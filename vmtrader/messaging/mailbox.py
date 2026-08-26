"""
A single-consumer FIFO mailbox, shared by both actors.

The broker's event queue and the strategy executor's queue are the
same shape: many-producer, one-consumer, unbounded, drained before
shutdown. One class serves both so the semantics cannot drift apart.

A mailbox is unbounded by default and may be given a cap. The two
actors answer the backpressure question differently because their
traffic differs, and the class carries both rather than letting the
semantics drift into two implementations.

The strategy executor's mailbox stays unbounded: its producer is
bounded by the number of open orders, so a cap would be a policy with
no failure mode behind it, and what makes that acceptable is that
depth and a high-water mark are measured. A queue that silently grows
is as much an incident waiting to happen as one that silently drops.

The broker's mailbox is capped, and a post beyond the cap is dropped
rather than blocked. Blocking would stall whichever thread produced
it -- a venue's websocket among them, which drops the connection
rather than wait -- and the alternative to a bounded loss there is an
unbounded one. The loss is never silent: it is counted in 'dropped'
and it is logged, first at error and then periodically, so that a
flood names itself without filling the disk.

What makes a drop survivable here is a property of the venue rather
than of this class. Order reports are cumulative, so a lost fill
notification is recovered by the next poll: 'increment = filled -
booked' reaches the same answer whether or not the intervening
notification arrived. That is not true of everything -- a dropped
command is a rebalance that no one re-sends -- which is why the cap
belongs to a policy decision recorded in the design document and not
to a default.

'None' is the close sentinel, the same convention as
TaskQueueWorker: it goes to the back of the queue, so everything
posted before close is consumed first, and a consumer that takes
'None' knows the mailbox is finished. Posting after close fails
loudly -- an event with no consumer coming is a silent loss, and
losses do not get to be silent.
"""

import logging
import queue
import threading

logger = logging.getLogger(__name__)


class MailboxClosed(Exception):
    """
    Raised when an event is posted to a mailbox that was closed.

    The producer outlived the consumer's shutdown. Whatever posted
    this event believed it would be handled; raising here is what
    turns a silent loss into a stack trace at the point of the
    mistake.
    """


class Mailbox:
    """
    An instrumented FIFO for exactly one consumer.

    Parameters
    ----------
    name : `str`, optional
        Shows up in log lines and exception messages.
    maxsize : `int`, optional
        How many events may wait before further posts are dropped.
        Zero, the default, means no limit. A capped mailbox never
        blocks a producer: it drops, counts and says so.
    """

    def __init__(self, name='mailbox', maxsize=0):
        self.name = name
        self.maxsize = maxsize
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._posted = 0
        self._high_water = 0
        self._dropped = 0

    def post(self, event) -> None:
        """
        Queue an event. Fire-and-forget; never blocks.

        A post to a full mailbox is dropped, not refused and not
        waited on. The caller is not told, because there is nothing a
        caller could do about it that would not be worse -- retrying
        deepens the flood, blocking stalls a feed. The record of the
        loss is in the log and in 'dropped'.

        Parameters
        ----------
        event : `object`
            Any event. 'None' is refused -- it is the close sentinel.

        Raises
        ------
        `ValueError`
            If the event is 'None'.
        `MailboxClosed`
            If the mailbox was closed. A closed mailbox is a different
            condition from a full one: full means later events may
            still be handled, closed means none will.
        """
        if event is None:
            raise ValueError(
                'event 는 None 이 될 수 없습니다. - None 은 종료 센티넬'
            )
        with self._lock:
            if self._closed:
                raise MailboxClosed(
                    f"mailbox '{self.name}' is closed; the event has "
                    f"no consumer coming"
                )
            if self.maxsize and self._queue.qsize() >= self.maxsize:
                self._drop(event)
                return
            self._queue.put(event)
            self._posted += 1
            depth = self._queue.qsize()
            if depth > self._high_water:
                self._high_water = depth

    def _drop(self, event) -> None:
        """
        Count a dropped event and report it without flooding the log.

        The first loss is an incident and is logged as one. After that
        a flood would write a line per event, so the rate is stepped
        down to every hundredth -- enough to show it is still going,
        and the running total is on every line so nothing has to be
        counted by hand. 'dropped' stays exact regardless.

        Called with the lock held.

        Parameters
        ----------
        event : `object`
            The event being dropped, named in the log by type.
        """
        self._dropped += 1
        if self._dropped == 1:
            logger.error(
                "Mailbox[%s] is full at %d; dropping a %s. Events will "
                "be lost until the consumer catches up.",
                self.name, self.maxsize, type(event).__name__
            )
        elif self._dropped % 100 == 0:
            logger.warning(
                'Mailbox[%s] has now dropped %d events.',
                self.name, self._dropped
            )

    def take(self, timeout=None):
        """
        Remove and return the next event, blocking until one arrives.

        Consumer side only -- one thread calls this.

        Parameters
        ----------
        timeout : `float`, optional
            Seconds to wait. Without one, waits indefinitely.

        Returns
        -------
        `object` or `None`
            The next event, or 'None' once the mailbox is closed and
            everything posted before the close has been taken.

        Raises
        ------
        `queue.Empty`
            If a timeout was given and it expired.
        """
        return self._queue.get(timeout=timeout)

    def close(self) -> None:
        """
        Refuse further posts and hand the consumer the sentinel.

        The sentinel goes to the back of the queue, so events already
        posted are consumed before the consumer sees 'None'. Closing
        twice is a no-op.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(None)

    def depth(self) -> int:
        """
        Return how many items are waiting, sentinel included.

        Returns
        -------
        `int`
            The current queue depth. Approximate under concurrency,
            which is all a gauge needs to be.
        """
        return self._queue.qsize()

    @property
    def posted(self) -> int:
        """
        Return how many events were ever posted.

        Returns
        -------
        `int`
            The lifetime count, sentinel excluded.
        """
        return self._posted

    @property
    def dropped(self) -> int:
        """
        Return how many events were lost to a full mailbox.

        The number that turns "the strategy seems to have missed
        something" into a fact. Always zero on an uncapped mailbox.

        Returns
        -------
        `int`
            The lifetime count of dropped events.
        """
        return self._dropped

    @property
    def high_water(self) -> int:
        """
        Return the deepest the queue has ever been.

        Returns
        -------
        `int`
            The high-water mark. The number that decides, one day,
            whether unbounded was ever actually tested.
        """
        return self._high_water

    @property
    def is_closed(self) -> bool:
        """
        Return whether the mailbox was closed.

        Returns
        -------
        `Boolean`
            Whether 'close()' has run.
        """
        return self._closed
