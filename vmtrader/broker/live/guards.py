"""
Pre-trade safety limits for live trading.

These are deliberately dumb. They know nothing about strategy, only
about magnitudes and a stop signal, so that a bug in the interesting
parts of the engine still runs into a wall before it can place a
hundred orders or one enormous one.
"""

import os

from vmtrader.errors import StopRequested


class KillSwitchEngaged(StopRequested):
    """
    Raised when the kill switch is engaged and an order is attempted.
    """


class OrderLimitExceeded(Exception):
    """
    Raised when an order breaches a configured limit.
    """


class TradingHalted(StopRequested):
    """
    Raised when reconciliation stopped this session.

    Believing we hold more than the venue reports leads to selling
    shares that are not there, so the mismatch halts trading until a
    human looks. It sits beside the kill switch rather than in a flag
    of its own because it is the same kind of fact -- trading must
    stop, one way, no automatic resumption -- and until now it was the
    only stop signal that could not raise, so no loop could see it.
    """


class SafetyGuard:
    """
    Enforces the per-order and per-session limits, and the kill switch.

    The kill switch is a file: if it exists, trading stops. A file is
    used rather than a signal or a socket because the process that
    trades is not always running, and whoever flips the switch -- an
    operator at a shell, or the Telegram gateway -- must be able to do
    so between sessions as well as during one. The engine checks it at
    launch, before every submission and on every poll, so the longest
    it can be ignored is one venue round trip.

    Parameters
    ----------
    kill_switch_path : `str`, optional
        Path whose existence halts trading. Without one, the kill
        switch is disabled, which suits tests but not live use.
    max_order_value : `float`, optional
        The largest consideration a single order may carry, in account
        currency. Without one, order value is unlimited.
    max_orders_per_session : `int`, optional
        The most orders that may be submitted in one session. Without
        one, the count is unlimited.
    """

    def __init__(
        self,
        kill_switch_path=None,
        max_order_value=None,
        max_orders_per_session=None
    ):
        self.kill_switch_path = kill_switch_path
        self.max_order_value = max_order_value
        self.max_orders_per_session = max_orders_per_session
        self.orders_submitted = 0
        self.halted_reason = None

    def is_kill_switch_engaged(self):
        """
        Return whether the kill switch file is present.

        Returns
        -------
        `Boolean`
            Whether trading is halted.
        """
        if self.kill_switch_path is None:
            return False
        return os.path.exists(self.kill_switch_path)

    def halt(self, reason):
        """
        Stop this session, and record why.

        The counterpart to the kill switch for a stop the engine
        decides on rather than one an operator throws. It does not
        clear: resuming means a new session, once a human has looked.

        Parameters
        ----------
        reason : `str`
            What made it necessary. Carried into the exception, since
            "trading is halted" without a cause is not actionable.
        """
        self.halted_reason = reason

    def is_halted(self):
        """
        Return whether this session has been halted.

        Returns
        -------
        `Boolean`
            Whether trading is stopped for a reason of the engine's.
        """
        return self.halted_reason is not None

    def check_can_trade(self):
        """
        Raise if trading is stopped, without reference to any order.

        **The single gate.** Every stop signal is read here and
        nowhere else, so that adding one means adding a branch rather
        than a fourth place that has to be remembered. D14 invariant 4
        asks for exactly this, and until the halt moved in there were
        four reading sites in three different shapes -- one of which
        returned quietly and so could never reach a loop.

        Called on entry to a cycle and on every poll, so that a switch
        thrown mid-session takes effect at the next opportunity rather
        than at the next session.

        Raises
        ------
        `StopRequested`
            'KillSwitchEngaged' if an operator threw the switch,
            'TradingHalted' if reconciliation stopped this session.
        """
        if self.is_kill_switch_engaged():
            raise KillSwitchEngaged(
                "Kill switch file '%s' is present. Trading is halted."
                % self.kill_switch_path
            )
        if self.is_halted():
            raise TradingHalted(self.halted_reason)

    def check_order(self, symbol, quantity, price):
        """
        Raise if the order breaches a limit or trading is halted.

        Parameters
        ----------
        symbol : `str`
            The engine symbol, used in the exception message.
        quantity : `int`
            The signed quantity of the order.
        price : `float`
            The price used to value the order.
        """
        self.check_can_trade()

        value = abs(quantity) * price
        if self.max_order_value is not None and value > self.max_order_value:
            raise OrderLimitExceeded(
                "Order for %s of %s at %s is worth %.2f, above the "
                "per-order limit of %.2f."
                % (symbol, quantity, price, value, self.max_order_value)
            )

        if (
            self.max_orders_per_session is not None
            and self.orders_submitted >= self.max_orders_per_session
        ):
            raise OrderLimitExceeded(
                "Session order limit of %s reached; refusing to submit "
                "an order for %s." % (self.max_orders_per_session, symbol)
            )

    def record_submission(self):
        """
        Count an order that reached the venue.

        Counted on submission rather than on the check, so that an
        order rejected by a limit does not consume the session budget.
        """
        self.orders_submitted += 1
