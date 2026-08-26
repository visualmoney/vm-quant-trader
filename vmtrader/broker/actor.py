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

from vmtrader.errors import StopRequested
from vmtrader.messaging import Mailbox, MailboxClosed, TargetWeights

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
        self._attempted = 0
        self._completed = 0
        self._commands_refused = False

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

        Raises
        ------
        `MailboxClosed`
            Once the cycle's command latch has been tripped. A command
            arriving after the barrier has nobody left to carry it
            out, and a loss with no consumer coming is the one thing
            this layer refuses to let happen quietly.
        """
        if self._commands_refused:
            raise MailboxClosed(
                "broker actor is no longer accepting commands: the "
                "cycle's barrier has passed. Whatever produced this "
                "was still deciding after the session stopped waiting."
            )
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
            except StopRequested:
                # Not absorbed: this is the operator saying stop, and a
                # stop the loop is obliged to eat is not a stop
                # (report 20260826-02, S3). It ends the drain and
                # reaches the session.
                raise
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
            # Counted on both sides of the call on purpose: attempted
            # says a command was taken up, completed says it came back.
            # A stop raised inside the venue call lands between them,
            # which is exactly the distinction between "the cycle ran"
            # and "the cycle was stopped".
            self._attempted += 1
            self._size_and_submit(message)
            self._completed += 1
        else:
            # Lifecycle events addressed here -- PollDue, EndOfDay --
            # have no handler yet because nothing produces them. When
            # one does, it lands here rather than in a second dispatch
            # somewhere else.
            raise TypeError(
                "broker actor was sent a %s, which it has no handler "
                "for" % type(message).__name__
            )

    def refuse_commands(self):
        """
        Stop accepting commands. One-way, and not the same as closing.

        Tripped at the cycle's barrier, immediately after the strategy
        actor has been stopped and before the drain. What it closes is
        the *command* lane: a strategy that overran its budget and
        finishes afterwards finds a door that is shut and says so,
        rather than queueing a rebalance nobody will ever carry out
        (report 20260826-02, S1).

        The mailbox itself stays open, and that asymmetry is the whole
        reason this is a latch rather than 'close()'. The fill worker
        is a producer into this same mailbox that is *born after* the
        strategy actor is already dead, so closing here would refuse
        the notifications settlement depends on. One mailbox, two
        lanes, two lifetimes (S9).

        Idempotent: tripping a tripped latch is a no-op.
        """
        self._commands_refused = True

    # -- instrumentation --------------------------------------------------

    @property
    def attempted(self):
        """
        Return how many commands this actor took up.

        Posting an event proves only that it was queued -- in threaded
        mode the deciding had not started yet -- so a session that
        reports having traded because 'post_event' returned is
        reporting the intent (report 20260826-01, B3). This is the
        next fact along: a command reached the broker side.

        It is still not the same as having traded. See 'completed'.

        Returns
        -------
        `int`
            The lifetime count of commands taken up.
        """
        return self._attempted

    @property
    def completed(self):
        """
        Return how many commands ran to the end.

        The honest answer to "did a rebalance happen", and the reason
        it is separate from 'attempted': a command that raised was
        taken up and did not happen. A single counter read both ways
        made a cycle the operator stopped indistinguishable from an
        ordinary day (report 20260826-02, S4).

        Returns
        -------
        `int`
            The lifetime count of commands that returned normally.
        """
        return self._completed

    @property
    def synchronous(self):
        """
        Return whether commands are carried out on the caller's thread.

        Read by the strategy actor at construction, so that the two
        halves cannot be assembled in disagreeing modes.

        Returns
        -------
        `Boolean`
            Whether this actor is synchronous.
        """
        return self._synchronous

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
