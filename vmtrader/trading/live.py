"""
The live trading session, run as a one-shot rather than a daemon.

Each launch does one thing and exits. The waiting between events is
cron's job, not a Python process's: a rebalance and an end-of-day
valuation are the only two events in a trading day, and holding a
pandas-loaded process open for the five hours between them buys
nothing on a small shared host.

That choice costs nothing because the engine already had to survive
restarts. Every launch reconciles against the venue, which means the
recovery path is also the ordinary startup path and gets exercised
daily rather than only after a crash.
"""

import pandas as pd

from vmtrader import settings
from vmtrader.alpha_model.base_strategy import as_strategy
from vmtrader.alpha_model.base_strategy_executor import BaseStrategyExecutor
from vmtrader.broker.actor import BrokerActor
from vmtrader.broker.live.guards import KillSwitchEngaged
from vmtrader.messaging import RebalanceDue
from vmtrader.broker.live.reconcile import reconcile
from vmtrader.signals.warmup import warm_up_signals
from vmtrader.trading.trading_session import TradingSession

# How long a cycle waits for the strategy to finish deciding. It is a
# budget rather than a guarantee: the executor is a daemon, so a
# strategy wedged on an external call cannot hold the cron slot past
# this, and what it was about to submit is settled by the next
# launch's reconciliation instead (ADR-0009).
#
# One of four numbers that bound a cycle, and until now none of them
# knew about the others (report 20260826-02, S14). The relationship
# they need is:
#
#     process cap  >  preamble + strategy budget
#                     + (settlement deadline - start) + shutdown timeout
#
# where the preamble is reconciliation and signal warm-up, the
# settlement deadline is 'min(start + time_budget, close - buffer)',
# the shutdown timeout is the fill worker's join in 'settle', and the
# process cap is the only one outside this process -- systemd's
# 'TimeoutStartSec' or a 'timeout -k' wrapper, since nothing inside
# can bound a main thread wedged on a vendor call.
#
# **With today's defaults it does not hold.** 3600s of cap against
# 60 + 3600 + 30 plus the preamble. What that buys is a SIGTERM
# arriving during 'settle''s finally or the STALE loop -- the one
# window where being killed costs the ledger's record of orders that
# are still working. Either the cap goes up or 'time_budget' comes
# down; the sum is what has to be looked at, which is why it is
# written here rather than left in three files.
STRATEGY_BUDGET_SECONDS = 60.0


class LiveTradingSession(TradingSession):
    """
    Runs one live cycle against a venue and returns.

    Parameters
    ----------
    broker : `LiveBroker`
        The live broker.
    qts : `QuantTradingSystem`
        The same trading system a backtest uses, unmodified.
    signals : `SignalsCollection`, optional
        Signals to warm from history before sizing. A live process
        holds no memory between launches, so without this a moving
        average would be computed from a single day's price.
    rebalance_dates : `list[pd.Timestamp]`, optional
        The dates on which trading is due. Without them every open day
        is a rebalance day.
    time_budget : `pd.Timedelta`, optional
        How long fill settlement may take. Defaults to one hour.
    close_buffer : `pd.Timedelta`, optional
        How far before the close settlement must stop regardless of
        the budget. Defaults to ten minutes.
    clock : `callable`, optional
        Returns the current timestamp. Injected for testing.
    synchronous : `Boolean`, optional
        Whether both actors handle their messages on the calling
        thread. True by default, which is Phase 0: no thread starts
        and a rebalance runs exactly where it always did. Setting it
        False gives the strategy a thread of its own; the cycle shape
        in '_decide_and_submit' is the same either way, which is the
        point of deciding the mode in one place.
    """

    def __init__(
        self,
        broker,
        qts,
        signals=None,
        rebalance_dates=None,
        time_budget=None,
        close_buffer=None,
        clock=None,
        synchronous=True
    ):
        self.broker = broker
        self.qts = qts
        self.signals = signals
        self.rebalance_dates = rebalance_dates
        self.time_budget = (
            time_budget if time_budget is not None
            else pd.Timedelta(minutes=60)
        )
        self.close_buffer = (
            close_buffer if close_buffer is not None
            else pd.Timedelta(minutes=10)
        )
        self.clock = clock if clock is not None else pd.Timestamp.now
        # Decision 4: the mode is decided here, by the assembly, and
        # nowhere else. Phase 1 flips this one argument; every guard
        # and both actors follow from it.
        self.synchronous = synchronous

    def _actors(self):
        """
        Build both actors for this launch and connect them.

        Synchronous, so no thread is started and the rebalance runs
        exactly where it always did. What the indirection buys is that
        the path from "trading is due" to an order is the same one a
        resident process will take -- when the flag flips there is no
        second code path to discover.

        The connection is the point. The executor's outbox is the
        broker actor's mailbox and nothing else: hand it
        'qts.size_and_submit' instead and the strategy is holding the
        portfolio's write path, which is what report 20260826-01 found
        as B1 and what decision 5 was withdrawn for.

        Built per cycle rather than held on the session, because a
        stopped executor is replaced rather than restarted. Under cron
        that costs nothing: each launch is one cycle.

        Returns
        -------
        `tuple[BaseStrategyExecutor, BrokerActor]`
            The strategy actor and the broker actor, both synchronous.
        """
        broker_actor = BrokerActor(
            size_and_submit=self.qts.size_and_submit,
            synchronous=self.synchronous,
            on_error=self._log_error
        )
        executor = BaseStrategyExecutor(
            strategy=as_strategy(
                self.qts.portfolio_construction_model.alpha_model
            ),
            decide=self.qts.decide_weights,
            broker=broker_actor,
            synchronous=self.synchronous,
            on_error=self._log_error
        )
        return executor, broker_actor

    def _decide_and_submit(self, now):
        """
        Run one rebalance to completion, whichever mode is in force.

        A cron cycle has an end, and this is what reaching it means:
        the strategy has finished deciding, and everything it decided
        has been carried out. Both have to be true before settlement
        starts, because settlement waits on open orders and there are
        none until the second one is.

        Getting this wrong was finding B3 of report 20260826-01. With
        a thread, 'post_event' returns having queued the event and
        nothing more; 'settle' then opens on an empty order book,
        returns zero, and the process exits and cuts the executor
        mid-decision. The rebalance does not happen, and the outcome
        says it did.

        The barrier is a join, not a question. Decision 12 refused the
        broker a thread because "has the cycle finished" would have to
        cross an actor boundary, and prohibition 1 forbids waiting on
        an answer -- but stopping an actor and waiting for it to
        finish is not asking it anything. That is also why decision
        2's single-use rule costs nothing here: the executor is built
        per cycle and a cycle ends it.

        Parameters
        ----------
        now : `pd.Timestamp`
            The time the rebalance is for.

        Returns
        -------
        `Boolean`
            Whether a decision actually reached the broker side.
        """
        executor, broker_actor = self._actors()
        try:
            if not executor.synchronous:
                executor.start()
            executor.post_event(RebalanceDue(dt=now))
        finally:
            # Barrier, and unconditional. Anything raised between
            # start() and here would otherwise leave a started thread
            # running into settlement, holding an outbox into a mailbox
            # nobody is draining. Writing this needed 'stop()' to be
            # total first: it used to raise out of Thread.join on an
            # executor that was never started, which in a 'finally'
            # means replacing the real exception with a complaint about
            # thread lifecycle (report 20260826-02, S2).
            if not executor.stop(timeout=STRATEGY_BUDGET_SECONDS):
                self._log(
                    'The strategy did not finish within %ss; whatever it '
                    'was about to submit is lost. The next launch '
                    'reconciles.' % STRATEGY_BUDGET_SECONDS
                )

        # The command lane closes here and not a line later. Between
        # the barrier and the drain is exactly the window an overrunning
        # strategy finishes in, and a command posted into that gap used
        # to be accepted, never consumed, and lost at exit (S1).
        broker_actor.refuse_commands()

        # What ended the executor -- an operator's stop, or a message
        # routed to the wrong actor -- cannot be raised on its own
        # thread and must not be swallowed, so it waits here. After the
        # barrier, not inside it: raising from the 'finally' would mask
        # whatever else had gone wrong.
        if executor.ended_by is not None:
            raise executor.ended_by

        # The broker actor's consumer is this thread (decision 12).
        broker_actor.drain()
        # Completed, not attempted: a command that was taken up and
        # then raised did not trade, and reporting otherwise is what
        # made a stopped cycle look like an ordinary one.
        return broker_actor.completed > 0

    def _log_error(self, error):
        """
        Report an exception raised inside a strategy handler.

        Parameters
        ----------
        error : `Exception`
            The exception raised.
        """
        self._log('Strategy handling failed: %s' % error)

    def _deadline(self, now):
        """
        Return when fill settlement must stop.

        The budget and the market close are both limits, and the
        earlier one wins: a rebalance that is still collecting fills at
        15:30 is collecting nothing.

        Parameters
        ----------
        now : `pd.Timestamp`
            The start of the cycle.

        Returns
        -------
        `pd.Timestamp`
            The deadline.
        """
        budget_end = now + self.time_budget
        close = pd.Timestamp.combine(
            now.date(), self.broker.exchange.close_time
        )
        if now.tzinfo is not None:
            close = close.tz_localize(now.tzinfo)
        return min(budget_end, close - self.close_buffer)

    def _is_rebalance_day(self, now):
        """
        Return whether trading is due today.

        cron fires every weekday; deciding whether today is a
        rebalance day belongs to the process, in the same place that
        knows about holidays.

        Parameters
        ----------
        now : `pd.Timestamp`
            The current timestamp.

        Returns
        -------
        `Boolean`
            Whether to trade today.
        """
        if not self.broker.exchange.is_trading_day(now):
            return False
        if self.rebalance_dates is None:
            return True
        return any(
            pd.Timestamp(dt).date() == now.date()
            for dt in self.rebalance_dates
        )

    def run_rebalance(self):
        """
        Run one rebalance: reconcile, size, submit, settle, exit.

        Returns
        -------
        `dict`
            What happened, for the operator's log.
        """
        now = self.clock()
        outcome = {
            'started_at': now,
            'traded': False,
            'reconcile': None,
            'fills_booked': 0,
            'reason': None
        }

        result = reconcile(self.broker)
        outcome['reconcile'] = result
        self._log(result.summary())
        if result.halt_trading:
            outcome['reason'] = 'reconciliation halted trading'
            return outcome

        try:
            self.broker.guard.check_can_trade()
        except KillSwitchEngaged as err:
            outcome['reason'] = str(err)
            self._log('Not trading: %s' % err)
            return outcome

        if not self._is_rebalance_day(now):
            outcome['reason'] = 'not a rebalance day'
            self._log('Not a rebalance day; exiting without trading.')
            return outcome

        if not self.broker.exchange.is_open_at_datetime(now):
            outcome['reason'] = 'market closed'
            self._log('Market is closed at %s; exiting.' % now)
            return outcome

        self.broker.update(now, force=True)

        warmed = self._warm_up_signals(now)
        if warmed is not None:
            outcome['signals_warmed'] = warmed
            if warmed and min(warmed.values()) == 0:
                # A signal with no history returns a number computed
                # from nothing. Sizing on it would be worse than not
                # trading today.
                starved = sorted(
                    asset for asset, count in warmed.items() if count == 0
                )
                outcome['reason'] = (
                    'no signal history for %s' % ', '.join(starved)
                )
                self._log(
                    'Refusing to trade: %s' % outcome['reason']
                )
                return outcome

        traded = self._decide_and_submit(now)
        outcome['traded'] = traded
        if not traded:
            outcome['reason'] = 'the strategy produced no decision'
            self._log(
                'The rebalance produced no decision; settling anything '
                'already open and exiting.'
            )

        deadline = self._deadline(now)
        self._log('Settling fills until %s.' % deadline)
        outcome['fills_booked'] = self.broker.settle(deadline)
        return outcome

    def _warm_up_signals(self, now):
        """
        Fill the signal buffers from history, if there are signals.

        Returns
        -------
        `dict{str: int}` or `None`
            How many prices each asset was warmed with, or None when
            the session has no signals to warm.
        """
        if self.signals is None:
            return None
        warmed = warm_up_signals(
            self.signals, self.broker.data_handler, now
        )
        self._log(
            'Warmed signals: %s'
            % ', '.join(
                '%s=%d' % (asset, count)
                for asset, count in sorted(warmed.items())
            )
        )
        return warmed

    def run_end_of_day(self):
        """
        Run the after-close launch: absorb late fills, value, record.

        Separate from the rebalance so that the trading process does
        not have to stay alive until the close, and so the equity curve
        is still written on a day when the rebalance crashed.

        Returns
        -------
        `dict`
            What happened, for the operator's log.
        """
        now = self.clock()
        result = reconcile(self.broker, halt_on_mismatch=False)
        self._log(result.summary())

        self.broker.update(now, force=True)
        self.broker.record_equity()
        equity = self.broker.get_account_total_equity()['master']
        self._log('Recorded equity of %.2f at %s.' % (equity, now))
        return {
            'started_at': now,
            'reconcile': result,
            'total_equity': equity
        }

    def run(self, results=False):
        """
        Run a rebalance cycle.

        Present because the TradingSession contract declares it. The
        two launches are the named methods; this is the default one.

        Parameters
        ----------
        results : `Boolean`, optional
            Ignored. A live session has no results to print.

        Returns
        -------
        `dict`
            What happened.
        """
        return self.run_rebalance()

    def _log(self, message):
        """
        Print an operational message, honouring the events setting.

        Parameters
        ----------
        message : `str`
            The message to print.
        """
        if settings.PRINT_EVENTS:
            print('(%s) - live session: %s' % (self.clock(), message))
