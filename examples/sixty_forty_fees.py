import os

import pandas as pd
import pytz

from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.equity import Equity
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.broker.fee_model.percent_fee_model import PercentFeeModel
from vmtrader.broker.fee_model.zero_fee_model import ZeroFeeModel
from vmtrader.data.backtest_data_handler import BacktestDataHandler
from vmtrader.data.daily_bar_csv import CSVDailyBarDataSource
from vmtrader.statistics.tearsheet import TearsheetStatistics
from vmtrader.trading.backtest import BacktestTradingSession

from tearsheet_output import output_tearsheet, parse_args


if __name__ == "__main__":
    args = parse_args(__file__, description='60/40 US Equities/Bonds (수수료 유무 비교) 백테스트.')

    start_dt = pd.Timestamp('2003-09-30 14:30:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2019-12-31 23:59:00', tz=pytz.UTC)

    # Construct the symbols and assets necessary for the backtest
    strategy_symbols = ['SPY', 'AGG']
    strategy_assets = ['EQ:%s' % symbol for symbol in strategy_symbols]
    strategy_universe = StaticUniverse(strategy_assets)

    # To avoid loading all CSV files in the directory, set the
    # data source to load only those provided symbols
    csv_dir = os.environ.get('VMTRADER_CSV_DATA_DIR', '.')
    data_source = CSVDailyBarDataSource(csv_dir, Equity, csv_symbols=strategy_symbols)
    data_handler = BacktestDataHandler(strategy_universe, data_sources=[data_source])

    # Construct the transaction cost modelling - fees/slippage
    fee_model = PercentFeeModel(commission_pct=0.1 / 100.0, tax_pct=0.5 / 100.0)

    # Construct an Alpha Model that simply provides
    # static allocations to a universe of assets
    # In this case 60% SPY ETF, 40% AGG ETF,
    # rebalanced at the end of each month
    strategy_alpha_model = FixedSignalsAlphaModel({'EQ:SPY': 0.6, 'EQ:AGG': 0.4})
    strategy_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        strategy_universe,
        strategy_alpha_model,
        rebalance='end_of_month',
        long_only=True,
        cash_buffer_percentage=0.01,
        data_handler=data_handler,
        fee_model=fee_model
    )
    strategy_backtest.run()

    # Construct benchmark assets (60/40 without fees)
    benchmark_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        strategy_universe,
        strategy_alpha_model,
        rebalance='end_of_month',
        long_only=True,
        cash_buffer_percentage=0.01,
        data_handler=data_handler,
        fee_model=ZeroFeeModel()
    )
    benchmark_backtest.run()

    # Performance Output
    tearsheet = TearsheetStatistics(
        strategy_equity=strategy_backtest.get_equity_curve(),
        benchmark_equity=benchmark_backtest.get_equity_curve(),
        title='60/40 US Equities/Bonds (With/Without Fees)'
    )
    output_tearsheet(tearsheet, args)
