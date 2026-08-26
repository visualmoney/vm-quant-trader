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
from vmtrader.messaging import EndOfDay, TargetWeights


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

    assert public == {'post_command', 'drain', 'mailbox'}
