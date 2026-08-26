"""
Pin the contract of the strategy actor.

Most of what matters here is not what the executor computes -- it
computes nothing -- but what it refuses and what it survives. The
guards, the loop that will not die, and the two modes agreeing are
the whole of it.
"""

import ast
import pathlib
import threading

import pandas as pd
import pytest

import vmtrader.alpha_model.base_strategy_executor
from vmtrader.alpha_model.base_strategy import BaseStrategy
from vmtrader.alpha_model.base_strategy_executor import BaseStrategyExecutor
from vmtrader.broker.actor import BrokerActor
from vmtrader.broker.live.worker import TaskQueueWorker
from vmtrader.messaging import (
    EndOfDay,
    OrderFilled,
    RebalanceDue,
    TargetWeights,
)


class RecordingStrategy(BaseStrategy):
    """A strategy that only remembers what it was told."""

    def __init__(self):
        self.fills = []

    def __call__(self, dt):
        return {}

    def on_fill(self, event):
        self.fills.append(event)


class Sent(list):
    """
    The commands that reached the broker side.

    A real 'BrokerActor' sits between the executor and this list, so
    that these tests exercise the seam rather than a stand-in for it.
    In threaded mode the actor queues, which is why reading this list
    means draining first -- 'drained()' does both.
    """

    def __init__(self, broker):
        super().__init__()
        self._broker = broker

    def drained(self):
        """
        Drain the broker actor, then return self.
        """
        self._broker.drain()
        return self


def _executor(synchronous=True, strategy=None, decide=None, on_error=None):
    """
    Build an executor wired to a real broker actor.

    Returns
    -------
    `tuple[BaseStrategyExecutor, Sent]`
        The executor and the commands the broker side received.
    """
    holder = {}
    broker = BrokerActor(
        size_and_submit=lambda command: holder['sent'].append(command),
        synchronous=synchronous
    )
    holder['sent'] = sent = Sent(broker)
    executor = BaseStrategyExecutor(
        strategy=strategy if strategy is not None else RecordingStrategy(),
        decide=decide if decide is not None else (
            lambda dt: TargetWeights(dt=dt, weights=(('EQ:005930', 1.0),))
        ),
        broker=broker,
        synchronous=synchronous,
        on_error=on_error
    )
    return executor, sent


def _a_fill(order_no='0000117057'):
    """
    Build a representative fill event.
    """
    return OrderFilled(
        order_no=order_no,
        symbol='EQ:005930',
        quantity=3,
        cumulative_filled=3,
        average_price=71200.0,
        cumulative_fees=105.0,
        dt=pd.Timestamp('2026-08-24 10:00', tz='Asia/Seoul'),
    )


# -- the flags the design turns on ------------------------------------

def test_the_executor_thread_is_a_daemon():
    """
    Tests that a stuck strategy cannot keep the process alive.

    Strategy code is arbitrary -- an API call with no timeout is
    enough -- and the one thing that must not follow from it is a
    process that will not exit. Safe only because this thread books
    nothing: what a shutdown cuts is one callback, and the next
    launch's reconciliation settles anything it had in flight.

    Asserted directly because a flag flipped by accident changes
    nothing else that any other test can see.
    """
    executor, _ = _executor(synchronous=False)

    assert executor.daemon is True


def test_the_fill_worker_thread_is_not_a_daemon():
    """
    Tests the other half of the asymmetry, which is not symmetric.

    The fill worker's join is the accounting barrier: cutting it mid
    shutdown drops a fill that the venue has already executed. Its
    flag has never been asserted anywhere, so a change to it would
    have passed the whole suite.
    """
    worker = TaskQueueWorker()
    worker.start()
    try:
        assert worker.get_thread().daemon is False
    finally:
        worker.stop()


# -- the two guards ---------------------------------------------------

def test_a_synchronous_executor_refuses_to_start():
    """
    Tests the guard against a thread with nothing to consume.

    In synchronous mode events never reach the mailbox, so a started
    thread would block on it forever: alive, idle, and looking
    perfectly healthy in a stack dump.
    """
    executor, _ = _executor(synchronous=True)

    with pytest.raises(RuntimeError, match='synchronous'):
        executor.start()


def test_a_threaded_executor_refuses_events_before_it_starts():
    """
    Tests the guard against the silent loss.

    Queueing against a consumer that was never started loses the
    event without a trace -- no exception, no log, just a rebalance
    that did not happen. This is the combination that has to fail
    loudly, and it is why the mode is not inferred from the flag
    alone.
    """
    executor, _ = _executor(synchronous=False)

    with pytest.raises(RuntimeError, match='not consuming'):
        executor.post_event(RebalanceDue(dt=pd.Timestamp('2026-08-24')))


def test_a_stopped_executor_refuses_events_too():
    """
    Tests that the same guard covers the far end of the life cycle.

    Stopping does not put the executor back to before it started; it
    ends it. Posting afterwards is the same silent loss as posting
    too early.
    """
    executor, _ = _executor(synchronous=False)
    executor.start()
    executor.stop(timeout=2.0)

    with pytest.raises(RuntimeError, match='not consuming'):
        executor.post_event(RebalanceDue(dt=pd.Timestamp('2026-08-24')))


def test_a_stopped_executor_cannot_be_started_again():
    """
    Tests the rule that a restart is a new instance.

    'Thread' is single-use, and rather than paper over that, the
    design adopts it: an executor that has run is finished. Under
    cron this is free, since every launch builds one.
    """
    executor, _ = _executor(synchronous=False)
    executor.start()
    executor.stop(timeout=2.0)

    with pytest.raises(RuntimeError):
        executor.start()


# -- the loop contract, shared with TaskQueueWorker -------------------

def test_a_raising_handler_does_not_end_the_loop():
    """
    Tests the single consumer's one obligation.

    Everything downstream of this thread stops when it does, so a
    strategy raising must cost that event and nothing more. The same
    contract 'TaskQueueWorker.__loop' keeps, asserted separately
    because the loops are separately written.
    """
    seen = []
    errors = []

    def decide(dt):
        if not seen:
            seen.append(dt)
            raise ValueError('the strategy had a bad day')
        seen.append(dt)
        return TargetWeights(dt=dt, weights=())

    executor, sent = _executor(
        synchronous=False, decide=decide, on_error=errors.append
    )
    executor.start()
    executor.post_event(RebalanceDue(dt=pd.Timestamp('2026-08-24 09:10')))
    executor.post_event(RebalanceDue(dt=pd.Timestamp('2026-08-24 09:20')))
    assert executor.stop(timeout=2.0)

    assert len(seen) == 2
    assert len(sent.drained()) == 1
    assert [type(error) for error in errors] == [ValueError]


def test_events_are_handled_in_the_order_they_were_posted():
    """
    Tests the FIFO the single consumer exists to provide.

    Order is the reason for a queue rather than a lock: a strategy
    must not observe a later fill before an earlier one.
    """
    strategy = RecordingStrategy()
    executor, _ = _executor(synchronous=False, strategy=strategy)
    executor.start()
    for order_no in ('0001', '0002', '0003'):
        executor.post_event(_a_fill(order_no=order_no))
    assert executor.stop(timeout=2.0)

    assert [fill.order_no for fill in strategy.fills] == [
        '0001', '0002', '0003'
    ]


def test_stopping_drains_what_was_already_posted():
    """
    Tests that shutting down is not the same as dropping.

    The sentinel goes behind what is queued, so an executor told to
    stop finishes the events it was already given.
    """
    strategy = RecordingStrategy()
    executor, _ = _executor(synchronous=False, strategy=strategy)
    executor.start()
    for order_no in ('0001', '0002', '0003', '0004', '0005'):
        executor.post_event(_a_fill(order_no=order_no))
    assert executor.stop(timeout=2.0)

    assert len(strategy.fills) == 5


# -- the property the flag exists to preserve -------------------------

def test_both_modes_produce_the_same_result_from_the_same_events():
    """
    Tests the isomorphism the synchronous flag is for.

    A backtest and a live session differ in where handlers run, not
    in what they do. If the two modes could disagree, a backtest
    would stop being evidence about live behaviour -- which is the
    whole claim it makes.
    """
    events = [
        RebalanceDue(dt=pd.Timestamp('2026-08-24 09:10')),
        _a_fill(order_no='0001'),
        RebalanceDue(dt=pd.Timestamp('2026-08-24 09:20')),
        _a_fill(order_no='0002'),
    ]

    sync_strategy = RecordingStrategy()
    sync, sync_sent = _executor(synchronous=True, strategy=sync_strategy)
    for event in events:
        sync.post_event(event)

    threaded_strategy = RecordingStrategy()
    threaded, threaded_sent = _executor(
        synchronous=False, strategy=threaded_strategy
    )
    threaded.start()
    for event in events:
        threaded.post_event(event)
    assert threaded.stop(timeout=2.0)

    assert sync_sent.drained() == threaded_sent.drained()
    assert [fill.order_no for fill in sync_strategy.fills] == (
        [fill.order_no for fill in threaded_strategy.fills]
    )


def test_a_synchronous_executor_starts_no_thread():
    """
    Tests that the synchronous mode really costs nothing.

    Phase 0 claims zero extra threads. An executor that quietly
    started one would still pass every behavioural test here.
    """
    before = threading.active_count()
    executor, _ = _executor(synchronous=True)
    for _ in range(5):
        executor.post_event(RebalanceDue(dt=pd.Timestamp('2026-08-24')))

    assert threading.active_count() == before
    assert executor.is_alive() is False


# -- routing ----------------------------------------------------------

def test_an_event_addressed_to_the_broker_is_refused():
    """
    Tests that misrouting is a mistake, not a no-op.

    'EndOfDay' belongs to the broker, which owns the portfolio and
    the ledger it touches. Swallowing it here would leave an equity
    curve silently unwritten, so the wiring error surfaces instead.
    """
    executor, _ = _executor(synchronous=True)

    with pytest.raises(TypeError, match='EndOfDay'):
        executor.post_event(EndOfDay(dt=pd.Timestamp('2026-08-24 15:30')))


def test_a_rebalance_becomes_a_command_for_the_broker():
    """
    Tests the seam between the two actors.

    The executor decides and sends; it does not size and it does not
    submit. What crosses is one message carrying the timestamp it was
    decided for.
    """
    executor, sent = _executor(synchronous=True)
    now = pd.Timestamp('2026-08-24 09:10')

    executor.post_event(RebalanceDue(dt=now))

    assert len(sent.drained()) == 1
    assert isinstance(sent[0], TargetWeights)
    assert sent[0].dt == now


# -- the hazard of inheriting from Thread -----------------------------

def test_the_executor_module_cannot_reach_the_accounting():
    """
    Tests the boundary that makes the daemon flag safe.

    The executor's thread may be cut at shutdown, and that is only
    tolerable because it books nothing: no portfolio, no ledger, no
    open orders. A single import of the broker package would put a
    write within reach of a thread that can vanish mid-statement.

    Structural rather than behavioural on purpose. A test that calls
    the executor and finds the portfolio unchanged proves it about
    that call; this proves the module cannot name the accounting.

    It proves nothing about what is *handed* to the executor, and an
    earlier version of this docstring claimed otherwise -- "no way to
    reach it at all" -- while both assembly points were passing in a
    bound method that reached all of it (report 20260826-01, B1). An
    import boundary cannot see an injected callable. The wiring is
    asserted on the instance instead, in
    tests/unit/trading/test_live_session.py.
    """
    source = pathlib.Path(
        vmtrader.alpha_model.base_strategy_executor.__file__
    ).read_text()

    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = sorted(
        module for module in imported
        if module.startswith('vmtrader.broker')
        or module.startswith('vmtrader.execution')
    )

    assert forbidden == [], (
        'the executor can reach the accounting through %s' % forbidden
    )


def test_thread_does_not_shadow_any_of_the_executor_s_methods():
    """
    Tests that subclassing 'Thread' has not eaten a method.

    'Thread.__init__' writes its own names into the instance, and
    'self._handle' -- a real thread handle since Python 3.13 -- once
    shadowed the dispatch method this class is built around. The
    failure was a TypeError about a '_thread._ThreadHandle' not being
    callable, at the first event, in every mode.

    The reserved names are undocumented and grow between releases, so
    this compares the class's own callables against what the instance
    actually carries rather than keeping a list.
    """
    executor, _ = _executor(synchronous=True)

    defined = {
        name for name, value in vars(BaseStrategyExecutor).items()
        if callable(value)
    }
    shadowed = defined & set(vars(executor))

    assert shadowed == set(), (
        'threading.Thread shadowed %s' % sorted(shadowed)
    )


# -- the third fact in the mode ---------------------------------------

class WritesTheAccounting:
    """
    A stand-in for the shape finding B1 caught: an outbox that sizes
    and submits. It is what 'qts' looks like from the executor's side.
    """

    synchronous = False

    def post_command(self, command):
        pass

    def size_and_submit(self, command, stats=None):
        pass


def test_an_outbox_that_can_write_is_refused():
    """
    Tests the guard the mode was missing.

    Decision 4 gave the mode two facts and guarded both. The effective
    mode is three: the flag, start(), and where the outbox points --
    and the third is the one that can lose money. Handing in something
    that can size and submit puts the accounting on a thread that a
    shutdown may cut mid-statement.

    Checked by what the object exposes rather than by its type. The
    property that matters was never the nominal type; it is that what
    the strategy holds is inert. Checking by type would also mean
    importing the broker package here, which is what the module's
    import boundary exists to prevent.
    """
    with pytest.raises(TypeError, match='can write'):
        BaseStrategyExecutor(
            strategy=RecordingStrategy(),
            decide=lambda dt: TargetWeights(dt=dt, weights=()),
            broker=WritesTheAccounting(),
            synchronous=False
        )


def test_something_that_cannot_receive_a_command_is_refused():
    """
    Tests the other half of the same check.

    A free callable used to be accepted here, which is how a bound
    method of the write path got in. Anything that cannot take a
    command at all is a wiring mistake worth naming at construction.
    """
    with pytest.raises(TypeError, match='post_command'):
        BaseStrategyExecutor(
            strategy=RecordingStrategy(),
            decide=lambda dt: TargetWeights(dt=dt, weights=()),
            broker=[].append,
            synchronous=False
        )


def test_the_two_actors_must_agree_about_the_mode():
    """
    Tests the fourth cell of the mode table.

    A synchronous executor wired to a threaded broker queues a command
    that nothing will consume: the rebalance is lost without a sound,
    which is the anti-pattern the whole layer exists to forbid. The
    reverse runs a broker handler on the strategy's thread.
    """
    threaded_broker = BrokerActor(
        size_and_submit=lambda command: None, synchronous=False
    )

    with pytest.raises(RuntimeError, match='disagree about the mode'):
        BaseStrategyExecutor(
            strategy=RecordingStrategy(),
            decide=lambda dt: TargetWeights(dt=dt, weights=()),
            broker=threaded_broker,
            synchronous=True
        )


# -- the stop contract: total, idempotent, never self-joining ---------

def test_stopping_an_executor_that_never_started_is_safe():
    """
    Tests the property that makes a 'finally' writable.

    This used to raise out of Thread.join. In a 'finally' -- which is
    where a session must stop its actors -- that means the original
    exception is replaced by a complaint about thread lifecycle, so
    the real failure is never seen. Totality is not tidiness here; it
    is what lets the cycle be wrapped at all.
    """
    executor, _ = _executor(synchronous=False)

    assert executor.stop(timeout=0.1) is True
    assert executor.mailbox.is_closed is True


def test_stopping_twice_is_free_and_may_wait_again():
    """
    Tests idempotency, and the limit of it.

    Closing an already-closed mailbox is a no-op, so a repeat costs
    nothing after success. Deliberately not refused: waiting again
    with more patience after a short timeout is a legitimate thing to
    want, and the fill worker's own tests already document that
    pattern.
    """
    executor, _ = _executor(synchronous=False)
    executor.start()

    assert executor.stop(timeout=2.0) is True
    assert executor.stop(timeout=2.0) is True
    assert executor.stop() is True


def test_a_synchronous_stop_closes_the_mailbox_too():
    """
    Tests that 'stopped' means the same thing in both modes.

    A synchronous executor used to return True without closing
    anything, so there was no observable record that a cycle had
    ended -- and any later code wanting to ask would have invented its
    own predicate. 'mailbox.is_closed' is that predicate now.
    """
    executor, _ = _executor(synchronous=True)

    assert executor.stop() is True
    assert executor.mailbox.is_closed is True


def test_an_executor_refuses_to_stop_itself():
    """
    Tests that a strategy hook cannot deadlock the session.

    Stopping joins, and a thread joining itself raises out of
    threading with a message about the wrong thing. A strategy that
    tries to end its own session gets told what it actually did.
    """
    caught = []

    def decide(dt):
        try:
            executor.stop(timeout=1.0)
        except RuntimeError as error:
            caught.append(error)
        return TargetWeights(dt=dt, weights=())

    executor, _ = _executor(synchronous=False, decide=decide)
    executor.start()
    executor.post_event(RebalanceDue(dt=pd.Timestamp('2026-08-24 09:10')))
    assert executor.stop(timeout=2.0)

    assert len(caught) == 1
    assert 'cannot stop itself' in str(caught[0])
