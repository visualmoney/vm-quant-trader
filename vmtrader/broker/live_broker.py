"""
A Broker implementation backed by a live venue.

Three decisions from the design shape this class.

Submission does not wait for a fill (ADR-0006). The sizer produced
every target from one snapshot, so serialising submissions behind their
own fills would push the last order minutes past the first and make the
result less like the backtest, not more. Orders are accepted in a burst
and fills are collected afterwards, within a time budget.

Collection runs on a worker thread, but accounting does not (ADR-0008).
The worker polls and buffers; the main thread books. The portfolio has
no lock and enforces timestamp monotonicity, so it gets exactly one
writer.

Transactions are stamped with an engine clock, not with the venue's
fill time (ADR-0007). Fills are confirmed in whatever order the venue
answers, and a confirmation that arrives late carrying an earlier
timestamp would otherwise raise straight out of the portfolio.
"""

import logging
import threading
import time

import numpy as np
import pandas as pd

from vmtrader.broker.broker import Broker
from vmtrader.broker.fee_model.zero_fee_model import ZeroFeeModel
from vmtrader.broker.live import ledger as ledger_states
from vmtrader.broker.live.ledger import OrderLedger
from vmtrader.broker.live.guards import (
    OrderLimitExceeded, SafetyGuard, StopRequested
)
from vmtrader.broker.live.worker import TaskQueueWorker
from vmtrader.broker.portfolio.portfolio import Portfolio
from vmtrader.broker.transaction.transaction import Transaction
from vmtrader import settings

logger = logging.getLogger(__name__)

# How many open orders a settlement round was sized for. The fill
# worker's queue is deliberately not capped at this: its producer is
# the main thread, which posts one round and then blocks on the drain
# barrier, so the depth is already bounded by the open order count and
# there is no flood to defend against. Dropping here would be worse
# than useless -- the posting order is deterministic, so the same tail
# would be starved every round and those orders would reach the
# deadline never having been polled once.
#
# What the number is for is knowing. A round this large means the
# cycle has left the shape it was designed around, which is worth
# saying out loud rather than silently truncating.
POLL_ROUND_WARN = 200


class LiveBroker(Broker):
    """
    Trades Korean cash equities through a venue client.

    Parameters
    ----------
    start_dt : `pd.Timestamp`
        The engine timestamp the broker starts at.
    exchange : `Exchange`
        Decides whether the market is open.
    data_handler : `LiveDataHandler`
        Supplies marks for sizing and valuation.
    client : `BrokerClient`
        The venue. Injected, and never imported by the engine.
    ledger : `OrderLedger`
        The durable record of intent, submission and fills.
    account_id : `str`, optional
        Identifier used for the single portfolio this broker holds.
        Defaults to 'live'.
    base_currency : `str`, optional
        Account currency. Defaults to 'KRW'.
    venue_name : `str`, optional
        Names the venue in operational log lines and in the ledger
        stamp. The class itself is venue-neutral, so the only thing
        that would otherwise identify which broker an operator is
        reading is the line prefix. Taken from the client's 'venue'
        attribute when it has one; otherwise 'live'.
    fee_model : `FeeModel`, optional
        Used by the sizer to estimate costs. Actual fees come from the
        venue where it reports them.
    guard : `SafetyGuard`, optional
        Order limits and the kill switch. Defaults to an inert guard.
    clock : `callable`, optional
        Returns the current engine timestamp. Injected so tests can run
        without real time passing.
    poll_throttle : `pd.Timedelta`, optional
        Minimum engine time between the polling and marking that
        'update' performs. Defaults to one minute.
    ledger_factory : `callable`, optional
        Returns a ledger connection for the calling thread. A SQLite
        connection belongs to one thread, so the worker cannot borrow
        the main one. Defaults to opening another connection on the
        same path, which is why the ledger must be a file rather than
        an in-memory database in live use.
    """

    def __init__(
        self,
        start_dt,
        exchange,
        data_handler,
        client,
        ledger,
        account_id='live',
        base_currency='KRW',
        venue_name=None,
        fee_model=None,
        guard=None,
        clock=None,
        poll_throttle=None,
        ledger_factory=None
    ):
        self.start_dt = start_dt
        self.current_dt = start_dt
        self.exchange = exchange
        self.data_handler = data_handler
        self.client = client
        self.ledger = ledger
        self.account_id = account_id
        self.base_currency = base_currency
        # The gateway knows which venue it dialled and whether the
        # money is real; the engine cannot tell, because a paper
        # account answers identically. Explicit arguments win, so a
        # test double need not carry either.
        self.venue_name = (
            venue_name if venue_name is not None
            else getattr(client, 'venue', 'live')
        )
        self.mode = getattr(client, 'mode', ledger_states.UNKNOWN)
        self.fee_model = fee_model if fee_model is not None else ZeroFeeModel()
        self.guard = guard if guard is not None else SafetyGuard()
        self.clock = clock if clock is not None else (lambda: self.current_dt)
        self.poll_throttle = (
            poll_throttle if poll_throttle is not None
            else pd.Timedelta(seconds=60)
        )
        # Starts at the broker's own start time, so the burst of
        # per-order 'update' calls that immediately follows a rebalance
        # is suppressed rather than spending the rate limit.
        self._last_poll_dt = start_dt
        self.ledger_factory = (
            ledger_factory if ledger_factory is not None
            else self._open_thread_ledger
        )

        self.portfolios = {}
        self.open_orders = {}
        # Reconciliation sets this when the engine believes it holds
        # more than the venue reports; selling shares that are not
        # there is the failure it prevents. The state lives in the
        # guard, which is the one place a stop signal is read, and this
        # stays as the name reconciliation and the tests already use.
        self._fill_buffer = []
        self._buffer_lock = threading.Lock()
        # What the portfolio has, per order. Distinct from the
        # poller's watermark on purpose -- see _drain_fill_buffer.
        self._portfolio_booked = {}
        self._portfolio_charged = {}
        self._worker = None

        self.create_portfolio(account_id, account_id)
        # Raises if this ledger already belongs to a different
        # deployment, which is the only moment the mistake is cheap.
        self.ledger.stamp_identity(
            self.venue_name, self.mode, self.account_id
        )

    @property
    def trading_halted(self):
        """
        Return whether reconciliation stopped this session.

        A view onto the guard, which owns every stop signal. Kept as an
        attribute because that is how reconciliation and its tests
        speak; what changed is that setting it now reaches the one gate
        every loop consults, so a halt can raise instead of being read
        quietly in one place and nowhere else.

        Returns
        -------
        `Boolean`
            Whether trading is stopped.
        """
        return self.guard.is_halted()

    @trading_halted.setter
    def trading_halted(self, halted):
        """
        Halt or clear the session.

        Parameters
        ----------
        halted : `Boolean`
            Whether to stop trading.
        """
        if halted:
            self.guard.halt(
                'Reconciliation found the engine holding more than the '
                'venue reports.'
            )
        else:
            self.guard.halted_reason = None

    def _open_thread_ledger(self):
        """
        Open a ledger connection belonging to the calling thread.

        Returns
        -------
        `OrderLedger`
            A connection on the same database file.
        """
        return OrderLedger(self.ledger.path)

    # -- engine clock ----------------------------------------------------

    def _now(self):
        """
        Return an engine timestamp that never goes backwards.

        The portfolio raises on a timestamp earlier than the one it
        last saw, so a clock that stalls or steps back -- an NTP
        correction, a coarse system clock -- must not reach it.

        Returns
        -------
        `pd.Timestamp`
            The current engine timestamp, at least the previous one.
        """
        now = self.clock()
        if now < self.current_dt:
            return self.current_dt
        return now

    # -- portfolio ------------------------------------------------------

    def create_portfolio(self, portfolio_id, name=None):
        """
        Create the local portfolio mirroring the venue account.

        The account already exists at the venue; this only creates the
        engine's view of it.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID.
        name : `str`, optional
            A human-readable name.
        """
        portfolio_id_str = str(portfolio_id)
        if portfolio_id_str in self.portfolios:
            raise ValueError(
                "Portfolio with ID '%s' already exists." % portfolio_id_str
            )
        self.portfolios[portfolio_id_str] = Portfolio(
            self.current_dt,
            currency=self.base_currency,
            portfolio_id=portfolio_id_str,
            name=name
        )

    def list_all_portfolios(self):
        """
        Return every portfolio held by the broker.

        Returns
        -------
        `list[Portfolio]`
            The portfolios, of which there is one.
        """
        return list(self.portfolios.values())

    def seed_from_venue(self):
        """
        Rebuild the local portfolio from the venue's balance.

        This is how a live session starts and how it recovers: there is
        no persisted portfolio to reload, so the venue's holdings and
        projected cash are the starting truth.

        Cash is taken from the projected figure rather than the settled
        deposit, because Korean equities settle at D+2 and the engine's
        ledger deducts cash at fill time.
        """
        balance = self.client.get_balance()
        portfolio = self.portfolios[self.account_id]

        portfolio.cash = balance.cash
        portfolio.pos_handler.positions = {}

        for holding in balance.holdings:
            txn = Transaction(
                holding.symbol,
                holding.quantity,
                self.current_dt,
                holding.average_price,
                'seed-%s' % holding.symbol,
                commission=0.0
            )
            portfolio.pos_handler.transact_position(txn)

        # Seeding must not spend cash: the holdings were paid for
        # before this process existed, and the venue's cash figure
        # already reflects that.
        portfolio.cash = balance.cash

    def get_account_cash_balance(self, currency=None):
        """
        Return the cash held, by currency.

        Parameters
        ----------
        currency : `str`, optional
            Restrict to a single currency.

        Returns
        -------
        `dict{str: float}` or `float`
            All balances, or the one requested.
        """
        cash = self.portfolios[self.account_id].cash
        balances = {self.base_currency: cash}
        if currency is None:
            return balances
        if currency not in balances:
            raise ValueError(
                "Currency '%s' is not held in this account." % currency
            )
        return balances[currency]

    def get_account_total_equity(self):
        """
        Return total equity, including the 'master' key the trading
        session reads directly.

        Returns
        -------
        `dict{str: float}`
            Equity per portfolio plus the 'master' total.
        """
        equity = {}
        for portfolio_id, portfolio in self.portfolios.items():
            equity[portfolio_id] = portfolio.total_market_value + portfolio.cash
        equity['master'] = sum(equity.values())
        return equity

    def get_portfolio_cash_balance(self, portfolio_id):
        """
        Return the cash held in a portfolio.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID.

        Returns
        -------
        `float`
            The cash balance.
        """
        return self.portfolios[str(portfolio_id)].cash

    def get_portfolio_total_equity(self, portfolio_id):
        """
        Return the total equity of a portfolio.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID.

        Returns
        -------
        `float`
            The total equity.
        """
        return self.portfolios[str(portfolio_id)].total_equity

    def get_portfolio_total_market_value(self, portfolio_id):
        """
        Return the market value of a portfolio's positions.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID.

        Returns
        -------
        `float`
            The total market value.
        """
        return self.portfolios[str(portfolio_id)].total_market_value

    def get_portfolio_as_dict(self, portfolio_id):
        """
        Return the portfolio in the dictionary form the sizers consume.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID.

        Returns
        -------
        `dict{str: dict}`
            The portfolio representation.
        """
        return self.portfolios[str(portfolio_id)].portfolio_to_dict()

    # -- order submission ------------------------------------------------

    def _clamp_quantity(self, portfolio_id, order, price):
        """
        Reduce an order to what may actually be traded.

        Three limits apply, and all of them are refusals the venue
        would make anyway -- better to make them here, where the reason
        can be logged, than to have an order bounce.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio the order belongs to.
        order : `Order`
            The order to clamp.
        price : `float`
            The mark used for the cash check.

        Returns
        -------
        `int`
            The signed quantity to submit, possibly zero.
        """
        quantity = int(np.floor(abs(order.quantity))) * int(
            np.sign(order.quantity)
        )
        if quantity == 0:
            return 0

        portfolio = self.portfolios[portfolio_id]

        if quantity < 0:
            held = portfolio.portfolio_to_dict().get(
                order.asset, {}
            ).get('quantity', 0)
            if held <= 0:
                return 0
            # Retail accounts cannot short on KRX, so a sale is capped
            # at what is actually held.
            quantity = -min(abs(quantity), int(held))

        if quantity > 0:
            affordable = int(np.floor(portfolio.cash / price))
            if affordable <= 0:
                return 0
            quantity = min(quantity, affordable)

        return quantity

    def submit_order(self, portfolio_id, order):
        """
        Accept an order and return, without waiting for a fill.

        The fill is collected later, by 'settle' or by 'update'. That
        separation is the point: every order in a rebalance reaches the
        market within seconds of the snapshot the sizer used.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID.
        order : `Order`
            The order to submit.
        """
        portfolio_id_str = str(portfolio_id)
        dt = self._now()

        if not self.exchange.is_open_at_datetime(dt):
            self._log(
                'Market closed at %s; refusing order for %s.'
                % (dt, order.asset)
            )
            return

        price = self.data_handler.get_asset_latest_ask_price(dt, order.asset)
        quantity = self._clamp_quantity(portfolio_id_str, order, price)
        if quantity == 0:
            self._log(
                'Order for %s clamped to zero; not submitting.' % order.asset
            )
            return

        try:
            self.guard.check_order(order.asset, quantity, price)
        except (StopRequested, OrderLimitExceeded) as err:
            self.ledger.record_intent(
                order.order_id, order.asset, quantity, dt
            )
            self.ledger.record_state(
                order.order_id, ledger_states.REJECTED, dt, note=str(err)
            )
            self._log('Order for %s refused: %s' % (order.asset, err))
            if isinstance(err, StopRequested):
                raise
            return

        # Written before the venue is called, so a process that dies
        # mid-call leaves evidence of an order that may exist.
        self.ledger.record_intent(order.order_id, order.asset, quantity, dt)

        try:
            order_no = self.client.place_market_order(order.asset, quantity)
        except Exception as err:  # noqa: BLE001
            # Never retried: the venue's order endpoint is not
            # idempotent, so a retry risks a duplicate position.
            self.ledger.record_state(
                order.order_id, ledger_states.REJECTED, dt, note=str(err)
            )
            self._log('Venue rejected order for %s: %s' % (order.asset, err))
            return

        self.guard.record_submission()
        self.ledger.record_submitted(order.order_id, order_no, dt)
        self.open_orders[order_no] = {
            'order_id': order.order_id,
            'symbol': order.asset,
            'quantity': quantity,
            'portfolio_id': portfolio_id_str,
            'booked_quantity': 0,
            'booked_fees': 0.0
        }

    # -- fill settlement -------------------------------------------------

    def _poll_once(self, order_no, ledger):
        """
        Ask the venue about one order and buffer any new fill.

        Runs on the worker thread. It must not touch the portfolio: it
        appends to a buffer under a lock, and the main thread books
        from there.

        Quantity and fees are both reported cumulatively by the venue,
        and both are converted to increments here. Fees were once
        passed through whole, which charged the running total again on
        every increment: an order filling in three parts paid its
        estimated costs three times over. The ledger's 'record_fill'
        has always documented its 'fees' argument as belonging to the
        increment, so this is the code catching up with the contract.

        The fee figure is the venue's estimate and may be revised
        between polls. Advancing the booked total only when an
        increment is booked is what makes that safe: a revision
        arriving with no new quantity is not lost, it is folded into
        the next increment's difference. A revision after the last
        increment is not booked at all, which is the same limitation
        the average price already carries, and the same one
        reconciliation exists to catch.

        Parameters
        ----------
        order_no : `str`
            The venue order number.
        ledger : `OrderLedger`
            This thread's ledger connection, or None to skip recording.

        Returns
        -------
        `Boolean`
            Whether the order has reached a terminal state.
        """
        state = self.open_orders.get(order_no)
        if state is None:
            return True

        report = self.client.get_order_report(order_no)
        increment = report.filled_quantity - state['booked_quantity']

        if increment > 0:
            direction = 1 if state['quantity'] > 0 else -1
            fees = report.fees - state['booked_fees']
            fill = {
                'order_no': order_no,
                'order_id': state['order_id'],
                'portfolio_id': state['portfolio_id'],
                'symbol': state['symbol'],
                'direction': direction,
                'price': report.average_price,
                'cumulative_fees': report.fees,
                'cumulative_filled': report.filled_quantity
            }
            if ledger is not None:
                ledger.record_fill(
                    state['order_id'], order_no, report.filled_quantity,
                    direction * increment, report.average_price,
                    fees, self._now()
                )
            # Handed over whether or not the ledger had seen it. A row
            # already written says the ledger knows; it says nothing
            # about the portfolio, and conflating the two is how a
            # re-emission would be suppressed exactly when it is needed.
            with self._buffer_lock:
                self._fill_buffer.append(fill)
            state['booked_quantity'] = report.filled_quantity
            state['booked_fees'] = report.fees

        return report.is_done

    def _drain_fill_buffer(self):
        """
        Book buffered fills into the portfolio, on the main thread.

        Timestamps come from the engine clock rather than the venue, so
        fills confirmed out of order cannot trip the portfolio's
        monotonicity check.

        Returns
        -------
        `int`
            How many fills were booked.
        """
        with self._buffer_lock:
            pending = self._fill_buffer
            self._fill_buffer = []

        booked = 0
        for fill in pending:
            # Difference against what the *portfolio* has, not against
            # what the poller last saw. The two are different facts and
            # keeping them apart is what makes a lost handoff
            # recoverable: the venue reports cumulatively, so the next
            # message carries a total this side has not caught up to,
            # and the arithmetic here closes the gap on its own.
            #
            # Advance it here, on the thread that books, and never on
            # the producing side. A watermark moved by the producer
            # says "we have seen this" when what mattered was "the
            # portfolio has this" -- and once these messages travel a
            # mailbox that may drop, the difference is a fill that is
            # never re-emitted and never booked (report 20260826-01, M1).
            order_no = fill['order_no']
            already = self._portfolio_booked.get(order_no, 0)
            increment = fill['cumulative_filled'] - already
            if increment <= 0:
                continue

            charged = self._portfolio_charged.get(order_no, 0.0)
            fees = fill['cumulative_fees'] - charged

            dt = self._now()
            self.current_dt = dt
            txn = Transaction(
                fill['symbol'],
                fill['direction'] * increment,
                dt,
                fill['price'],
                fill['order_id'],
                commission=fees
            )
            self.portfolios[fill['portfolio_id']].transact_asset(txn)
            self._portfolio_booked[order_no] = fill['cumulative_filled']
            self._portfolio_charged[order_no] = fill['cumulative_fees']
            booked += 1
        return booked

    def settle(self, deadline, poll_interval=0.0, sleep=None,
               shutdown_timeout=30.0):
        """
        Collect fills for the open orders, within a time budget.

        The budget exists because the market closes. Anything still
        open when it expires is marked stale rather than waited on: a
        late fill is absorbed by the next 'update', and the unfilled
        remainder is picked up by the next rebalance.

        The kill switch ends settlement too, and it does not mark
        anything stale. Being told to stop is not the same fact as
        having given up: the orders are still working at the venue, and
        STALE is terminal, so marking them would remove them from
        'get_open_orders' and leave the next launch with no way to ask
        about them. Distinguishing the two exits is what makes the
        operations manual's promise -- left open, tidied by the next
        launch -- actually true.

        Polling runs on a worker thread so that the main thread stays
        free to watch the kill switch and the deadline.

        The drain barrier before each booking is never abandoned, since
        it is what gives the portfolio a single writer. It is only
        broken into to report a round that is taking longer than a
        share of the remaining budget, so that a wedged poll is named
        in the log rather than passing as a quiet cycle.

        Parameters
        ----------
        deadline : `pd.Timestamp`
            When to stop collecting.
        poll_interval : `float`, optional
            Seconds to wait between rounds.
        sleep : `callable`, optional
            Injected sleep, so tests need not spend real time.
        shutdown_timeout : `float`, optional
            Seconds to wait for the fill worker to end. Sized from what
            the gateway allows one call: a connect and a read, with the
            fill enquiry never retried, so a worker still running after
            this has stalled somewhere no timeout reaches. Reported
            rather than enforced -- the point is that the stall is
            named in the log instead of passing as a normal exit.

        Returns
        -------
        `int`
            How many fills were booked.
        """
        sleeper = sleep if sleep is not None else (lambda _: None)
        booked = 0
        warned_on_round_size = False
        stopped_by_operator = False
        worker = TaskQueueWorker(on_error=self._log_error)
        self._worker = worker
        worker.start()

        try:
            while self.open_orders:
                if self._now() >= deadline:
                    break
                if self.guard.is_kill_switch_engaged():
                    self._log('Kill switch engaged; stopping settlement.')
                    stopped_by_operator = True
                    break

                done = []
                posted = list(self.open_orders)
                # Once per settlement, not once per round: the point is
                # to learn that the cycle is oversized, and repeating it
                # every round would bury the rest of the log. It goes to
                # the logger rather than through '_log' because a
                # tripwire a settings flag can silence is not a
                # tripwire.
                if not warned_on_round_size and (
                    len(posted) > POLL_ROUND_WARN
                ):
                    warned_on_round_size = True
                    logger.warning(
                        'Settling %d open orders in one round, beyond the '
                        '%d this cycle is sized for. Nothing is dropped; '
                        'expect the round to take proportionally longer '
                        'and the time budget to bind sooner.',
                        len(posted), POLL_ROUND_WARN
                    )
                round_started = time.monotonic()
                for order_no in posted:
                    worker.post_task({
                        'runnable': self._poll_task,
                        'order_no': order_no,
                        'done': done
                    })
                # 드레인은 끝까지 기다린다 -- 이 배리어가 곧 회계의 단일
                # 작성자 규율이다(ADR-0008). 다만 남은 예산에 비례한 간격으로
                # 한 번 짚어, 멈춘 폴이 사이클을 조용히 먹는 일이 없게 한다.
                # 예산이 한 시간이면 첫 짚음은 15분, 마감이 가까울수록 짧아진다.
                heartbeat = max(
                    1.0, (deadline - self._now()).total_seconds() / 4
                )
                overran = not worker.join_tasks(timeout=heartbeat)
                if overran:
                    self._log(
                        'Fill polling has not drained in %.0fs; still '
                        'waiting.' % heartbeat
                    )
                    worker.join_tasks()

                # 라운드마다 남긴다. 하트비트의 1/4도, 게이트웨이의 (5, 15)도
                # 관측 없이 고른 값이라, 이 기록이 쌓여야 실측 분포로 바꿀 수
                # 있다. debug 인 것은 운용 로그가 아니라 표본이기 때문이다.
                logger.debug(
                    'settle drain orders=%d elapsed=%.3f heartbeat=%.1f '
                    'overran=%s',
                    len(posted), time.monotonic() - round_started,
                    heartbeat, overran
                )

                booked += self._drain_fill_buffer()
                for order_no in done:
                    self._close_order(order_no, ledger_states.FILLED)

                if self.open_orders:
                    sleeper(poll_interval)
        finally:
            if not worker.stop(timeout=shutdown_timeout):
                self._log(
                    'Fill worker did not stop within %ss; a poll is '
                    'still running.' % shutdown_timeout
                )
            self._worker = None
            booked += self._drain_fill_buffer()

        # Why the loop ended decides how the remainder is closed, and
        # the two reasons are not interchangeable.
        #
        # The budget expiring means we stopped caring: STALE is honest,
        # and a late fill is absorbed by the next 'update' or the next
        # rebalance.
        #
        # The kill switch means somebody told us to stop. The orders
        # are still working at the venue, and STALE is terminal --
        # 'get_open_orders' skips terminal rows, so marking them would
        # be throwing away the only hook by which the next launch's
        # reconciliation could ever ask about them again. They stay
        # SUBMITTED, which is what they are.
        if stopped_by_operator:
            if self.open_orders:
                self._log(
                    '%d order(s) left working at the venue; they stay '
                    'SUBMITTED so the next launch settles them.'
                    % len(self.open_orders)
                )
            return booked

        for order_no in list(self.open_orders):
            self._close_order(
                order_no, ledger_states.STALE,
                note='Unfilled when the time budget expired.'
            )
        return booked

    def _poll_task(self, task):
        """
        Worker task: poll one order and note whether it is finished.

        Parameters
        ----------
        task : `dict`
            Carries 'order_no' and the shared 'done' list.
        """
        ledger = None
        if self.ledger_factory is not None:
            ledger = self.ledger_factory()
        try:
            if self._poll_once(task['order_no'], ledger):
                task['done'].append(task['order_no'])
        finally:
            if ledger is not None:
                ledger.close()

    def _close_order(self, order_no, state, note=None):
        """
        Move an order out of the open set and record its end state.

        Parameters
        ----------
        order_no : `str`
            The venue order number.
        state : `str`
            The terminal ledger state.
        note : `str`, optional
            A reason for the audit trail.
        """
        order = self.open_orders.pop(order_no, None)
        if order is None:
            return
        self.ledger.record_state(
            order['order_id'], state, self._now(), note=note
        )

    # -- session ---------------------------------------------------------

    def update(self, dt, force=False):
        """
        Advance the broker: absorb late fills and mark to market.

        Called after each submission and on every session event. Late
        fills of orders abandoned by an earlier deadline arrive here,
        which is why leaving them stale is safe.

        The work is throttled. The execution handler calls this after
        every single order, which in a backtest is free but live would
        spend the venue's rate limit on answers nobody is waiting for,
        and would book fills for the first name of a rebalance while
        the last name has not yet been sent. Collecting fills is the
        job of 'settle', which runs after the whole burst; this method
        only needs to catch what arrives between cycles.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The timestamp to advance to. Never moves the broker back.
        force : `Boolean`, optional
            Poll and mark regardless of the throttle.
        """
        if dt > self.current_dt:
            self.current_dt = dt

        if not force and dt - self._last_poll_dt < self.poll_throttle:
            return
        self._last_poll_dt = dt

        if self.open_orders:
            done = []
            for order_no in list(self.open_orders):
                if self._poll_once(order_no, self.ledger):
                    done.append(order_no)
            self._drain_fill_buffer()
            for order_no in done:
                self._close_order(order_no, ledger_states.FILLED)

        self._mark_to_market()

    def _mark_to_market(self):
        """
        Revalue every held position at the venue's current price.

        A symbol the venue will not price is left at its previous
        valuation rather than zeroed, since a missing quote is not
        evidence that a position became worthless.
        """
        self.data_handler.clear_cache()
        dt = self._now()
        self.current_dt = dt

        for portfolio in self.portfolios.values():
            for symbol in list(portfolio.pos_handler.positions.keys()):
                try:
                    price = self.data_handler.get_asset_latest_mid_price(
                        dt, symbol
                    )
                except Exception as err:  # noqa: BLE001
                    self._log(
                        'No mark for %s (%s); keeping the previous '
                        'valuation.' % (symbol, err)
                    )
                    continue
                portfolio.update_market_value_of_asset(symbol, price, dt)

    def record_equity(self):
        """
        Append the current total equity to the ledger's curve.

        Recorded once at the market close, matching where a backtest
        records it, so the statistics layer means the same thing in
        both.
        """
        self.ledger.record_equity(
            self._now(), self.get_account_total_equity()['master'],
            mode=self.mode
        )

    # -- logging ---------------------------------------------------------

    def _log(self, message):
        """
        Print an operational message, honouring the events setting.

        Parameters
        ----------
        message : `str`
            The message to print.
        """
        if settings.PRINT_EVENTS:
            print(
                '(%s) - %s broker: %s'
                % (self.current_dt, self.venue_name, message)
            )

    def _log_error(self, err):
        """
        Report an exception raised inside a worker task.

        Parameters
        ----------
        err : `Exception`
            The exception raised.
        """
        self._log('Fill polling failed: %s' % err)
