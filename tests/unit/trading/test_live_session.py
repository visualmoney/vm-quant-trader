import datetime

from types import SimpleNamespace

import pandas as pd
import pytest

from vmtrader import settings
from vmtrader.broker.actor import BrokerActor
from vmtrader.messaging import MailboxClosed, TargetWeights
from vmtrader.broker.live.client import AccountBalance, OrderReport
from vmtrader.broker.live.guards import SafetyGuard
from vmtrader.broker.live.ledger import OrderLedger
from vmtrader.broker.live_broker import LiveBroker
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

    Offers both halves of a rebalance, because the session reaches one
    through the strategy executor now. Recording on the second half
    rather than the first is deliberate: it is the half that would
    place orders, so 'calls' still means "a rebalance actually
    happened" and not merely "weights were considered".
    """

    def __init__(self):
        self.calls = []
        self.portfolio_construction_model = SimpleNamespace(alpha_model=None)

    def decide_weights(self, dt):
        return TargetWeights(dt=dt, weights=())

    def size_and_submit(self, command, stats=None):
        self.calls.append(command.dt)

    def __call__(self, dt, stats=None):
        self.size_and_submit(self.decide_weights(dt), stats=stats)


def _session(tmp_path, now, guard=None, holidays=None,
             rebalance_dates=None, synchronous=True):
    """
    Build a live session around a stub venue.
    """
    venue = StubVenue()
    broker = LiveBroker(
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
        broker, qts, rebalance_dates=rebalance_dates,
        clock=lambda: now, synchronous=synchronous
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
    broker = LiveBroker(
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
    broker = LiveBroker(
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
    broker = LiveBroker(
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


def test_the_executor_outbox_is_a_mailbox_not_the_write_path(tmp_path):
    """
    Tests the wiring that finding B1 of report 20260826-01 caught.

    The strategy actor's outbox used to be 'qts.size_and_submit', a
    bound method of the half decision 9 had just split off. Follow it
    and you reach get_portfolio_as_dict, then open_orders, then the
    ledger, then transact_asset -- the withdrawn decision 5, line for
    line, arriving through an injected callable instead of a name.

    An import boundary cannot see that, because nothing was imported.
    This asserts on the instance instead: what the executor holds must
    be a broker actor's mailbox door and nothing else.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, _, _ = _session(tmp_path, now)

    executor, broker_actor = session._actors()
    outbox = executor._post_command

    assert outbox.__func__ is BrokerActor.post_command
    assert outbox.__self__ is broker_actor


def test_the_executor_cannot_reach_accounting_through_its_outbox(tmp_path):
    """
    Tests that the outbox stays a door rather than becoming a corridor.

    A later refactor could keep the type and still hand back something
    that writes: what matters is that everything reachable through the
    object the executor holds is inert with respect to the portfolio,
    the ledger and the open orders.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, broker, _, _ = _session(tmp_path, now)

    executor, _ = session._actors()
    reachable = {
        name for name in dir(executor._post_command.__self__)
        if not name.startswith('_')
    }

    assert reachable == {
        'post_command', 'drain', 'mailbox', 'name', 'synchronous',
        'attempted', 'completed', 'refuse_commands'
    }
    for forbidden in ('portfolios', 'open_orders', 'ledger', 'submit_order'):
        assert not hasattr(executor._post_command.__self__, forbidden)


@pytest.mark.parametrize('synchronous', [True, False])
def test_a_rebalance_completes_in_either_mode(tmp_path, synchronous):
    """
    Tests the acceptance criterion for finding B3.

    A cycle has to reach the same place whichever mode it runs in.
    With a thread, 'post_event' only queues: before this fix 'settle'
    then opened on an empty order book, returned zero, and the process
    exited cutting the executor mid-decision -- while the outcome dict
    reported a trade. Silent, and on the plane that runs live.

    Parametrised rather than written twice on purpose. Two tests drift;
    one test run twice cannot.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, qts, _ = _session(tmp_path, now, synchronous=synchronous)

    outcome = session.run_rebalance()

    assert qts.calls == [now]
    assert outcome['traded'] is True
    assert outcome['reason'] is None


def test_a_strategy_that_decides_nothing_is_not_reported_as_a_trade(tmp_path):
    """
    Tests that the outcome reflects the act, not the intent.

    'traded' used to be set unconditionally, right after posting the
    event -- which in threaded mode proved only that something had
    been queued. It is derived from what the broker side actually
    carried out now, so a strategy that fails to decide says so
    instead of reporting a rebalance that never happened.

    Threaded because that is where the branch is reachable: the
    consumer loop absorbs a raising handler by design, so no command
    is ever posted. Synchronously the same failure propagates out of
    the session instead, and the two modes differing here is finding
    M4, still open.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, qts, _ = _session(tmp_path, now, synchronous=False)

    def explode(dt):
        raise ValueError('the alpha model could not be evaluated')

    session.qts.decide_weights = explode

    outcome = session.run_rebalance()

    assert qts.calls == []
    assert outcome['traded'] is False
    assert 'no decision' in outcome['reason']


def test_a_failing_cycle_does_not_leak_the_strategy_thread(tmp_path):
    """
    Tests the 'finally' around the cycle.

    Anything raised on the main thread between starting the executor
    and the barrier used to leave a started thread running on into
    settlement, still holding an outbox into a mailbox nobody would
    drain. The stop is unconditional now, and it is safe to call on
    every path -- which is the property S13 had to establish before S2
    could be written.

    The failure is injected at 'post_event' rather than inside the
    strategy on purpose: a strategy raising is handled by the consumer
    loop and never reaches this thread, so it would not exercise the
    window at all.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, _, _ = _session(tmp_path, now, synchronous=False)

    seen = []
    original = session._actors

    def actors():
        executor, broker_actor = original()
        seen.append(executor)

        def explode(event):
            raise RuntimeError('the clock produced a malformed event')

        executor.post_event = explode
        return executor, broker_actor

    session._actors = actors

    with pytest.raises(RuntimeError, match='malformed'):
        session._decide_and_submit(now)

    assert len(seen) == 1
    assert seen[0].is_alive() is False
    assert seen[0].mailbox.is_closed is True


def test_a_rebalance_that_failed_is_not_reported_as_a_trade(tmp_path):
    """
    Tests that 'traded' follows the act rather than the attempt.

    The command reaches the broker side and fails there. The drain
    absorbs it -- an ordinary failure does not end a drain, because
    everything behind that consumer stops when it does -- so the cycle
    carries on to settlement, and the outcome must still say the
    rebalance did not happen.

    Threaded, because that is where the absorption lives: posting
    synchronously dispatches on the caller's thread with no guard, so
    the same failure propagates out of the session instead. The two
    modes differing there is finding M4, still open.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, qts, _ = _session(tmp_path, now, synchronous=False)

    def explode(command, stats=None):
        raise ValueError('the sizer could not price the universe')

    session.qts.size_and_submit = explode

    outcome = session.run_rebalance()

    assert qts.calls == []
    assert outcome['traded'] is False
    assert 'no decision' in outcome['reason']


def test_a_late_decision_is_refused_rather_than_queued(tmp_path):
    """
    Tests the window between the barrier and the drain.

    A strategy that overran keeps running, and when it finishes it
    still holds a live outbox. Before the latch that outbox took the
    command, put it in a queue the cycle had already finished draining,
    and the process exited with it still there -- no exception, no
    counter, a rebalance that simply did not happen.

    Simulated by posting after the cycle rather than by racing a real
    overrun: the point is what the door does, not how long the
    strategy took to reach it.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    session, _, _, _ = _session(tmp_path, now)

    captured = []
    original = session._actors

    def actors():
        executor, broker_actor = original()
        captured.append(broker_actor)
        return executor, broker_actor

    session._actors = actors
    session._decide_and_submit(now)

    with pytest.raises(MailboxClosed, match='barrier'):
        captured[0].post_command(
            TargetWeights(dt=now, weights=(('EQ:005930', 1.0),))
        )
