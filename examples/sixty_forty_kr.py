"""
A 60/40 portfolio of Korean ETFs, rebalanced monthly.

The same shape as the US example beside it -- sixty per cent equity,
forty per cent bonds -- with three substitutions that matter:

  * KODEX 200 (069500) for the equity leg and KOSEF 국고채10년 (148070)
    for the bond leg;
  * won as the account currency, so sizing and reporting are in the
    currency the account is actually denominated in;
  * Korean trading costs, which are asymmetric -- brokerage on both
    sides, transaction tax on sales only. A monthly rebalance sells
    something almost every month, so pricing that tax matters to the
    result rather than being a rounding detail.

The benchmark is buy-and-hold of the equity leg alone, which is the
comparison a 60/40 investor is actually making: does holding bonds
earn its keep?

Price history comes from the venue, via scripts/fetch_daily_bars.py,
so the backtest and the live session read the same source.
"""

import os

import pandas as pd
import pytz

from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.equity import Equity
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.broker.fee_model.korea_fee_model import KoreaStockFeeModel
from vmtrader.data.backtest_data_handler import BacktestDataHandler
from vmtrader.data.daily_bar_csv import CSVDailyBarDataSource
from vmtrader.statistics.tearsheet import TearsheetStatistics
from vmtrader.trading.backtest import BacktestTradingSession

from tearsheet_output import output_tearsheet, parse_args


# Retail brokerage on Korean equities, and the securities transaction
# tax charged on sales. Both are order-of-magnitude right rather than
# any particular broker's schedule; adjust to your own.
COMMISSION_PCT = 0.00015
TRANSACTION_TAX_PCT = 0.0018

EQUITY = '069500'    # KODEX 200
BONDS = '148070'     # KOSEF 국고채10년


if __name__ == "__main__":
    args = parse_args(
        __file__, description='60/40 한국 주식/채권 ETF 백테스트.'
    )

    # 14:30 UTC because the simulated exchange still keeps NYSE hours
    # (see the spec's C-6): a rebalance timestamped outside them never
    # executes. The prices are Korean daily bars; the session times are
    # only scaffolding for a daily backtest.
    start_dt = pd.Timestamp('2022-09-01 14:30:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2026-08-20 23:59:00', tz=pytz.UTC)

    strategy_symbols = [EQUITY, BONDS]
    strategy_assets = ['EQ:%s' % symbol for symbol in strategy_symbols]
    strategy_universe = StaticUniverse(strategy_assets)

    csv_dir = os.environ.get('VMTRADER_CSV_DATA_DIR', '.')
    data_source = CSVDailyBarDataSource(
        csv_dir, Equity, csv_symbols=strategy_symbols
    )
    data_handler = BacktestDataHandler(
        strategy_universe, data_sources=[data_source]
    )

    fee_model = KoreaStockFeeModel(
        commission_pct=COMMISSION_PCT, tax_pct=TRANSACTION_TAX_PCT
    )

    strategy_alpha_model = FixedSignalsAlphaModel({
        'EQ:%s' % EQUITY: 0.6,
        'EQ:%s' % BONDS: 0.4,
    })
    strategy_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        strategy_universe,
        strategy_alpha_model,
        initial_cash=10000000.0,
        rebalance='end_of_month',
        long_only=True,
        cash_buffer_percentage=0.01,
        fee_model=fee_model,
        base_currency='KRW',
        data_handler=data_handler
    )
    strategy_backtest.run()

    # Benchmark: hold the equity leg and nothing else.
    benchmark_universe = StaticUniverse(['EQ:%s' % EQUITY])
    benchmark_alpha_model = FixedSignalsAlphaModel({'EQ:%s' % EQUITY: 1.0})
    benchmark_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        benchmark_universe,
        benchmark_alpha_model,
        initial_cash=10000000.0,
        rebalance='buy_and_hold',
        long_only=True,
        cash_buffer_percentage=0.01,
        fee_model=fee_model,
        base_currency='KRW',
        data_handler=data_handler
    )
    benchmark_backtest.run()

    tearsheet = TearsheetStatistics(
        strategy_equity=strategy_backtest.get_equity_curve(),
        benchmark_equity=benchmark_backtest.get_equity_curve(),
        title='60/40 한국 주식/채권 ETF (KODEX 200 / KOSEF 국고채10년)'
    )
    output_tearsheet(tearsheet, args)
