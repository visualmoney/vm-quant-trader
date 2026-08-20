import datetime
import os

import pandas as pd
import pytest
import pytz

from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.equity import Equity
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.data.backtest_data_handler import BacktestDataHandler
from vmtrader.data.daily_bar_csv import CSVDailyBarDataSource
from vmtrader.data.daily_bar_memory import InMemoryDailyBarDataSource
from vmtrader.trading.backtest import BacktestTradingSession


# The CSV fixtures and the expected history are the ones the end-to-end
# backtest test uses. Reusing them is the point: the in-memory source is
# only correct if it reproduces the CSV source's results exactly.
FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'trading', 'fixtures'
)
SYMBOLS = ['ABC', 'DEF']


@pytest.fixture
def csv_source():
    return CSVDailyBarDataSource(FIXTURE_DIR, Equity, csv_symbols=SYMBOLS)


@pytest.fixture
def memory_source():
    frames = {
        'EQ:%s' % symbol: pd.read_csv(
            os.path.join(FIXTURE_DIR, '%s.csv' % symbol),
            index_col='Date',
            parse_dates=True
        )
        for symbol in SYMBOLS
    }
    return InMemoryDailyBarDataSource(frames)


def test_bar_and_bid_ask_frames_are_identical(csv_source, memory_source):
    """
    Checks that both sources hold the same assets and produce byte-identical
    bar and bid/ask frames from the same underlying data.
    """
    assert set(csv_source.asset_bar_frames) == set(memory_source.asset_bar_frames)

    for asset in csv_source.asset_bar_frames:
        pd.testing.assert_frame_equal(
            csv_source.asset_bar_frames[asset],
            memory_source.asset_bar_frames[asset]
        )
        pd.testing.assert_frame_equal(
            csv_source.asset_bid_ask_frames[asset],
            memory_source.asset_bid_ask_frames[asset]
        )


def test_every_price_query_agrees(csv_source, memory_source):
    """
    Checks that the two sources answer identically at every timestamp
    the data carries, not merely that their stored frames match.
    """
    for asset, bid_ask_df in csv_source.asset_bid_ask_frames.items():
        for dt in bid_ask_df.index:
            assert csv_source.get_bid(dt, asset) == memory_source.get_bid(dt, asset)
            assert csv_source.get_ask(dt, asset) == memory_source.get_ask(dt, asset)


def test_historical_closes_agree(csv_source, memory_source):
    """
    Checks the multi-asset range query agrees across the two sources.
    """
    start_dt = pd.Timestamp('2019-01-01 00:00:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2019-01-31 23:59:00', tz=pytz.UTC)
    assets = ['EQ:%s' % symbol for symbol in SYMBOLS]

    pd.testing.assert_frame_equal(
        csv_source.get_assets_historical_closes(start_dt, end_dt, assets),
        memory_source.get_assets_historical_closes(start_dt, end_dt, assets)
    )


def test_backtest_through_the_in_memory_source_matches_the_csv_fixture(memory_source):
    """
    Runs the same weekly rebalanced 60/40 backtest as the end-to-end test,
    but supplied by the in-memory data source, and compares against the same
    expected history and holdings.

    This is the test that matters: it exercises the whole engine through the
    substituted data source and pins the result against a fixture written
    from the CSV path.
    """
    assets = ['EQ:ABC', 'EQ:DEF']
    universe = StaticUniverse(assets)
    alpha_model = FixedSignalsAlphaModel({'EQ:ABC': 0.6, 'EQ:DEF': 0.4})
    data_handler = BacktestDataHandler(universe, data_sources=[memory_source])

    backtest = BacktestTradingSession(
        pd.Timestamp('2019-01-01 00:00:00', tz=pytz.UTC),
        pd.Timestamp('2019-01-31 23:59:00', tz=pytz.UTC),
        universe,
        alpha_model,
        portfolio_id='000001',
        rebalance='weekly',
        rebalance_weekday='WED',
        long_only=True,
        cash_buffer_percentage=0.05,
        data_handler=data_handler
    )
    backtest.run(results=False)

    portfolio = backtest.broker.portfolios['000001']

    expected_dict = {
        'EQ:ABC': {
            'unrealised_pnl': -31121.26203538094,
            'realised_pnl': 0.0,
            'total_pnl': -31121.26203538094,
            'market_value': 561680.8382534103,
            'quantity': 4674
        },
        'EQ:DEF': {
            'unrealised_pnl': 18047.831359406424,
            'realised_pnl': 613.3956570402925,
            'total_pnl': 18661.227016446715,
            'market_value': 376203.80367208034,
            'quantity': 1431.0
        }
    }

    history_df = portfolio.history_to_df().reset_index()
    expected_df = pd.read_csv(os.path.join(FIXTURE_DIR, 'sixty_forty_history.dat'))
    pd.testing.assert_frame_equal(history_df, expected_df)

    portfolio_dict = portfolio.portfolio_to_dict()
    for symbol in expected_dict:
        for metric in expected_dict[symbol]:
            assert portfolio_dict[symbol][metric] == pytest.approx(
                expected_dict[symbol][metric]
            )


def test_a_backtest_starting_before_the_data_fails_loudly(memory_source):
    """
    Checks that a backtest whose start date precedes an asset's first bar
    raises, rather than trading it at a price the backtest cannot yet know.

    Until 0.3.13 the price lookup answered such a query with the final price
    of the series, so this backtest ran to completion on look-ahead and the
    order sizer's guard - whose message names this exact situation - could
    never fire.
    """
    assets = ['EQ:ABC', 'EQ:DEF']
    universe = StaticUniverse(assets)
    data_handler = BacktestDataHandler(universe, data_sources=[memory_source])

    backtest = BacktestTradingSession(
        # The fixture data begins on 2019-01-01
        pd.Timestamp('2018-12-03 00:00:00', tz=pytz.UTC),
        pd.Timestamp('2018-12-31 23:59:00', tz=pytz.UTC),
        universe,
        FixedSignalsAlphaModel({'EQ:ABC': 0.6, 'EQ:DEF': 0.4}),
        portfolio_id='000001',
        rebalance='end_of_month',
        long_only=True,
        cash_buffer_percentage=0.05,
        data_handler=data_handler
    )

    with pytest.raises(ValueError) as excinfo:
        backtest.run(results=False)

    assert 'Not-a-Number' in str(excinfo.value)


def test_a_gap_in_the_bars_is_valued_at_the_last_known_price():
    """
    Checks that the engine values a position through a day with no bar at the
    most recent price before it, rather than at the next one after it.

    This is the only test that drives the padding policy through the engine.
    The other integration tests cannot: the simulation engine emits events at
    14:30 and 21:00 and the bar conversion writes rows at exactly those
    timestamps, so every query they make is an exact index match and the
    policy is never reached. Switching the lookup to 'backfill' - which makes
    every price query in the engine look into the future - leaves all four
    end-to-end tests passing.

    The bars here deliberately jump from 120 to 500 across the gap, so
    padding backwards and filling forwards cannot be confused.
    """
    bars = pd.DataFrame(
        {
            'Open': [100.0, 110.0, 500.0],
            'Close': [110.0, 120.0, 510.0],
        },
        # 2019-01-04 is a Friday, and is missing
        index=pd.to_datetime(['2019-01-02', '2019-01-03', '2019-01-07'])
    )
    source = InMemoryDailyBarDataSource({'EQ:ABC': bars}, adjust_prices=False)

    universe = StaticUniverse(['EQ:ABC'])
    backtest = BacktestTradingSession(
        pd.Timestamp('2019-01-02 14:30:00', tz=pytz.UTC),
        pd.Timestamp('2019-01-07 23:59:00', tz=pytz.UTC),
        universe,
        FixedSignalsAlphaModel({'EQ:ABC': 1.0}),
        portfolio_id='000001',
        rebalance='buy_and_hold',
        long_only=True,
        cash_buffer_percentage=0.01,
        data_handler=BacktestDataHandler(universe, data_sources=[source])
    )
    backtest.run(results=False)

    equity = backtest.get_equity_curve()['Equity']

    # 990,000 of the initial 1,000,000 is invested at the opening price of
    # 100.0, giving 9,900 units and 10,000 of cash
    assert equity.loc[datetime.date(2019, 1, 3)] == pytest.approx(10000.0 + 9900 * 120.0)

    # The gap day pads back to the previous close of 120.0. Filling forwards
    # from the next bar would value it at 500.0, an equity of 4,960,000
    assert equity.loc[datetime.date(2019, 1, 4)] == pytest.approx(10000.0 + 9900 * 120.0)

    assert equity.loc[datetime.date(2019, 1, 7)] == pytest.approx(10000.0 + 9900 * 510.0)
