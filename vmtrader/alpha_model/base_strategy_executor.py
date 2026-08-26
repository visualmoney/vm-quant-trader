"""
The strategy actor: a thread, a mailbox, and the strategy it owns.

This is the slow half of the pipeline. The broker must be quick and
exact because it holds the money; a strategy may call an API, load a
model, or think for five seconds, and separating the two means the
thinking never delays a fill being recorded.

It is a 'Thread' by inheritance because an actor's identity is its
thread, and 'Thread' being single-use is the point rather than a
limitation: a stopped executor is not restarted, a new one is built.
Under cron that is free, since every launch is a new process.

The consumer loop is written here rather than borrowed from
'TaskQueueWorker'. The two follow the same contract -- a sentinel
ends it, a raising handler is reported and the loop survives -- and
the cost of having written it twice is that both are pinned by tests
that assert the same things.

Both modes run the same '_dispatch'. That is the whole reason the
synchronous mode exists as a flag rather than a second class: a
backtest and a live session reach a strategy hook by the same code,
so a bug found in one is a bug in both.

It is called '_dispatch' and not '_handle' for a reason worth
knowing. 'Thread.__init__' assigns 'self._handle' -- a real thread
handle since Python 3.13 -- so a method of that name is defined on
the class and then shadowed on every instance, and the first call
fails with a TypeError about a '_thread._ThreadHandle' not being
callable. Subclassing 'Thread' means sharing its instance namespace,
and the reserved names are not documented anywhere; a test asserts
that none of this class's methods are shadowed rather than leaving
the next Python release to find out.

See docs/dev/threading-and-event-architecture.md, decisions 2, 3, 4
and 9, and appendix C.
"""

import logging
import traceback

from threading import Thread

from vmtrader.messaging import Mailbox, OrderFilled, RebalanceDue

logger = logging.getLogger(__name__)

# What an outbox must not be able to reach. Checked by attribute name
# rather than by type, and deliberately: importing the broker actor to
# use isinstance would put the accounting package back within this
# module's reach, which is the thing the import boundary exists to
# prevent. The property that matters was never the nominal type
# anyway -- it is that the object the strategy holds is inert.
_WRITES_THE_ACCOUNTING = (
    'portfolios', 'open_orders', 'ledger', 'submit_order',
    'size_and_submit', 'update', 'settle', 'transact_asset'
)


def _refuse_an_outbox_that_can_write(broker):
    """
    Reject anything that could turn the outbox into a write path.

    The strategy actor may be cut at shutdown, so what it holds must
    not be able to book. This is the guard for the third fact in the
    mode -- the flag and 'start()' had guards, and the one that could
    lose money did not.

    Parameters
    ----------
    broker : `object`
        The candidate broker actor.

    Raises
    ------
    `TypeError`
        If it cannot deliver a command, or if it exposes a way to
        write the accounting.
    """
    if not callable(getattr(broker, 'post_command', None)):
        raise TypeError(
            'the broker actor must expose post_command(command); got '
            '%r, which cannot receive a decision at all'
            % type(broker).__name__
        )
    reachable = sorted(
        name for name in _WRITES_THE_ACCOUNTING if hasattr(broker, name)
    )
    if reachable:
        raise TypeError(
            'refusing an outbox that can write: %r exposes %s. The '
            'strategy would be holding the accounting, which is the '
            'withdrawn decision 5.'
            % (type(broker).__name__, ', '.join(reachable))
        )


class BaseStrategyExecutor(Thread):
    """
    Runs a strategy's reactions on a thread of its own.

    Parameters
    ----------
    strategy : `BaseStrategy`
        The strategy. Owned, not inherited from: its author never
        sees a thread API.
    decide : `callable`
        Takes a timestamp and returns the 'TargetWeights' the
        strategy wants. Everything it does must be a function of time
        and market data -- it runs on this thread, which owns no
        account state.
    broker : `BrokerActor`
        The broker actor this one sends decisions to. Its mailbox door
        becomes the outbox; nothing else here can reach it.

        Taken as the object rather than as a bare callable on purpose.
        A free callable is what let the portfolio's write path be
        handed in and called on this thread (report 20260826-01, B1),
        and no import boundary could see it. What is checked is not the
        type but the property that mattered: an outbox must not be able
        to write.
    synchronous : `Boolean`, optional
        Whether to handle events on the caller's thread instead of
        queueing them. Decided once, by whichever session assembles
        this, and never per call. Must match the broker actor's mode.
    on_error : `callable`, optional
        Called with the exception when a handler raises. The failure
        is logged either way; the loop abandons that event and takes
        the next.

    Raises
    ------
    `TypeError`
        If the broker actor exposes anything that writes.
    `RuntimeError`
        If the two actors disagree about the mode.
    """

    def __init__(
        self,
        strategy,
        decide,
        broker,
        synchronous=False,
        on_error=None
    ):
        super().__init__(name='strategy-executor', daemon=True)
        _refuse_an_outbox_that_can_write(broker)
        if getattr(broker, 'synchronous', None) is not synchronous:
            raise RuntimeError(
                'the two actors disagree about the mode: executor '
                'synchronous=%r, broker synchronous=%r. A queued '
                'command with nobody consuming, or a handler running '
                'on the wrong thread, follows from every mismatch.'
                % (synchronous, getattr(broker, 'synchronous', None))
            )
        self._strategy = strategy
        self._decide = decide
        self._broker = broker
        self._post_command = broker.post_command
        self._synchronous = synchronous
        self._on_error = on_error
        self._mailbox = Mailbox('strategy-executor')

    # -- the face the producers call ------------------------------------

    def post_event(self, event):
        """
        Hand the executor a fact. Fire and forget; never blocks.

        Parameters
        ----------
        event : `object`
            Any event this executor knows how to handle.

        Raises
        ------
        `RuntimeError`
            If this is a threaded executor with nobody consuming. An
            event queued against a consumer that was never started,
            or has already stopped, would sit there until the process
            ended and be lost without a sound. Refusing is what turns
            that into a stack trace at the mistake.
        """
        if self._synchronous:
            self._dispatch(event)
        elif not self.is_alive():
            raise RuntimeError(
                "executor '%s' is not consuming: it was never started, "
                "or it has already stopped. A stopped executor is not "
                "restarted -- build a new one." % self.name
            )
        else:
            self._mailbox.post(event)

    def start(self):
        """
        Start the consumer thread.

        Raises
        ------
        `RuntimeError`
            If this executor is synchronous. Its events are handled
            on the caller's thread, so a thread started here would
            wait on a mailbox nothing posts to -- alive, idle, and
            invisible.
        """
        if self._synchronous:
            raise RuntimeError(
                "executor '%s' is synchronous; starting a thread would "
                "leave it waiting on a mailbox nothing posts to."
                % self.name
            )
        super().start()

    # -- the consumer loop ----------------------------------------------

    def run(self):
        """
        Take events one at a time until the mailbox closes.

        A handler that raises is reported and the loop continues. The
        single consumer is the single point of failure for everything
        downstream of it, so the one thing it must not do is end
        because a strategy had a bad day.
        """
        while True:
            event = self._mailbox.take()
            if event is None:
                break
            try:
                self._dispatch(event)
            except Exception as error:  # noqa: BLE001
                logger.error(
                    'Executor[%s] handler Exception:\n%s',
                    self.name, traceback.format_exc()
                )
                if self._on_error is not None:
                    self._on_error(error)

    # -- the one path both modes take -----------------------------------

    def _dispatch(self, event):
        """
        Dispatch one event to whatever answers for it.

        The only place an event becomes an action, in either mode.

        Parameters
        ----------
        event : `object`
            The event to handle.
        """
        if isinstance(event, RebalanceDue):
            self._post_command(self._decide(event.dt))
        elif isinstance(event, OrderFilled):
            self._strategy.on_fill(event)
        else:
            # Every other event in the vocabulary is addressed to the
            # broker. Arriving here means a producer sent it to the
            # wrong actor, which is a wiring mistake and not something
            # to absorb quietly.
            raise TypeError(
                "executor '%s' was sent a %s, which is not addressed to "
                "it" % (self.name, type(event).__name__)
            )

    # -- the face the session assembling this calls ----------------------

    def stop(self, timeout=None):
        """
        Drain what was posted, then end the thread.

        The ordinary way down. The daemon flag is the last resort
        underneath it, not this: it only decides what happens when a
        strategy has stopped responding altogether.

        Parameters
        ----------
        timeout : `float`, optional
            Seconds to wait for the thread to end. Without one, waits
            indefinitely.

        Returns
        -------
        `Boolean`
            Whether the executor finished. A synchronous one always
            has.
        """
        if self._synchronous:
            return True
        self._mailbox.close()
        self.join(timeout)
        if self.is_alive():
            logger.error(
                'Executor[%s] did not stop within %ss; a strategy '
                'callback is still running.', self.name, timeout
            )
            return False
        return True

    # -- instrumentation --------------------------------------------------

    @property
    def mailbox(self):
        """
        Return the mailbox, for its depth and counters.

        Returns
        -------
        `Mailbox`
            The queue this executor consumes.
        """
        return self._mailbox
