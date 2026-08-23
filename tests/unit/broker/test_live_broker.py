import datetime
import logging
import re

import pandas as pd
import pytest

from vmtrader import settings
from vmtrader.broker.fee_model.korea_fee_model import KoreaStockFeeModel
from vmtrader.broker.live import ledger as ledger_states
from vmtrader.broker.live.client import AccountBalance, Holding, OrderReport
from vmtrader.broker.live.guards import KillSwitchEngaged, SafetyGuard
from vmtrader.broker.live.ledger import OrderLedger
from vmtrader.broker.live_broker import LiveBroker
from vmtrader.data.live_data_handler import LiveDataHandler
from vmtrader.exchange.krx_exchange import KrxExchange
from vmtrader.execution.order import Order


@pytest.fixture(autouse=True)
def _quiet_events():
    """
    Silence the engine's event printing for these tests only.

    'PRINT_EVENTS' is module-level global state, so setting it at
    import time leaks into every test that runs afterwards -- including
    one that asserts on printed output.
    """
    previous = settings.PRINT_EVENTS
    settings.set_print_events(False)
    yield
    settings.set_print_events(previous)


class FakeClient:
    """
    A venue that fills orders on a schedule the test decides.

    Records every call, so tests can assert on what reached the venue
    as well as on what came back.
    """

    def __init__(self, price=10000.0, fill_plan=None, balance=None,
                 reject=False):
        self.price = price
        self.fill_plan = fill_plan or {}
        self.balance = balance
        self.reject = reject
        self.placed = []
        self.reports_served = []
        self._next_no = 0
        self._poll_counts = {}

    def place_market_order(self, symbol, quantity):
        if self.reject:
            raise RuntimeError('venue refused the order')
        self._next_no += 1
        order_no = '%04d' % self._next_no
        self.placed.append((symbol, quantity, order_no))
        return order_no

    def get_order_report(self, order_no):
        count = self._poll_counts.get(order_no, 0)
        self._poll_counts[order_no] = count + 1
        plan = self.fill_plan.get(order_no)
        if plan is None:
            requested = abs(
                next(q for _, q, no in self.placed if no == order_no)
            )
            report = OrderReport(
                order_no, requested, self.price, 0, 0, 0.0, True
            )
        else:
            report = plan[min(count, len(plan) - 1)]
        self.reports_served.append(report)
        return report

    def get_balance(self):
        return self.balance

    def get_price(self, symbol):
        return self.price

    def get_trading_day(self, date_str):
        return True


def _poll_driven_clock(client, expire_after):
    """
    Build a clock that jumps past the deadline once the venue has been
    polled a given number of times.

    Driving the clock from venue polls rather than from wall time keeps
    these tests deterministic: the broker reads the time an
    implementation-defined number of times per round, but it polls
    exactly once per open order per round.
    """
    def now():
        if len(client.reports_served) >= expire_after:
            return pd.Timestamp('2026-08-20 12:00:00')
        return pd.Timestamp('2026-08-20 10:00:00')
    return now


def _broker(client, tmp_path, guard=None, cash=1000000.0, clock=None):
    """
    Build a broker seeded with cash and no positions.
    """
    start = pd.Timestamp('2026-08-20 10:00:00')
    ledger = OrderLedger(str(tmp_path / 'ledger.db'))
    broker = LiveBroker(
        start_dt=start,
        exchange=KrxExchange(),
        data_handler=LiveDataHandler(client),
        client=client,
        ledger=ledger,
        fee_model=KoreaStockFeeModel(commission_pct=0.00015, tax_pct=0.0018),
        guard=guard,
        clock=clock
    )
    broker.portfolios[broker.account_id].cash = cash
    return broker


def test_submit_order_returns_before_the_fill_arrives(tmp_path):
    """
    Tests that submission does not wait for a fill.

    This is the whole reason ADR-0006 exists: a blocking submission
    would push the last order of a rebalance minutes past the first.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path)
    order = Order(broker.current_dt, 'EQ:005930', 10)

    broker.submit_order(broker.account_id, order)

    assert len(client.placed) == 1
    assert client.reports_served == []
    assert broker.get_portfolio_as_dict(broker.account_id) == {}


def test_settle_books_the_fill_into_the_portfolio(tmp_path):
    """
    Tests that settlement moves the position and the cash.
    """
    client = FakeClient(price=10000.0)
    broker = _broker(client, tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    booked = broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    assert booked == 1
    holding = broker.get_portfolio_as_dict(broker.account_id)['EQ:005930']
    assert holding['quantity'] == 10
    assert broker.get_portfolio_cash_balance(broker.account_id) < 1000000.0


def test_partial_fill_books_only_what_filled(tmp_path):
    """
    Tests that an order that never completes books its filled part and
    is left stale rather than waited on forever.
    """
    plan = {
        '0001': [
            OrderReport('0001', 4, 10000.0, 6, 0, 0.0, False),
            OrderReport('0001', 4, 10000.0, 6, 0, 0.0, False),
        ]
    }
    client = FakeClient(fill_plan=plan)
    broker = _broker(client, tmp_path)
    order = Order(broker.current_dt, 'EQ:005930', 10)
    broker.submit_order(broker.account_id, order)

    broker.clock = _poll_driven_clock(client, expire_after=2)
    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    holding = broker.get_portfolio_as_dict(broker.account_id)['EQ:005930']
    assert holding['quantity'] == 4
    assert broker.ledger.get_order(order.order_id)['state'] == (
        ledger_states.STALE
    )


def test_incremental_fills_are_booked_once_each(tmp_path):
    """
    Tests that cumulative venue snapshots become increments.

    The venue reports totals, not deltas, so a naive reading would book
    the same shares on every poll.
    """
    plan = {
        '0001': [
            OrderReport('0001', 3, 10000.0, 7, 0, 0.0, False),
            OrderReport('0001', 7, 10000.0, 3, 0, 0.0, False),
            OrderReport('0001', 10, 10000.0, 0, 0, 0.0, True),
        ]
    }
    client = FakeClient(fill_plan=plan)
    broker = _broker(client, tmp_path)
    order = Order(broker.current_dt, 'EQ:005930', 10)
    broker.submit_order(broker.account_id, order)
    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    holding = broker.get_portfolio_as_dict(broker.account_id)['EQ:005930']
    assert holding['quantity'] == 10
    fills = broker.ledger.get_fills(order.order_id)
    assert [row['quantity'] for row in fills] == [3, 4, 3]


def test_zero_fill_leaves_the_portfolio_untouched(tmp_path):
    """
    Tests that an unfilled order creates no transaction.
    """
    plan = {'0001': [OrderReport('0001', 0, 0.0, 10, 0, 0.0, False)]}
    client = FakeClient(fill_plan=plan)
    broker = _broker(client, tmp_path)
    before = broker.get_portfolio_cash_balance(broker.account_id)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )

    broker.clock = _poll_driven_clock(client, expire_after=2)
    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    assert broker.get_portfolio_as_dict(broker.account_id) == {}
    assert broker.get_portfolio_cash_balance(broker.account_id) == before


def test_fills_confirmed_out_of_order_do_not_raise(tmp_path):
    """
    Tests the crash this design exists to avoid.

    Two orders fill at different venue times and are confirmed in the
    opposite order. Stamping transactions with the venue's fill time
    would raise out of the portfolio's monotonicity check; the engine
    clock never goes backwards, so it does not.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path, cash=10000000.0)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:000660', 10)
    )
    broker.open_orders = dict(reversed(list(broker.open_orders.items())))

    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    holdings = broker.get_portfolio_as_dict(broker.account_id)
    assert holdings['EQ:005930']['quantity'] == 10
    assert holdings['EQ:000660']['quantity'] == 10


def test_a_clock_that_steps_backwards_is_clamped(tmp_path):
    """
    Tests that a clock correction cannot push a transaction into the
    portfolio's past.
    """
    client = FakeClient()
    times = iter([
        pd.Timestamp('2026-08-20 10:00:00'),
        pd.Timestamp('2026-08-20 09:00:00'),
    ])
    broker = _broker(
        client, tmp_path, clock=lambda: next(times, pd.Timestamp(
            '2026-08-20 10:30:00'
        ))
    )
    assert broker._now() == pd.Timestamp('2026-08-20 10:00:00')
    assert broker._now() >= pd.Timestamp('2026-08-20 10:00:00')


def test_short_sales_are_refused(tmp_path):
    """
    Tests that a sale beyond the holding is refused, since retail
    accounts cannot short on KRX.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', -15)
    )
    assert client.placed == []


def test_sales_are_clamped_to_the_holding(tmp_path):
    """
    Tests that selling more than is held sells only what is held.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', -25)
    )
    assert client.placed[-1][1] == -10


def test_buys_are_clamped_to_available_cash(tmp_path):
    """
    Tests that a buy beyond the cash balance is reduced rather than
    executed into a negative balance, which the simulated broker allows
    and a venue does not.
    """
    client = FakeClient(price=10000.0)
    broker = _broker(client, tmp_path, cash=55000.0)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    assert client.placed[0][1] == 5


def test_fractional_quantities_are_floored(tmp_path):
    """
    Tests that fractional sizes become whole shares, and that a size
    below one share is not sent at all.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 1.4)
    )
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:000660', 0.9)
    )
    assert [p[1] for p in client.placed] == [1]


def test_orders_are_refused_when_the_market_is_closed(tmp_path):
    """
    Tests that nothing is submitted outside the session.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path)
    broker.current_dt = pd.Timestamp('2026-08-20 16:00:00')
    broker.clock = lambda: pd.Timestamp('2026-08-20 16:00:00')
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    assert client.placed == []


def test_kill_switch_stops_submission(tmp_path):
    """
    Tests that the kill switch halts trading and is recorded.
    """
    switch = tmp_path / 'HALT'
    switch.write_text('')
    client = FakeClient()
    broker = _broker(
        client, tmp_path, guard=SafetyGuard(kill_switch_path=str(switch))
    )
    order = Order(broker.current_dt, 'EQ:005930', 10)

    with pytest.raises(KillSwitchEngaged):
        broker.submit_order(broker.account_id, order)

    assert client.placed == []
    assert broker.ledger.get_order(order.order_id)['state'] == (
        ledger_states.REJECTED
    )


def test_a_venue_rejection_does_not_stop_the_session(tmp_path):
    """
    Tests that one refused order is recorded and the session goes on.
    """
    client = FakeClient(reject=True)
    broker = _broker(client, tmp_path)
    order = Order(broker.current_dt, 'EQ:005930', 10)
    broker.submit_order(broker.account_id, order)

    assert broker.ledger.get_order(order.order_id)['state'] == (
        ledger_states.REJECTED
    )
    assert broker.open_orders == {}


def test_orders_are_never_retried(tmp_path):
    """
    Tests that a failed submission is not resent.

    The venue's order endpoint is not idempotent, so a retry risks a
    duplicate position.
    """
    calls = []

    class CountingClient(FakeClient):
        def place_market_order(self, symbol, quantity):
            calls.append(symbol)
            raise RuntimeError('timeout')

    broker = _broker(CountingClient(), tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    assert len(calls) == 1


def test_update_absorbs_a_late_fill_of_a_stale_order(tmp_path):
    """
    Tests that abandoning an order at the deadline does not lose it.

    A fill that arrives after the budget expires is booked by the next
    update, which is what makes leaving orders stale safe.
    """
    plan = {'0001': [
        OrderReport('0001', 0, 0.0, 10, 0, 0.0, False),
        OrderReport('0001', 0, 0.0, 10, 0, 0.0, False),
        OrderReport('0001', 10, 10000.0, 0, 0, 0.0, True),
    ]}
    client = FakeClient(fill_plan=plan)
    broker = _broker(client, tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )

    broker.clock = _poll_driven_clock(client, expire_after=2)
    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))
    assert broker.get_portfolio_as_dict(broker.account_id) == {}

    # The order is stale, but still known to the venue.
    broker.open_orders['0001'] = {
        'order_id': 'late', 'symbol': 'EQ:005930', 'quantity': 10,
        'portfolio_id': broker.account_id, 'booked_quantity': 0
    }
    broker.clock = lambda: pd.Timestamp('2026-08-20 12:30:00')
    broker.update(pd.Timestamp('2026-08-20 12:30:00'))

    assert broker.get_portfolio_as_dict(
        broker.account_id
    )['EQ:005930']['quantity'] == 10


def test_seed_from_venue_rebuilds_holdings_and_cash(tmp_path):
    """
    Tests that a session starts from the venue's balance, since there
    is no persisted portfolio to reload.
    """
    balance = AccountBalance(
        cash=500000.0,
        settled_cash=900000.0,
        total_equity=1200000.0,
        holdings=(Holding('EQ:005930', 10, 70000.0),)
    )
    client = FakeClient(balance=balance)
    broker = _broker(client, tmp_path)
    broker.seed_from_venue()

    assert broker.get_portfolio_cash_balance(broker.account_id) == 500000.0
    assert broker.get_portfolio_as_dict(
        broker.account_id
    )['EQ:005930']['quantity'] == 10


def test_no_funding_api_is_offered(tmp_path):
    """
    Tests that a live broker exposes no way to move cash locally.

    The venue has no transfer API, so any such method could only
    refuse. They used to exist and raise, because the Broker ABC
    required them; since ADR-0016 it does not, and the honest answer
    to "can I fund this account through the engine" is that the method
    is not there. Pinned because deleting a method is easy to undo by
    accident when copying the simulated broker.
    """
    broker = _broker(FakeClient(), tmp_path)
    for name in (
        'subscribe_funds_to_account',
        'withdraw_funds_from_account',
        'subscribe_funds_to_portfolio',
        'withdraw_funds_from_portfolio',
    ):
        assert not hasattr(broker, name), (
            "LiveBroker should not offer '%s'; funding a live account "
            "happens at the venue, and the engine reads the balance."
            % name
        )


def test_total_equity_carries_the_master_key(tmp_path):
    """
    Tests the undocumented contract the trading session depends on.
    """
    broker = _broker(FakeClient(), tmp_path)
    equity = broker.get_account_total_equity()
    assert 'master' in equity
    assert equity['master'] == pytest.approx(1000000.0)


def test_marking_keeps_the_last_valuation_when_a_mark_is_missing(tmp_path):
    """
    Tests that an unpriceable symbol is not revalued to zero, since a
    missing quote is not evidence that a position became worthless.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))
    valued = broker.get_portfolio_total_market_value(broker.account_id)

    def no_price(symbol):
        raise RuntimeError('venue has no quote')

    client.get_price = no_price
    broker.update(pd.Timestamp('2026-08-20 11:30:00'))

    assert broker.get_portfolio_total_market_value(
        broker.account_id
    ) == valued


def test_equity_curve_is_persisted(tmp_path):
    """
    Tests that equity is written to the ledger.

    A live process dies between sessions, so unlike a backtest the
    curve cannot live in memory.
    """
    broker = _broker(FakeClient(), tmp_path)
    broker.record_equity()
    rows = broker.ledger.get_equity_curve()
    assert len(rows) == 1
    assert rows[0]['total_equity'] == pytest.approx(1000000.0)


def test_krw_is_the_account_currency(tmp_path):
    """
    Tests that the account reports Korean won.
    """
    broker = _broker(FakeClient(), tmp_path)
    assert broker.get_account_cash_balance('KRW') == 1000000.0
    assert broker.base_currency == 'KRW'
    assert isinstance(
        broker.exchange.open_time, datetime.time
    )


def test_update_is_throttled_during_a_submission_burst(tmp_path):
    """
    Tests that the per-order 'update' calls do not each poll the venue.

    The execution handler calls update after every single order. Live,
    that would spend the rate limit on answers nobody is waiting for
    and would book the first name's fill while the last name has not
    been sent yet. Collection belongs to settle, which runs after the
    burst.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path, cash=10000000.0)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )

    for _ in range(5):
        broker.update(broker.current_dt)

    assert client.reports_served == []
    assert broker.get_portfolio_as_dict(broker.account_id) == {}


def test_update_polls_once_the_throttle_window_has_passed(tmp_path):
    """
    Tests that a later call does poll, which is how late fills of
    stale orders are absorbed between cycles.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path, cash=10000000.0)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    broker.update(broker.current_dt)
    assert client.reports_served == []

    later = pd.Timestamp('2026-08-20 11:00:00')
    broker.clock = lambda: later
    broker.update(later)

    assert client.reports_served != []
    assert broker.get_portfolio_as_dict(
        broker.account_id
    )['EQ:005930']['quantity'] == 10


def test_update_can_be_forced(tmp_path):
    """
    Tests that a caller who genuinely wants a poll now can have one.
    """
    client = FakeClient()
    broker = _broker(client, tmp_path, cash=10000000.0)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    broker.update(broker.current_dt, force=True)
    assert client.reports_served != []


class _StubbornWorker:
    """
    A worker that reports it could not be stopped.

    A real one only does this when a poll is wedged inside the venue
    SDK, which a unit test cannot arrange: the drain barrier would
    block before the shutdown is ever reached.
    """

    def __init__(self, **kwargs):
        self.stop_timeout = 'never called'

    def start(self):
        pass

    def post_task(self, task):
        pass

    def join_tasks(self, timeout=None):
        return True

    def stop(self, timeout=None):
        self.stop_timeout = timeout
        return False


def test_settle_reports_a_worker_that_would_not_stop(
    tmp_path, monkeypatch, capsys
):
    """
    Tests that a settlement whose worker outlives the shutdown says so.

    The stall cannot be cured from inside the process, so the point is
    that it is named: a cycle that ends with a thread still polling
    must not read as a clean exit in the log.
    """
    stub = _StubbornWorker()
    monkeypatch.setattr(
        'vmtrader.broker.live_broker.TaskQueueWorker', lambda **kw: stub
    )
    settings.set_print_events(True)

    client = FakeClient()
    broker = _broker(client, tmp_path)
    booked = broker.settle(
        deadline=pd.Timestamp('2026-08-20 11:00:00'), shutdown_timeout=0.5
    )

    assert booked == 0
    assert stub.stop_timeout == 0.5
    assert 'did not stop within 0.5s' in capsys.readouterr().out


class _SlowDrainWorker:
    """
    A worker whose first drain check reports the round unfinished.

    Real slowness cannot be arranged here without spending the wall
    clock the heartbeat is derived from, so the timing is faked and the
    tasks run inline: what the test is about is what the broker does
    with the answer, not how long it waited for it.
    """

    def __init__(self, **kwargs):
        self.timeouts = []

    def start(self):
        pass

    def post_task(self, task):
        task['runnable'](task)

    def join_tasks(self, timeout=None):
        self.timeouts.append(timeout)
        return timeout is None

    def stop(self, timeout=None):
        return True


def test_a_slow_drain_is_reported_but_still_waited_out(
    tmp_path, monkeypatch, capsys
):
    """
    Tests that a round which outruns the heartbeat is named in the log
    and then waited for anyway.

    The barrier is what gives the portfolio a single writer, so it is
    never abandoned on a timeout -- the timeout only decides when to
    say something. The interval is a share of the remaining budget, so
    an hour of budget reports after fifteen minutes and a nearly spent
    one reports sooner.
    """
    stub = _SlowDrainWorker()
    monkeypatch.setattr(
        'vmtrader.broker.live_broker.TaskQueueWorker', lambda **kw: stub
    )
    settings.set_print_events(True)

    client = FakeClient(price=10000.0)
    broker = _broker(client, tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )
    booked = broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    assert booked == 1
    holding = broker.get_portfolio_as_dict(broker.account_id)['EQ:005930']
    assert holding['quantity'] == 10
    assert stub.timeouts == [900.0, None]
    assert 'has not drained in 900s' in capsys.readouterr().out


def test_each_settle_round_leaves_a_drain_sample(tmp_path, caplog):
    """
    Tests that every round records what it would take to size the
    timeouts from measurement.

    Both the heartbeat's share of the budget and the gateway's HTTP
    limits were chosen without observation. Neither can be replaced by
    a measured figure unless the rounds say how long they actually
    took, so the sample carries the order count alongside the elapsed
    time -- a round is slow because of how many orders it polls.
    """
    client = FakeClient(price=10000.0)
    broker = _broker(client, tmp_path)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', 10)
    )

    with caplog.at_level(logging.DEBUG, logger='vmtrader.broker.live_broker'):
        broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    samples = [
        record.getMessage() for record in caplog.records
        if record.getMessage().startswith('settle drain')
    ]
    assert len(samples) == 1
    assert 'orders=1' in samples[0]
    assert 'heartbeat=900.0' in samples[0]
    assert 'overran=False' in samples[0]
    assert re.search(r'elapsed=\d+\.\d{3}', samples[0])
