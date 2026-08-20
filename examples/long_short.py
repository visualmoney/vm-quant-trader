import os

import pandas as pd
import pytz

from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.equity import Equity
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.data.backtest_data_handler import BacktestDataHandler
from vmtrader.data.daily_bar_csv import CSVDailyBarDataSource
from vmtrader.statistics.tearsheet import TearsheetStatistics
from vmtrader.trading.backtest import BacktestTradingSession

from tearsheet_output import output_tearsheet, parse_args


if __name__ == "__main__":
    args = parse_args(__file__, description='Long/Short Leveraged Treasury Bond ETFs 백테스트.')

    start_dt = pd.Timestamp('2007-01-31 14:30:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2020-05-31 23:59:00', tz=pytz.UTC)

    # Construct the symbols and assets necessary for the backtest
    strategy_symbols = ['TLT', 'IEI']
    strategy_assets = ['EQ:%s' % symbol for symbol in strategy_symbols]
    strategy_universe = StaticUniverse(strategy_assets)

    # To avoid loading all CSV files in the directory, set the
    # data source to load only those provided symbols
    csv_dir = os.environ.get('VMTRADER_CSV_DATA_DIR', '.')
    data_source = CSVDailyBarDataSource(csv_dir, Equity, csv_symbols=strategy_symbols)
    data_handler = BacktestDataHandler(strategy_universe, data_sources=[data_source])

    # Construct an Alpha Model that simply provides
    # static allocations to a universe of assets
    # In this case 100% TLT ETF, -70% IEI ETF,
    # rebalanced at the end of each month, leveraged 5x
    strategy_alpha_model = FixedSignalsAlphaModel(
        {'EQ:TLT': 1.0, 'EQ:IEI': -0.7}
    )
    strategy_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        strategy_universe,
        strategy_alpha_model,
        rebalance='end_of_month',
        long_only=False,
        gross_leverage=5.0,
        data_handler=data_handler
    )
    strategy_backtest.run()

    # Construct benchmark assets (buy & hold SPY)
    benchmark_symbols = ['SPY']
    benchmark_assets = ['EQ:SPY']
    benchmark_universe = StaticUniverse(benchmark_assets)
    benchmark_data_source = CSVDailyBarDataSource(csv_dir, Equity, csv_symbols=benchmark_symbols)
    benchmark_data_handler = BacktestDataHandler(benchmark_universe, data_sources=[benchmark_data_source])

    # Construct a benchmark Alpha Model that provides
    # 100% static allocation to the SPY ETF, with no rebalance
    benchmark_alpha_model = FixedSignalsAlphaModel({'EQ:SPY': 1.0})
    benchmark_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        benchmark_universe,
        benchmark_alpha_model,
        rebalance='buy_and_hold',
        long_only=True,
        cash_buffer_percentage=0.01,
        data_handler=benchmark_data_handler
    )
    benchmark_backtest.run()

    # Performance Output
    tearsheet = TearsheetStatistics(
        strategy_equity=strategy_backtest.get_equity_curve(),
        benchmark_equity=benchmark_backtest.get_equity_curve(),
        title='Long/Short Leveraged Treasury Bond ETFs'
    )
    output_tearsheet(tearsheet, args)
