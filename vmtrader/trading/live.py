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
from vmtrader.broker.live.guards import KillSwitchEngaged
from vmtrader.broker.live.reconcile import reconcile
from vmtrader.signals.warmup import warm_up_signals
from vmtrader.trading.trading_session import TradingSession


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
    """

    def __init__(
        self,
        broker,
        qts,
        signals=None,
        rebalance_dates=None,
        time_budget=None,
        close_buffer=None,
        clock=None
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

        self.qts(now)
        outcome['traded'] = True

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
