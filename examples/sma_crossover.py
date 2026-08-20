import os

import pandas as pd
import pytz

from vmtrader.alpha_model.alpha_model import AlphaModel
from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.equity import Equity
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.data.backtest_data_handler import BacktestDataHandler
from vmtrader.data.daily_bar_csv import CSVDailyBarDataSource
from vmtrader.signals.signals_collection import SignalsCollection
from vmtrader.signals.sma import SMASignal
from vmtrader.statistics.tearsheet import TearsheetStatistics
from vmtrader.trading.backtest import BacktestTradingSession

from tearsheet_output import output_tearsheet, parse_args


class SMACrossoverAlphaModel(AlphaModel):
    """
    An alpha model that holds, in equal weight, every asset whose
    short-period simple moving average sits above its long-period
    simple moving average, and holds nothing otherwise.

    This is the classic 'golden cross' trend filter applied per asset
    rather than to a single index. With a two asset universe of SPY and
    AGG it produces four states: both trending (50/50), one trending
    (100% of that asset), or neither trending (fully in cash).

    Note that the weights are normalised to sum to unity by the order
    sizer, so holding a single trending asset means holding 100% of it,
    not 50% with the remainder in cash. Cash is only held when no asset
    qualifies at all.

    Parameters
    ----------
    signals : `SignalsCollection`
        The entity for interfacing with the pre-calculated signals.
        In this instance the 'sma' signal is required.
    short_lookback : `int`
        The number of business days in the short moving average.
    long_lookback : `int`
        The number of business days in the long moving average. Also
        determines how many daily closes must be buffered before any
        weight is generated.
    universe : `Universe`
        The collection of assets to allocate between.
    data_handler : `DataHandler`
        The interface to the pricing data.
    """

    def __init__(
        self, signals, short_lookback, long_lookback, universe, data_handler
    ):
        self.signals = signals
        self.short_lookback = short_lookback
        self.long_lookback = long_lookback
        self.universe = universe
        self.data_handler = data_handler

    def _trending_assets(self, dt):
        """
        Determine which assets are in an uptrend, that is, those whose
        short moving average exceeds their long moving average.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The datetime for which the trend should be determined.

        Returns
        -------
        `list[str]`
            The asset symbols currently in an uptrend.
        """
        return [
            asset for asset in self.universe.get_assets(dt)
            if self.signals['sma'](asset, self.short_lookback) >
            self.signals['sma'](asset, self.long_lookback)
        ]

    def _generate_signals(self, dt, weights):
        """
        Assign 1 / N of the signal weight to each trending asset,
        leaving every other asset at zero.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The datetime for which the signal weights
            should be calculated.
        weights : `dict{str: float}`
            The current signal weights dictionary.

        Returns
        -------
        `dict{str: float}`
            The newly created signal weights dictionary.
        """
        trending = self._trending_assets(dt)

        # An all-zero weight vector liquidates the portfolio into cash,
        # since the order sizer leaves a zero-sum vector unscaled
        if not trending:
            return weights

        for asset in trending:
            weights[asset] = 1.0 / len(trending)
        return weights

    def __call__(self, dt):
        """
        Calculate the signal weights for the SMA crossover alpha
        model, assuming that enough daily closes have been buffered
        to calculate the long moving average.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The datetime for which the signal weights
            should be calculated.

        Returns
        -------
        `dict{str: float}`
            The newly created signal weights dictionary.
        """
        weights = {asset: 0.0 for asset in self.universe.get_assets(dt)}

        # Only generate weights once the price buffers are full,
        # otherwise the long moving average is taken over a partial window
        if self.signals.warmup >= self.long_lookback:
            weights = self._generate_signals(dt, weights)
        return weights


def print_comparison(strategy_equity, benchmark_equity, periods=252):
    """
    Print a side by side comparison of the strategy and benchmark
    performance statistics.

    Parameters
    ----------
    strategy_equity : `pd.DataFrame`
        The strategy equity curve, carrying an 'Equity' column.
    benchmark_equity : `pd.DataFrame`
        The benchmark equity curve, carrying an 'Equity' column.
    periods : `int`, optional
        The number of periods in a year, used for annualisation.
    """
    from vmtrader.statistics import performance as perf

    def stats(equity_df):
        returns = equity_df['Equity'].pct_change().fillna(0.0)
        cum_returns = (1.0 + returns).cumprod()
        _, max_dd, dd_dur = perf.create_drawdowns(cum_returns)
        return {
            'Total Return': cum_returns.iloc[-1] - 1.0,
            'CAGR': perf.create_cagr(cum_returns, periods),
            'Sharpe': perf.create_sharpe_ratio(returns, periods),
            'Sortino': perf.create_sortino_ratio(returns, periods),
            'Max Drawdown': max_dd,
            'Max DD Duration': dd_dur,
        }

    strategy = stats(strategy_equity)
    benchmark = stats(benchmark_equity)

    print()
    print('%-18s %14s %14s' % ('', 'SMA Crossover', '60/40'))
    print('-' * 48)
    for metric in strategy:
        if metric == 'Max DD Duration':
            print('%-18s %11d일 %11d일' % (
                metric, strategy[metric], benchmark[metric]
            ))
        elif metric in ('Sharpe', 'Sortino'):
            print('%-18s %14.2f %14.2f' % (
                metric, strategy[metric], benchmark[metric]
            ))
        else:
            print('%-18s %13.2f%% %13.2f%%' % (
                metric, strategy[metric] * 100.0, benchmark[metric] * 100.0
            ))
    print()


if __name__ == "__main__":
    args = parse_args(
        __file__,
        description='SPY/AGG SMA 크로스오버 전략 대 60/40 벤치마크 백테스트.'
    )

    # Duration of the backtest. The burn-in date is a full year after the
    # start so that the 200 day buffer is filled before any trade is made
    start_dt = pd.Timestamp('2003-09-30 14:30:00', tz=pytz.UTC)
    burn_in_dt = pd.Timestamp('2004-09-30 14:30:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2019-12-31 23:59:00', tz=pytz.UTC)

    # Model parameters. 50 and 200 business days are the conventional
    # 'golden cross' pair
    short_lookback = 50
    long_lookback = 200

    # The strategy allocates between the same two assets as the 60/40
    # benchmark, so the comparison isolates the allocation rule itself
    symbols = ['SPY', 'AGG']
    assets = ['EQ:%s' % symbol for symbol in symbols]
    universe = StaticUniverse(assets)

    # To avoid loading all CSV files in the directory, set the
    # data source to load only those provided symbols
    csv_dir = os.environ.get('VMTRADER_CSV_DATA_DIR', '.')
    data_source = CSVDailyBarDataSource(csv_dir, Equity, csv_symbols=symbols)
    data_handler = BacktestDataHandler(universe, data_sources=[data_source])

    # Generate the moving average signals used by the alpha model. Both
    # lookbacks are buffered for every asset in the universe
    sma = SMASignal(start_dt, universe, lookbacks=[short_lookback, long_lookback])
    signals = SignalsCollection({'sma': sma}, data_handler)

    strategy_alpha_model = SMACrossoverAlphaModel(
        signals, short_lookback, long_lookback, universe, data_handler
    )

    strategy_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        universe,
        strategy_alpha_model,
        signals=signals,
        rebalance='end_of_month',
        long_only=True,
        cash_buffer_percentage=0.01,
        burn_in_dt=burn_in_dt,
        data_handler=data_handler
    )
    strategy_backtest.run()

    # Construct the 60/40 benchmark. It begins at the burn-in date rather
    # than the start date so that both equity curves share an index
    benchmark_alpha_model = FixedSignalsAlphaModel({'EQ:SPY': 0.6, 'EQ:AGG': 0.4})
    benchmark_backtest = BacktestTradingSession(
        burn_in_dt,
        end_dt,
        universe,
        benchmark_alpha_model,
        rebalance='end_of_month',
        long_only=True,
        cash_buffer_percentage=0.01,
        data_handler=data_handler
    )
    benchmark_backtest.run()

    strategy_equity = strategy_backtest.get_equity_curve()
    benchmark_equity = benchmark_backtest.get_equity_curve()
    print_comparison(strategy_equity, benchmark_equity)

    # Performance Output
    tearsheet = TearsheetStatistics(
        strategy_equity=strategy_equity,
        benchmark_equity=benchmark_equity,
        title='SPY/AGG SMA Crossover vs 60/40'
    )
    output_tearsheet(tearsheet, args)
