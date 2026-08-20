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

import threading

import numpy as np
import pandas as pd

from vmtrader.broker.broker import Broker
from vmtrader.broker.fee_model.zero_fee_model import ZeroFeeModel
from vmtrader.broker.kis import ledger as ledger_states
from vmtrader.broker.kis.ledger import OrderLedger
from vmtrader.broker.kis.guards import (
    KillSwitchEngaged, OrderLimitExceeded, SafetyGuard
)
from vmtrader.broker.kis.worker import TaskQueueWorker
from vmtrader.broker.portfolio.portfolio import Portfolio
from vmtrader.broker.transaction.transaction import Transaction
from vmtrader import settings


class KisBroker(Broker):
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
    account_id : `str`
        Identifier used for the single portfolio this broker holds.
    base_currency : `str`, optional
        Account currency. Defaults to 'KRW'.
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
        account_id='kis',
        base_currency='KRW',
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
        self._fill_buffer = []
        self._buffer_lock = threading.Lock()
        self._worker = None

        self.create_portfolio(account_id, account_id)

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

    # -- funding: unsupported -------------------------------------------

    def _reject_funding(self, method):
        """
        Raise for a funding operation the venue does not offer.

        Parameters
        ----------
        method : `str`
            The method name, used in the message.
        """
        raise NotImplementedError(
            "%s is not supported against a live account. The venue has no "
            "transfer API, so moving cash locally would desynchronise the "
            "engine from the account immediately. Fund the account with "
            "the broker directly; the engine reads the balance." % method
        )

    def subscribe_funds_to_account(self, amount):
        """
        Not supported against a live account.

        Parameters
        ----------
        amount : `float`
            Ignored.
        """
        self._reject_funding('subscribe_funds_to_account')

    def withdraw_funds_from_account(self, amount):
        """
        Not supported against a live account.

        Parameters
        ----------
        amount : `float`
            Ignored.
        """
        self._reject_funding('withdraw_funds_from_account')

    def subscribe_funds_to_portfolio(self, portfolio_id, amount):
        """
        Not supported against a live account.

        Parameters
        ----------
        portfolio_id : `str`
            Ignored.
        amount : `float`
            Ignored.
        """
        self._reject_funding('subscribe_funds_to_portfolio')

    def withdraw_funds_from_portfolio(self, portfolio_id, amount):
        """
        Not supported against a live account.

        Parameters
        ----------
        portfolio_id : `str`
            Ignored.
        amount : `float`
            Ignored.
        """
        self._reject_funding('withdraw_funds_from_portfolio')

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
        except (KillSwitchEngaged, OrderLimitExceeded) as err:
            self.ledger.record_intent(
                order.order_id, order.asset, quantity, dt
            )
            self.ledger.record_state(
                order.order_id, ledger_states.REJECTED, dt, note=str(err)
            )
            self._log('Order for %s refused: %s' % (order.asset, err))
            if isinstance(err, KillSwitchEngaged):
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
            'booked_quantity': 0
        }

    # -- fill settlement -------------------------------------------------

    def _poll_once(self, order_no, ledger):
        """
        Ask the venue about one order and buffer any new fill.

        Runs on the worker thread. It must not touch the portfolio: it
        appends to a buffer under a lock, and the main thread books
        from there.

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
            fill = {
                'order_no': order_no,
                'order_id': state['order_id'],
                'portfolio_id': state['portfolio_id'],
                'symbol': state['symbol'],
                'quantity': direction * increment,
                'price': report.average_price,
                'fees': report.fees,
                'cumulative_filled': report.filled_quantity
            }
            booked = True
            if ledger is not None:
                booked = ledger.record_fill(
                    state['order_id'], order_no, report.filled_quantity,
                    direction * increment, report.average_price,
                    report.fees, self._now()
                )
            if booked:
                with self._buffer_lock:
                    self._fill_buffer.append(fill)
            state['booked_quantity'] = report.filled_quantity

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

        for fill in pending:
            dt = self._now()
            self.current_dt = dt
            txn = Transaction(
                fill['symbol'],
                fill['quantity'],
                dt,
                fill['price'],
                fill['order_id'],
                commission=fill['fees']
            )
            self.portfolios[fill['portfolio_id']].transact_asset(txn)
        return len(pending)

    def settle(self, deadline, poll_interval=0.0, sleep=None):
        """
        Collect fills for the open orders, within a time budget.

        The budget exists because the market closes. Anything still
        open when it expires is marked stale rather than waited on: a
        late fill is absorbed by the next 'update', and the unfilled
        remainder is picked up by the next rebalance.

        Polling runs on a worker thread so that the main thread stays
        free to watch the kill switch and the deadline.

        Parameters
        ----------
        deadline : `pd.Timestamp`
            When to stop collecting.
        poll_interval : `float`, optional
            Seconds to wait between rounds.
        sleep : `callable`, optional
            Injected sleep, so tests need not spend real time.

        Returns
        -------
        `int`
            How many fills were booked.
        """
        sleeper = sleep if sleep is not None else (lambda _: None)
        booked = 0
        worker = TaskQueueWorker(on_error=self._log_error)
        self._worker = worker
        worker.start()

        try:
            while self.open_orders:
                if self._now() >= deadline:
                    break
                if self.guard.is_kill_switch_engaged():
                    self._log('Kill switch engaged; stopping settlement.')
                    break

                done = []
                for order_no in list(self.open_orders):
                    worker.post_task({
                        'runnable': self._poll_task,
                        'order_no': order_no,
                        'done': done
                    })
                worker.join_tasks()

                booked += self._drain_fill_buffer()
                for order_no in done:
                    self._close_order(order_no, ledger_states.FILLED)

                if self.open_orders:
                    sleeper(poll_interval)
        finally:
            worker.stop()
            self._worker = None
            booked += self._drain_fill_buffer()

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
            self._now(), self.get_account_total_equity()['master']
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
            print('(%s) - kis broker: %s' % (self.current_dt, message))

    def _log_error(self, err):
        """
        Report an exception raised inside a worker task.

        Parameters
        ----------
        err : `Exception`
            The exception raised.
        """
        self._log('Fill polling failed: %s' % err)
