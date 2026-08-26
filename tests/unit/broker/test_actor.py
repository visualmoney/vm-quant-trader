"""
Pin the broker actor's contract.

It exists so that the strategy has somewhere to send a decision that
is not the portfolio's write path. Most of what matters is therefore
about what it exposes rather than what it computes.
"""

import logging

import pandas as pd
import pytest

from vmtrader.broker.actor import BROKER_MAILBOX_MAXSIZE, BrokerActor
from vmtrader.broker.live.guards import KillSwitchEngaged
from vmtrader.errors import StopRequested
from vmtrader.messaging import EndOfDay, MailboxClosed, TargetWeights


def _command(dt='2026-08-24 09:10'):
    """
    Build a representative command.
    """
    return TargetWeights(
        dt=pd.Timestamp(dt), weights=(('EQ:005930', 1.0),)
    )


def _actor(synchronous=True, size_and_submit=None, on_error=None):
    """
    Build an actor whose work is recorded in a list.

    Returns
    -------
    `tuple[BrokerActor, list]`
        The actor and the commands it carried out.
    """
    done = []
    actor = BrokerActor(
        size_and_submit=size_and_submit or done.append,
        synchronous=synchronous,
        on_error=on_error
    )
    return actor, done


def test_a_synchronous_actor_carries_the_command_out_at_once():
    """
    Tests the Phase 0 mode.

    No thread, no queue: the command is carried out on the caller's
    thread, which is where a rebalance has always happened.
    """
    actor, done = _actor(synchronous=True)
    command = _command()

    actor.post_command(command)

    assert done == [command]
    assert actor.mailbox.depth() == 0


def test_a_threaded_actor_queues_rather_than_acting():
    """
    Tests that the mode moves the work, not the meaning.

    In threaded mode the posting thread must not run the handler --
    that is the whole separation. It queues, and the thread that owns
    the accounting drains it.
    """
    actor, done = _actor(synchronous=False)

    actor.post_command(_command())

    assert done == []
    assert actor.mailbox.depth() == 1


def test_draining_carries_out_what_was_queued_in_order():
    """
    Tests the consumer half.

    It returns rather than looping because a cron cycle has an end; a
    resident session loops over the same dispatch.
    """
    actor, done = _actor(synchronous=False)
    for minute in ('09:10', '09:20', '09:30'):
        actor.post_command(_command('2026-08-24 %s' % minute))

    handled = actor.drain()

    assert handled == 3
    assert [str(c.dt.time()) for c in done] == [
        '09:10:00', '09:20:00', '09:30:00'
    ]
    assert actor.mailbox.depth() == 0


def test_a_raising_handler_does_not_end_the_drain(caplog):
    """
    Tests that one bad command does not strand the rest.

    Everything behind this actor stops when its consumer does, so a
    command that fails must cost that command and nothing more.
    """
    seen = []
    errors = []

    def size_and_submit(command):
        seen.append(command)
        if len(seen) == 1:
            raise ValueError('the venue said no')

    actor, _ = _actor(
        synchronous=False, size_and_submit=size_and_submit,
        on_error=errors.append
    )
    actor.post_command(_command('2026-08-24 09:10'))
    actor.post_command(_command('2026-08-24 09:20'))

    with caplog.at_level(logging.ERROR):
        assert actor.drain() == 2

    assert len(seen) == 2
    assert [type(error) for error in errors] == [ValueError]


def test_a_message_with_no_handler_is_refused():
    """
    Tests that misrouting is a mistake rather than a no-op.

    'EndOfDay' is addressed to this actor by decision 11 but has no
    handler yet, because nothing produces it. Swallowing it would
    leave an equity curve silently unwritten.
    """
    actor, _ = _actor(synchronous=True)

    with pytest.raises(TypeError, match='EndOfDay'):
        actor.post_command(EndOfDay(dt=pd.Timestamp('2026-08-24 15:30')))


def test_the_mailbox_is_capped():
    """
    Tests decision 8's asymmetry from this side.

    The thread that owns the accounting must not be cut, and a thread
    that must not be cut must not be held by a producer either -- so
    this mailbox drops where the executor's grows.
    """
    actor, _ = _actor(synchronous=False)

    assert actor.mailbox.maxsize == BROKER_MAILBOX_MAXSIZE
    for _ in range(BROKER_MAILBOX_MAXSIZE + 10):
        actor.post_command(_command())

    assert actor.mailbox.depth() == BROKER_MAILBOX_MAXSIZE
    assert actor.mailbox.dropped == 10


def test_post_command_is_the_only_way_in():
    """
    Tests the property finding B1 turns on.

    What the strategy holds must not reach the portfolio, the ledger
    or the open orders. It holds a bound method of this class, so the
    surface of this class is the surface the strategy has -- and
    nothing public here writes anything.
    """
    public = {
        name for name in vars(BrokerActor)
        if not name.startswith('_')
    }

    assert public == {
        'post_command', 'drain', 'mailbox', 'synchronous',
        'attempted', 'completed', 'refuse_commands'
    }


def test_a_stop_ends_the_drain_and_reaches_the_caller():
    """
    Tests the loop that matters most for a stop.

    This drain runs on the main thread, so re-raising here actually
    delivers: the operator's signal reaches the session, which is the
    only place that can decide the cycle is over. The executor's loop
    cannot do the same -- it would only kill its own thread -- which is
    why the two actors handle a stop differently despite sharing the
    rule that neither absorbs one.
    """
    actor, done = _actor(synchronous=False)
    actor._size_and_submit = lambda command: (_ for _ in ()).throw(
        KillSwitchEngaged('the operator threw the switch')
    )
    actor.post_command(_command())

    with pytest.raises(StopRequested):
        actor.drain()


def test_an_ordinary_failure_still_does_not_end_the_drain():
    """
    Tests that only stops escape.

    A command failing for any other reason costs that command and the
    drain carries on, because everything behind this actor stops when
    its consumer does.
    """
    errors = []
    actor, _ = _actor(
        synchronous=False,
        size_and_submit=lambda command: (_ for _ in ()).throw(
            ValueError('the venue said no')
        ),
        on_error=errors.append
    )
    actor.post_command(_command())
    actor.post_command(_command())

    assert actor.drain() == 2
    assert [type(error) for error in errors] == [ValueError, ValueError]


def test_a_command_that_raised_counts_as_attempted_and_not_completed():
    """
    Tests the distinction the outcome dict turns on.

    One counter read both ways made a cycle the operator stopped look
    like an ordinary day: the command was taken up, so the count was
    non-zero, so the session reported a trade. Taken up and finished
    are different facts and the gap between them is exactly where a
    stop lands.
    """
    actor, _ = _actor(
        synchronous=False,
        size_and_submit=lambda command: (_ for _ in ()).throw(
            ValueError('the venue said no')
        ),
        on_error=lambda error: None
    )
    actor.post_command(_command())
    actor.drain()

    assert actor.attempted == 1
    assert actor.completed == 0


def test_a_command_that_returned_counts_as_both():
    """
    Tests the ordinary case, so the pair cannot drift apart silently.
    """
    actor, done = _actor(synchronous=True)

    actor.post_command(_command())

    assert (actor.attempted, actor.completed) == (1, 1)
    assert len(done) == 1


def test_the_command_latch_refuses_late_decisions():
    """
    Tests the door that closes at the cycle's barrier.

    A strategy that overran its budget keeps running -- it is a daemon
    and the budget bounds the wait, not the work. When it finishes it
    still holds an outbox, and before the latch that outbox accepted a
    whole rebalance into a queue nobody would drain again. Lost at
    exit, silently, which is what this layer exists to prevent.
    """
    actor, done = _actor(synchronous=False)
    actor.post_command(_command())

    actor.refuse_commands()

    with pytest.raises(MailboxClosed, match='barrier'):
        actor.post_command(_command())
    assert actor.mailbox.depth() == 1   # what arrived in time is intact


def test_the_latch_leaves_the_mailbox_open():
    """
    Tests the asymmetry that makes this a latch and not a close.

    The fill worker posts into this same mailbox and is born after the
    strategy actor is already dead, so closing at the barrier would
    refuse the notifications settlement depends on. One mailbox, two
    lanes, two lifetimes.
    """
    actor, _ = _actor(synchronous=False)

    actor.refuse_commands()

    assert actor.mailbox.is_closed is False
    assert actor.drain() == 0   # still usable as a consumer


def test_the_latch_is_one_way_and_idempotent():
    """
    Tests that the door does not reopen.

    A cycle ends once. Reopening would mean a rebalance decided after
    the session stopped waiting could still be carried out, against an
    account that settlement has been moving underneath it.
    """
    actor, _ = _actor(synchronous=False)

    actor.refuse_commands()
    actor.refuse_commands()

    with pytest.raises(MailboxClosed):
        actor.post_command(_command())
