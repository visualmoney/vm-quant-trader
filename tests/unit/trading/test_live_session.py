import datetime

import pandas as pd
import pytest

from vmtrader import settings
from vmtrader.broker.kis.client import AccountBalance, OrderReport
from vmtrader.broker.kis.guards import SafetyGuard
from vmtrader.broker.kis.ledger import OrderLedger
from vmtrader.broker.kis_broker import KisBroker
from vmtrader.data.live_data_handler import LiveDataHandler
from vmtrader.exchange.krx_exchange import KrxExchange
from vmtrader.trading.live import LiveTradingSession


@pytest.fixture(autouse=True)
def _quiet_events():
    """
    Silence event printing for these tests only.
    """
    previous = settings.PRINT_EVENTS
    settings.set_print_events(False)
    yield
    settings.set_print_events(previous)


class StubVenue:
    """
    A venue that fills whatever it is given, in full, on first poll.
    """

    def __init__(self, cash=10000000.0):
        self.cash = cash
        self.placed = []
        self._next = 0

    def place_market_order(self, symbol, quantity):
        self._next += 1
        order_no = '%04d' % self._next
        self.placed.append((symbol, quantity, order_no))
        return order_no

    def get_order_report(self, order_no):
        _, quantity, _ = next(
            p for p in self.placed if p[2] == order_no
        )
        return OrderReport(
            order_no, abs(quantity), 10000.0, 0, 0, 0.0, True
        )

    def get_balance(self):
        return AccountBalance(self.cash, self.cash, self.cash, ())

    def get_price(self, symbol):
        return 10000.0

    def get_trading_day(self, date_str):
        return True


class RecordingSystem:
    """
    Stands in for QuantTradingSystem, recording when it was called.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, dt, stats=None):
        self.calls.append(dt)


def _session(tmp_path, now, guard=None, holidays=None, rebalance_dates=None):
    """
    Build a live session around a stub venue.
    """
    venue = StubVenue()
    broker = KisBroker(
        start_dt=now,
        exchange=KrxExchange(holidays=holidays),
        data_handler=LiveDataHandler(venue),
        client=venue,
        ledger=OrderLedger(str(tmp_path / 'live.db')),
        guard=guard,
        clock=lambda: now
    )
    qts = RecordingSystem()
    session = LiveTradingSession(
        broker, qts, rebalance_dates=rebalance_dates, clock=lambda: now
    )
    return session, broker, qts, venue


def test_a_rebalance_runs_and_settles(tmp_path):
    """
    Tests the ordinary path: reconcile, trade, settle, exit.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, broker, qts, _ = _session(tmp_path, now)

    outcome = session.run_rebalance()

    assert outcome['traded'] is True
    assert qts.calls == [now]
    assert outcome['reason'] is None


def test_nothing_trades_on_a_holiday(tmp_path):
    """
    Tests that cron firing on a closed day costs one launch and no
    orders, since the process decides, not the schedule.
    """
    now = pd.Timestamp('2026-08-17 10:00:00')
    session, broker, qts, _ = _session(
        tmp_path, now, holidays={datetime.date(2026, 8, 17)}
    )

    outcome = session.run_rebalance()

    assert outcome['traded'] is False
    assert outcome['reason'] == 'not a rebalance day'
    assert qts.calls == []


def test_nothing_trades_off_schedule(tmp_path):
    """
    Tests that a weekly or monthly strategy exits quietly on the days
    in between.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, qts, _ = _session(
        tmp_path, now, rebalance_dates=[pd.Timestamp('2026-08-21')]
    )

    outcome = session.run_rebalance()

    assert outcome['traded'] is False
    assert qts.calls == []


def test_nothing_trades_outside_market_hours(tmp_path):
    """
    Tests that a launch after the close exits without trading.
    """
    now = pd.Timestamp('2026-08-20 16:00:00')
    session, _, qts, _ = _session(tmp_path, now)

    outcome = session.run_rebalance()

    assert outcome['reason'] == 'market closed'
    assert qts.calls == []


def test_the_kill_switch_stops_the_session_before_it_sizes(tmp_path):
    """
    Tests that a halted session never even asks the strategy what it
    wants, so no venue call is made.
    """
    switch = tmp_path / 'HALT'
    switch.write_text('')
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, qts, venue = _session(
        tmp_path, now, guard=SafetyGuard(kill_switch_path=str(switch))
    )

    outcome = session.run_rebalance()

    assert outcome['traded'] is False
    assert 'Kill switch' in outcome['reason']
    assert qts.calls == []
    assert venue.placed == []


def test_the_deadline_is_the_earlier_of_budget_and_close(tmp_path):
    """
    Tests that the time budget cannot run past the market close.

    A rebalance still collecting fills at 15:30 is collecting nothing,
    so the close wins whenever it comes first.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, _, _ = _session(tmp_path, now)
    # An hour's budget from 10:00 is the earlier limit.
    assert session._deadline(now) == pd.Timestamp('2026-08-20 11:00:00')

    late = pd.Timestamp('2026-08-20 15:00:00')
    session.clock = lambda: late
    # The close at 15:30, less the buffer, now binds instead.
    assert session._deadline(late) == pd.Timestamp('2026-08-20 15:20:00')


def test_end_of_day_records_equity_without_trading(tmp_path):
    """
    Tests the second launch: value the account and write the curve.

    It is separate from the rebalance so the trading process need not
    stay alive until the close, and so the curve is still written on a
    day the rebalance failed.
    """
    now = pd.Timestamp('2026-08-20 15:40:00')
    session, broker, qts, venue = _session(tmp_path, now)

    outcome = session.run_end_of_day()

    assert qts.calls == []
    assert venue.placed == []
    assert outcome['total_equity'] > 0.0
    assert len(broker.ledger.get_equity_curve()) == 1


def test_end_of_day_reports_a_mismatch_without_halting(tmp_path):
    """
    Tests that the valuation launch does not halt trading on a
    disagreement, since it places no orders and the next rebalance
    will reconcile properly anyway.
    """
    now = pd.Timestamp('2026-08-20 15:40:00')
    session, broker, _, _ = _session(tmp_path, now)
    broker.ledger.record_intent('orphan', 'EQ:005930', 10, now)

    session.run_end_of_day()

    assert broker.trading_halted is False


def test_reconciliation_halt_stops_the_rebalance(tmp_path):
    """
    Tests that a session which cannot trust its own picture does not
    trade on it.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, broker, qts, venue = _session(tmp_path, now)
    broker.ledger.record_intent('orphan', 'EQ:005930', 10, now)

    outcome = session.run_rebalance()

    assert outcome['traded'] is False
    assert 'reconciliation' in outcome['reason']
    assert qts.calls == []
    assert venue.placed == []


class HistoryVenue(StubVenue):
    """
    A venue that also serves daily closes.
    """

    def __init__(self, closes=None, **kwargs):
        super().__init__(**kwargs)
        self.closes = closes
        self.chart_calls = []

    def get_daily_closes(self, symbol, start_date, end_date, adjusted=True):
        self.chart_calls.append((symbol, start_date, end_date, adjusted))
        if self.closes is None:
            return []
        return self.closes


def _signals(assets, lookback=5):
    """
    Build a signals collection over the given assets.
    """
    from vmtrader.asset.universe.static import StaticUniverse
    from vmtrader.signals.signals_collection import SignalsCollection
    from vmtrader.signals.sma import SMASignal

    universe = StaticUniverse(list(assets))
    sma = SMASignal(pd.Timestamp('2026-08-20'), universe, [lookback])
    return SignalsCollection({'sma': sma}, None)


def test_signals_are_warmed_on_every_launch(tmp_path):
    """
    Tests that a cron one-shot primes its buffers before sizing.

    Every launch starts with empty buffers, so without this a moving
    average would be computed from one day's price, every day.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    closes = [
        ('2026081%d' % day, 70000.0 + day * 100) for day in range(1, 10)
    ]
    venue = HistoryVenue(closes=closes)
    broker = KisBroker(
        start_dt=now,
        exchange=KrxExchange(),
        data_handler=LiveDataHandler(venue),
        client=venue,
        ledger=OrderLedger(str(tmp_path / 'live.db')),
        clock=lambda: now
    )
    signals = _signals(['EQ:005930'])
    session = LiveTradingSession(
        broker, RecordingSystem(), signals=signals, clock=lambda: now
    )

    outcome = session.run_rebalance()

    assert outcome['traded'] is True
    assert outcome['signals_warmed'] == {'EQ:005930': 5}
    assert venue.chart_calls != []
    assert signals['sma']('EQ:005930', 5) > 0.0


def test_a_starved_signal_stops_the_rebalance(tmp_path):
    """
    Tests that trading is refused when history is missing.

    A signal with no history still returns a number, and sizing on it
    is worse than skipping a day.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    venue = HistoryVenue(closes=[])
    broker = KisBroker(
        start_dt=now,
        exchange=KrxExchange(),
        data_handler=LiveDataHandler(venue),
        client=venue,
        ledger=OrderLedger(str(tmp_path / 'live.db')),
        clock=lambda: now
    )
    qts = RecordingSystem()
    session = LiveTradingSession(
        broker, qts, signals=_signals(['EQ:005930']), clock=lambda: now
    )

    outcome = session.run_rebalance()

    assert outcome['traded'] is False
    assert 'no signal history' in outcome['reason']
    assert qts.calls == []
    assert venue.placed == []


def test_a_session_without_signals_does_not_ask_for_history(tmp_path):
    """
    Tests that a fixed-weight strategy costs no extra venue calls.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    venue = HistoryVenue()
    broker = KisBroker(
        start_dt=now,
        exchange=KrxExchange(),
        data_handler=LiveDataHandler(venue),
        client=venue,
        ledger=OrderLedger(str(tmp_path / 'live.db')),
        clock=lambda: now
    )
    session = LiveTradingSession(
        broker, RecordingSystem(), clock=lambda: now
    )

    outcome = session.run_rebalance()

    assert outcome['traded'] is True
    assert venue.chart_calls == []
