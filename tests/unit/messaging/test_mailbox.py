import queue
import threading

import pytest

from vmtrader.messaging import Mailbox, MailboxClosed


def test_events_come_out_in_the_order_they_went_in():
    """
    Tests FIFO ordering.

    With one consumer there is no interleaving to test, so ordering is
    the whole contract: a fill is never handled after the cancel that
    followed it.
    """
    box = Mailbox()
    for i in range(50):
        box.post(i)
    assert [box.take() for _ in range(50)] == list(range(50))


def test_close_delivers_the_sentinel_after_the_backlog():
    """
    Tests drain-before-shutdown.

    The sentinel goes to the back of the queue, so an event posted
    before close is never dropped on shutdown -- the same guarantee
    TaskQueueWorker.stop() gives its tasks.
    """
    box = Mailbox()
    box.post('a')
    box.post('b')
    box.close()
    assert box.take() == 'a'
    assert box.take() == 'b'
    assert box.take() is None


def test_posting_after_close_raises_instead_of_losing_the_event():
    """
    Tests that a post with no consumer coming fails loudly.

    An event accepted after close would sit in the queue forever --
    a silent loss. The mistake surfaces where it was made.
    """
    box = Mailbox(name='strategy')
    box.close()
    with pytest.raises(MailboxClosed):
        box.post('late fill')


def test_none_is_refused_because_it_is_the_sentinel():
    """
    Tests that the sentinel value cannot be posted as an event.

    A 'None' event would end the consumer loop early and strand
    everything queued behind it.
    """
    box = Mailbox()
    with pytest.raises(ValueError):
        box.post(None)


def test_closing_twice_is_a_noop():
    """
    Tests close idempotency.

    A second close must not queue a second sentinel: the consumer
    stops at the first one, and a stray 'None' behind it would leak
    into whoever drains the queue next.
    """
    box = Mailbox()
    box.close()
    box.close()
    assert box.take() is None
    with pytest.raises(queue.Empty):
        box.take(timeout=0.01)


def test_depth_and_high_water_measure_the_backlog():
    """
    Tests the instrumentation that makes an unbounded queue acceptable.

    The unbounded choice rests on the producer being bounded today;
    the high-water mark is the evidence that gets to say so tomorrow.
    """
    box = Mailbox()
    for i in range(3):
        box.post(i)
    assert box.depth() == 3
    assert box.high_water == 3
    assert box.posted == 3
    box.take()
    box.take()
    assert box.depth() == 1
    assert box.high_water == 3
    assert box.posted == 3


def test_take_blocks_until_a_producer_posts():
    """
    Tests the handoff across the thread boundary.

    The consumer parks on 'take()' and wakes when a producer posts --
    the mechanism both actors rely on for their idle time.
    """
    box = Mailbox()
    got = []

    def consume():
        got.append(box.take())

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    box.post('fill')
    consumer.join(timeout=2)
    assert not consumer.is_alive()
    assert got == ['fill']
