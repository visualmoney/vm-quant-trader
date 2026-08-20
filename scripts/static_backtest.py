from datetime import datetime, timedelta
import os

import click
import pandas as pd
import pytz

from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.equity import Equity
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.data.backtest_data_handler import BacktestDataHandler
from vmtrader.data.daily_bar_csv import CSVDailyBarDataSource
from vmtrader.env_file import load_env_file
from vmtrader.statistics.json_statistics import JSONStatistics
from vmtrader.statistics.tearsheet import TearsheetStatistics
from vmtrader.trading.backtest import BacktestTradingSession


DATE_FORMAT = '%Y-%m-%d'


def obtain_allocations(allocations):
    """
    Converts the provided command-line allocations string
    into a dictionary used for VMTrader.

    Parameters
    ----------
    allocations : `str`
        The asset allocations string. e.g. 'SPY:0.6,AGG:0.4'.

    Returns
    -------
    `dict`
        The asset allocation dictionary

    Raises
    ------
    `click.BadParameter`
        If the string cannot be parsed into asset/weight pairs.
    """
    allocs_dict = {}
    for alloc in allocations.split(','):
        try:
            alloc_asset, alloc_value = alloc.split(':')
            allocs_dict['EQ:%s' % alloc_asset.strip()] = float(alloc_value)
        except ValueError:
            raise click.BadParameter(
                "could not parse '%s'. Expected comma-separated "
                "SYMBOL:WEIGHT pairs, e.g. 'SPY:0.6,AGG:0.4'." % alloc
            )
    return allocs_dict


def parse_allocations(ctx, param, value):
    """
    Click callback converting the '--allocations' string into a dictionary.

    Parsing here rather than in the command body means a malformed string is
    reported as a usage error, with a non-zero exit code, before the backtest
    starts.

    Parameters
    ----------
    ctx : `click.Context`
        The Click context. Unused.
    param : `click.Parameter`
        The parameter being processed. Unused.
    value : `str`
        The asset allocations string.

    Returns
    -------
    `dict`
        The asset allocation dictionary
    """
    return obtain_allocations(value)


def to_timestamp(date, end_of_day=False):
    """
    Convert a parsed command-line date into a UTC pandas Timestamp.

    Parameters
    ----------
    date : `datetime.datetime`
        The date provided on the command line.
    end_of_day : `Boolean`, optional
        Whether to use the end of the trading day (23:59) rather than
        midnight. Defaults to False.

    Returns
    -------
    `pd.Timestamp`
        The UTC-localised timestamp.
    """
    time = '23:59:00' if end_of_day else '00:00:00'
    return pd.Timestamp(
        '%s %s' % (date.strftime(DATE_FORMAT), time), tz=pytz.UTC
    )


@click.command()
@click.option(
    '--start-date', 'start_date', required=True,
    type=click.DateTime([DATE_FORMAT]),
    help='Backtest starting date, as YYYY-MM-DD'
)
@click.option(
    '--end-date', 'end_date', default=None,
    type=click.DateTime([DATE_FORMAT]),
    help='Backtest ending date, as YYYY-MM-DD. Defaults to yesterday.'
)
@click.option(
    '--allocations', 'alloc_dict', required=True, callback=parse_allocations,
    help='Allocations key-values, i.e. "SPY:0.6,AGG:0.4"'
)
@click.option(
    '--title', 'strat_title', required=True,
    help='Backtest strategy title'
)
@click.option(
    '--id', 'strat_id', required=True,
    help='Backtest strategy ID string'
)
@click.option(
    '--output-dir', 'output_dir', default=None, type=click.Path(),
    help=(
        'Directory to write the JSON statistics into. Defaults to the '
        'VMTRADER_OUTPUT_DIR environment variable, or the current directory.'
    )
)
@click.option(
    '--tearsheet', 'tearsheet', is_flag=True, default=False,
    help='Whether to display the (blocking) tearsheet plot'
)
@click.option(
    '--tearsheet-file', 'tearsheet_file', default=None, type=click.Path(),
    help=(
        'Save the tearsheet to this path. Works without a display, so it '
        'can be used on headless machines.'
    )
)
def cli(
    start_date, end_date, alloc_dict, strat_title, strat_id,
    output_dir, tearsheet, tearsheet_file
):
    # Pick up VMTRADER_CSV_DATA_DIR and friends from a '.env' file, if present.
    # Variables already set in the environment take precedence.
    load_env_file()

    csv_dir = os.environ.get('VMTRADER_CSV_DATA_DIR', '.')

    if output_dir is None:
        output_dir = os.environ.get('VMTRADER_OUTPUT_DIR', '.')

    start_dt = to_timestamp(start_date)

    if end_date is None:
        # Use yesterday's date
        end_date = datetime.now() - timedelta(1)
    end_dt = to_timestamp(end_date, end_of_day=True)

    # Assets and Data Handling
    strategy_assets = list(alloc_dict.keys())
    strategy_symbols = [symbol.replace('EQ:', '') for symbol in strategy_assets]
    strategy_universe = StaticUniverse(strategy_assets)
    strategy_data_source = CSVDailyBarDataSource(
        csv_dir, Equity, csv_symbols=strategy_symbols
    )

    strategy_data_handler = BacktestDataHandler(
        strategy_universe, data_sources=[strategy_data_source]
    )

    strategy_alpha_model = FixedSignalsAlphaModel(alloc_dict)
    strategy_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        strategy_universe,
        strategy_alpha_model,
        rebalance='end_of_month',
        account_name=strat_title,
        portfolio_id='STATIC001',
        portfolio_name=strat_title,
        long_only=True,
        cash_buffer_percentage=0.01,
        data_handler=strategy_data_handler
    )
    strategy_backtest.run()

    # Benchmark: 60/40 US Equities/Bonds
    benchmark_symbols = ['SPY', 'AGG']
    benchmark_assets = ['EQ:SPY', 'EQ:AGG']
    benchmark_universe = StaticUniverse(benchmark_assets)

    benchmark_data_source = CSVDailyBarDataSource(
        csv_dir, Equity, csv_symbols=benchmark_symbols
    )
    benchmark_data_handler = BacktestDataHandler(
        benchmark_universe, data_sources=[benchmark_data_source]
    )

    benchmark_signal_weights = {'EQ:SPY': 0.6, 'EQ:AGG': 0.4}
    benchmark_title = '60/40 US Equities/Bonds'
    benchmark_alpha_model = FixedSignalsAlphaModel(benchmark_signal_weights)
    benchmark_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        benchmark_universe,
        benchmark_alpha_model,
        rebalance='end_of_month',
        account_name='60/40 US Equities/Bonds',
        portfolio_id='6040EQBD',
        portfolio_name=benchmark_title,
        long_only=True,
        cash_buffer_percentage=0.01,
        data_handler=benchmark_data_handler
    )
    benchmark_backtest.run()

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    output_filename = os.path.join(
        output_dir, ('%s_monthly.json' % strat_id).replace('-', '_')
    )
    stats = JSONStatistics(
        equity_curve=strategy_backtest.get_equity_curve(),
        target_allocations=strategy_backtest.get_target_allocations(),
        strategy_id=strat_id,
        strategy_name=strat_title,
        benchmark_curve=benchmark_backtest.get_equity_curve(),
        benchmark_id='6040-us-equitiesbonds',
        benchmark_name=benchmark_title,
        output_filename=output_filename
    )
    stats.to_file()

    if tearsheet or tearsheet_file is not None:
        if not tearsheet:
            # 저장만 할 때는 디스플레이가 필요 없는 백엔드로 전환한다
            import matplotlib
            matplotlib.use('Agg')

        tearsheet_stats = TearsheetStatistics(
            strategy_equity=strategy_backtest.get_equity_curve(),
            benchmark_equity=benchmark_backtest.get_equity_curve(),
            title=strat_title
        )
        tearsheet_stats.plot_results(filename=tearsheet_file, show=tearsheet)


if __name__ == "__main__":
    cli()
