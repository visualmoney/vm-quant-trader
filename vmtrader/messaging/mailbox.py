"""
A single-consumer FIFO mailbox, shared by both actors.

The broker's event queue and the strategy executor's queue are the
same shape: many-producer, one-consumer, unbounded, drained before
shutdown. One class serves both so the semantics cannot drift apart.

The queue is unbounded on purpose. Today's producer is a single
thread whose output is bounded by the number of open orders, so a cap
would only add a policy question with no failure mode behind it. What
makes unbounded acceptable is that it is measured: depth and a
high-water mark are kept, so the day a push-based feed arrives and
this judgement expires, the graph that proves it is already being
drawn. A queue that silently grows is as much an incident waiting to
happen as one that silently drops.

'None' is the close sentinel, the same convention as
TaskQueueWorker: it goes to the back of the queue, so everything
posted before close is consumed first, and a consumer that takes
'None' knows the mailbox is finished. Posting after close fails
loudly -- an event with no consumer coming is a silent loss, and
losses do not get to be silent.
"""

import queue
import threading


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
    An unbounded, instrumented FIFO for exactly one consumer.

    Parameters
    ----------
    name : `str`, optional
        Shows up in log lines and exception messages.
    """

    def __init__(self, name='mailbox'):
        self.name = name
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._posted = 0
        self._high_water = 0

    def post(self, event) -> None:
        """
        Queue an event. Fire-and-forget; never blocks.

        Parameters
        ----------
        event : `object`
            Any event. 'None' is refused -- it is the close sentinel.

        Raises
        ------
        `ValueError`
            If the event is 'None'.
        `MailboxClosed`
            If the mailbox was closed.
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
            self._queue.put(event)
            self._posted += 1
            depth = self._queue.qsize()
            if depth > self._high_water:
                self._high_water = depth

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
