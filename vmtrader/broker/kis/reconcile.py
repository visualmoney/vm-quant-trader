"""
Bring the engine's view of the account back in line with the venue's.

A live session starts with no memory. The portfolio is rebuilt from the
venue, and the ledger says what the previous process was doing when it
stopped -- which is not always the same as what it had finished doing.

The asymmetry in how disagreements are handled is deliberate. Believing
we hold more than we do leads to selling shares that are not there, so
that halts trading. Holding something the engine did not buy is
somebody else trading the same account by hand, which is not our
business to undo.
"""

from vmtrader.broker.kis import ledger as ledger_states


class ReconcileResult:
    """
    What a reconciliation found.

    Parameters
    ----------
    resolved_orders : `list[str]`
        Orders that were open in the ledger and have now been settled
        against the venue.
    orphan_intents : `list[str]`
        Orders recorded as intended but with no venue order number.
    overstated : `dict{str: tuple}`
        Symbols where the engine believes it holds more than the venue
        reports, as (local, venue) quantities.
    untracked : `dict{str: int}`
        Symbols the venue reports that the engine does not hold.
    halt_trading : `Boolean`
        Whether trading must stop until a human looks.
    """

    def __init__(
        self,
        resolved_orders=None,
        orphan_intents=None,
        overstated=None,
        untracked=None
    ):
        self.resolved_orders = resolved_orders or []
        self.orphan_intents = orphan_intents or []
        self.overstated = overstated or {}
        self.untracked = untracked or {}
        self.halt_trading = bool(self.overstated) or bool(self.orphan_intents)

    def summary(self):
        """
        Return a one-line human summary.

        Returns
        -------
        `str`
            The summary.
        """
        return (
            'reconcile: %d order(s) settled, %d orphan intent(s), '
            '%d overstated, %d untracked, halt=%s'
            % (
                len(self.resolved_orders), len(self.orphan_intents),
                len(self.overstated), len(self.untracked), self.halt_trading
            )
        )


def reconcile(broker, halt_on_mismatch=True):
    """
    Settle orders left open by a previous process, then compare
    positions against the venue.

    Runs before a session trades. Order recovery happens first, since
    an unrecorded fill is itself a source of position disagreement.

    Parameters
    ----------
    broker : `KisBroker`
        The broker to reconcile. Its portfolio is rebuilt from the
        venue as part of this.
    halt_on_mismatch : `Boolean`, optional
        Whether to engage the halt on an overstatement. Passing False
        reports without stopping, which suits an inspection tool.

    Returns
    -------
    `ReconcileResult`
        What was found.
    """
    resolved, orphans = _recover_open_orders(broker)

    local = dict(
        (symbol, position['quantity'])
        for symbol, position in broker.get_portfolio_as_dict(
            broker.account_id
        ).items()
    )
    broker.seed_from_venue()
    venue = dict(
        (symbol, position['quantity'])
        for symbol, position in broker.get_portfolio_as_dict(
            broker.account_id
        ).items()
    )

    overstated = {}
    for symbol, quantity in local.items():
        held = venue.get(symbol, 0)
        if quantity > held:
            overstated[symbol] = (quantity, held)

    untracked = dict(
        (symbol, quantity) for symbol, quantity in venue.items()
        if symbol not in local
    )

    result = ReconcileResult(resolved, orphans, overstated, untracked)
    if result.halt_trading and halt_on_mismatch:
        # Two findings stop trading, for the same underlying reason:
        # the engine's picture is wrong somewhere it cannot see.
        # Overstating a holding leads to selling shares that are not
        # there, and an intent with no order number may be an order
        # already working at the venue that a second attempt would
        # duplicate.
        broker.trading_halted = True
    return result


def _recover_open_orders(broker):
    """
    Ask the venue about every order the ledger left open.

    Parameters
    ----------
    broker : `KisBroker`
        The broker whose ledger and client are used.

    Returns
    -------
    `tuple[list, list]`
        The order numbers settled, and the order IDs with no order
        number to settle against.
    """
    resolved = []
    orphans = []

    for row in broker.ledger.get_open_orders():
        order_no = row['order_no']
        if order_no is None:
            # The process died between recording the intent and
            # hearing back, so the order may or may not exist. The
            # position comparison below is the real defence.
            orphans.append(row['order_id'])
            broker.ledger.record_state(
                row['order_id'], ledger_states.REJECTED, broker._now(),
                note='No order number recorded; the venue may still have '
                     'accepted it. Verify against the balance.'
            )
            continue

        broker.open_orders[order_no] = {
            'order_id': row['order_id'],
            'symbol': row['symbol'],
            'quantity': row['quantity'],
            'portfolio_id': broker.account_id,
            'booked_quantity': _already_booked(broker, row['order_id'])
        }
        if broker._poll_once(order_no, broker.ledger):
            resolved.append(order_no)

    broker._drain_fill_buffer()
    for order_no in resolved:
        broker._close_order(order_no, ledger_states.FILLED)
    return resolved, orphans


def _already_booked(broker, order_id):
    """
    Return how much of an order the ledger has already accounted for.

    Without this, recovery would treat the venue's cumulative total as
    entirely new and book fills that were already in the portfolio
    before the process restarted.

    Parameters
    ----------
    broker : `KisBroker`
        The broker whose ledger is read.
    order_id : `str`
        The engine order ID.

    Returns
    -------
    `int`
        The quantity already booked, unsigned.
    """
    fills = broker.ledger.get_fills(order_id)
    return sum(abs(row['quantity']) for row in fills)
