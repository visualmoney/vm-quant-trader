"""
The broker actor: the mailbox in front of everything that owns money.

Phase 0 built the strategy actor and stopped. This is the half that
was missing, and it is the half that matters: the portfolio, the open
orders and the ledger all live behind it, and every write to them is
supposed to happen on the one thread that consumes this mailbox.

Without it there was nowhere for the strategy to send a decision, so
both assembly points handed the executor a bound method of the broker
half instead -- and the executor called it on its own thread. That is
the withdrawn decision 5 arriving through dependency injection rather
than through a name, which is why an import boundary could not see it.
Naming the object is the fix; the guard against re-binding it is the
test beside this class.

It is not a Thread, and the asymmetry with 'BaseStrategyExecutor' is
the design rather than an oversight. The consumer here is the main
thread (decision 12), which already owns this state and already runs
this actor's behaviour, driven by a call sequence rather than by a
queue. Giving it a thread of its own would make "has the cycle
finished" a question asked across an actor boundary, and prohibition 1
forbids waiting for the answer.

See docs/dev/threading-and-event-architecture.md, decisions 9 and 12,
appendix C, and report 20260826-01 finding B1.
"""

import logging
import traceback

from vmtrader.messaging import Mailbox, TargetWeights

logger = logging.getLogger(__name__)

# Decision 8: the broker's mailbox is capped and drops beyond the cap,
# because the thread that must not be cut must also not be held by a
# producer. The executor's mailbox is unbounded for the opposite
# reason.
BROKER_MAILBOX_MAXSIZE = 200


class BrokerActor:
    """
    Receives commands from the strategy and carries them out.

    Parameters
    ----------
    size_and_submit : `callable`
        Takes a 'TargetWeights' and turns it into orders at the venue.
        Holding this is what makes the object Actor 1 -- the thing
        finding B1 objects to is the *strategy* holding it, not this.
    synchronous : `Boolean`, optional
        Whether to carry a command out on the caller's thread instead
        of queueing it. Decided once, by whichever session assembles
        this, and never per call.
    on_error : `callable`, optional
        Called with the exception when a handler raises. The failure is
        logged either way.
    """

    def __init__(self, size_and_submit, synchronous=True, on_error=None):
        self.name = 'broker'
        self._size_and_submit = size_and_submit
        self._synchronous = synchronous
        self._on_error = on_error
        self._mailbox = Mailbox('broker', maxsize=BROKER_MAILBOX_MAXSIZE)

    # -- the face the strategy actor calls -------------------------------

    def post_command(self, command):
        """
        Hand the broker a decision. Fire-and-forget; never blocks.

        This is what the strategy actor's outbox must point at. It is
        deliberately the only public way in: a caller holding this
        cannot reach the portfolio, the ledger or the open orders
        through it, which is the property that lets the strategy run
        on a thread that owns none of them.

        Parameters
        ----------
        command : `object`
            A command this actor knows how to carry out.
        """
        if self._synchronous:
            self._dispatch(command)
        else:
            self._mailbox.post(command)

    # -- the consumer side, run by the main thread -----------------------

    def drain(self):
        """
        Carry out everything waiting, then return.

        The consumer half, and it returns rather than looping because
        under cron a cycle has an end. A resident session replaces this
        with a loop over the same dispatch; both shapes share the
        handler, which is the point.

        A handler that raises is reported and the drain continues. The
        single consumer is the single point of failure for everything
        behind it, so it does not end because one command failed.

        Returns
        -------
        `int`
            How many messages were carried out.
        """
        handled = 0
        while self._mailbox.depth() > 0:
            message = self._mailbox.take()
            if message is None:
                break
            handled += 1
            try:
                self._dispatch(message)
            except Exception as error:  # noqa: BLE001
                logger.error(
                    'BrokerActor[%s] handler Exception:\n%s',
                    self.name, traceback.format_exc()
                )
                if self._on_error is not None:
                    self._on_error(error)
        return handled

    # -- the one path both modes take ------------------------------------

    def _dispatch(self, message):
        """
        Carry out one command.

        The only place a command becomes an order, in either mode.

        Parameters
        ----------
        message : `object`
            The command to carry out.
        """
        if isinstance(message, TargetWeights):
            self._size_and_submit(message)
        else:
            # Lifecycle events addressed here -- PollDue, EndOfDay --
            # have no handler yet because nothing produces them. When
            # one does, it lands here rather than in a second dispatch
            # somewhere else.
            raise TypeError(
                "broker actor was sent a %s, which it has no handler "
                "for" % type(message).__name__
            )

    # -- instrumentation --------------------------------------------------

    @property
    def mailbox(self):
        """
        Return the mailbox, for its depth, counters and drop count.

        Returns
        -------
        `Mailbox`
            The queue this actor consumes.
        """
        return self._mailbox
