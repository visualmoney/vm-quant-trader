import numpy as np
import pandas as pd
import pytest
import pytz

from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.data.backtest_data_handler import BacktestDataHandler
from vmtrader.data.daily_bar_memory import InMemoryDailyBarDataSource


# Three daily bars carrying a 2:1 split before the final day, so that the
# adjusted and unadjusted paths produce visibly different prices.
#
#   adjusted open = (Adj Close / Close) * Open
#     day 1: (52.5 / 105) * 100 =  50.0
#     day 2: (57.5 / 115) * 110 =  55.0
#     day 3: (125 / 125)  * 120 = 120.0
BARS = pd.DataFrame(
    {
        'Open': [100.0, 110.0, 120.0],
        'Close': [105.0, 115.0, 125.0],
        'Adj Close': [52.5, 57.5, 125.0],
    },
    index=pd.to_datetime(['2020-01-01', '2020-01-02', '2020-01-03'])
)


def _utc(timestamp):
    return pd.Timestamp(timestamp, tz=pytz.UTC)


def test_unadjusted_bars_become_open_and_close_timestamps():
    """
    Checks that each daily bar becomes two rows, the opening price
    timestamped at 14:30 UTC and the closing price at 21:00 UTC.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )

    bid_ask = source.asset_bid_ask_frames['EQ:ABC']

    assert list(bid_ask.index) == [
        _utc('2020-01-01 14:30'), _utc('2020-01-01 21:00'),
        _utc('2020-01-02 14:30'), _utc('2020-01-02 21:00'),
        _utc('2020-01-03 14:30'), _utc('2020-01-03 21:00'),
    ]
    assert list(bid_ask['Bid']) == pytest.approx(
        [100.0, 105.0, 110.0, 115.0, 120.0, 125.0]
    )

    # No bid/ask spread is modelled, so the two are always equal
    assert list(bid_ask['Ask']) == list(bid_ask['Bid'])


def test_adjusted_bars_scale_the_open_by_the_close_ratio():
    """
    Checks that the opening price is adjusted by the same factor as the
    close, rather than being left at its unadjusted value.
    """
    source = InMemoryDailyBarDataSource({'EQ:ABC': BARS})

    bid_ask = source.asset_bid_ask_frames['EQ:ABC']

    assert list(bid_ask['Bid']) == pytest.approx(
        [50.0, 52.5, 55.0, 57.5, 120.0, 125.0]
    )


@pytest.mark.parametrize(
    'timestamp,expected',
    [
        ('2020-01-01 14:30', 100.0),   # exactly the opening timestamp
        ('2020-01-01 18:00', 100.0),   # mid-session, pads back to the open
        ('2020-01-01 21:00', 105.0),   # exactly the closing timestamp
        ('2020-01-02 09:00', 105.0),   # overnight, pads back to the close
        ('2020-01-03 21:00', 125.0),   # the final bar
    ]
)
def test_prices_pad_backwards_to_the_last_known_timestamp(timestamp, expected):
    """
    Checks that a query between two timestamps returns the most recent
    price at or before it, rather than interpolating or returning NaN.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )

    assert source.get_bid(_utc(timestamp), 'EQ:ABC') == pytest.approx(expected)
    assert source.get_ask(_utc(timestamp), 'EQ:ABC') == pytest.approx(expected)


def test_price_before_the_first_bar_is_nan():
    """
    Checks that a timestamp earlier than the first bar has no price.

    Until 0.3.13 it returned the LAST price of the series, because
    'index.get_indexer(..., method="pad")' returns -1 when nothing precedes
    the timestamp and iloc takes -1 as the final row. A backtest starting
    before an asset's data began therefore valued and traded that asset at a
    price from the end of the sample.

    The NaN matters beyond correctness: both order sizers raise on a NaN
    price with a message naming this exact situation, and that guard could
    not fire while the lookup answered with a number.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )

    assert np.isnan(source.get_bid(_utc('2019-06-01'), 'EQ:ABC'))
    assert np.isnan(source.get_ask(_utc('2019-06-01'), 'EQ:ABC'))

    # An unknown asset raises instead, which the data handler turns into NaN
    with pytest.raises(KeyError):
        source.get_bid(_utc('2020-01-02 14:30'), 'EQ:NOPE')


def test_price_after_the_final_bar_returns_the_final_price():
    """
    Checks that a timestamp beyond the data pads forward from the last
    bar, which is the intended behaviour for a stale price.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )

    assert source.get_bid(_utc('2021-01-01'), 'EQ:ABC') == pytest.approx(125.0)


def test_naive_index_is_localised_to_utc():
    """
    Checks that a naive DatetimeIndex is treated as UTC, matching what
    CSVDailyBarDataSource does with the dates it parses.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )

    assert source.asset_bar_frames['EQ:ABC'].index.tz == pytz.UTC


def test_tz_aware_index_is_converted_to_utc():
    """
    Checks that a frame indexed in another timezone is converted rather
    than rejected, so that the bar timestamps stay comparable.
    """
    eastern = BARS.copy()
    # pytz carries its own tz database, so this does not depend on the
    # host having a system zoneinfo installation
    eastern.index = eastern.index.tz_localize(pytz.timezone('US/Eastern'))

    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': eastern}, adjust_prices=False
    )

    index = source.asset_bar_frames['EQ:ABC'].index
    assert index.tz == pytz.UTC
    assert index[0] == _utc('2020-01-01 05:00')


def test_bars_are_sorted_by_timestamp():
    """
    Checks that out-of-order input is sorted, since the padded lookup
    depends on a monotonic index.
    """
    shuffled = BARS.iloc[[2, 0, 1]]

    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': shuffled}, adjust_prices=False
    )

    assert source.asset_bar_frames['EQ:ABC'].index.is_monotonic_increasing
    assert source.get_bid(_utc('2020-01-01 14:30'), 'EQ:ABC') == pytest.approx(100.0)


@pytest.mark.parametrize(
    'dropped,adjust_prices',
    [
        ('Open', False),
        ('Close', False),
        ('Adj Close', True),
    ]
)
def test_missing_required_column_raises(dropped, adjust_prices):
    """
    Checks that a missing column is reported at construction, naming the
    asset and the column, rather than surfacing later as a KeyError from
    inside the bar conversion.
    """
    incomplete = BARS.drop(columns=[dropped])

    with pytest.raises(ValueError) as excinfo:
        InMemoryDailyBarDataSource(
            {'EQ:ABC': incomplete}, adjust_prices=adjust_prices
        )

    assert 'EQ:ABC' in str(excinfo.value)
    assert dropped in str(excinfo.value)


def test_non_datetime_index_raises():
    """
    Checks that a frame indexed by anything other than timestamps is
    rejected at construction.
    """
    bad = BARS.reset_index(drop=True)

    with pytest.raises(ValueError) as excinfo:
        InMemoryDailyBarDataSource({'EQ:ABC': bad}, adjust_prices=False)

    assert 'DatetimeIndex' in str(excinfo.value)


@pytest.mark.parametrize(
    'adjusted,expected',
    [
        (False, [105.0, 115.0, 125.0]),
        (True, [52.5, 57.5, 125.0]),
    ]
)
def test_get_assets_historical_closes(adjusted, expected):
    """
    Checks the multi-asset range query, including that the 'adjusted'
    flag selects the adjusted column.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )

    closes = source.get_assets_historical_closes(
        _utc('2020-01-01'), _utc('2020-01-03'), ['EQ:ABC'], adjusted=adjusted
    )

    assert list(closes.columns) == ['EQ:ABC']
    assert list(closes['EQ:ABC']) == pytest.approx(expected)


def test_get_assets_historical_closes_omits_unknown_assets():
    """
    Checks that an asset the source does not carry is left out of the
    columns rather than returned as a column of NaN.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )

    closes = source.get_assets_historical_closes(
        _utc('2020-01-01'), _utc('2020-01-03'), ['EQ:ABC', 'EQ:NOPE']
    )

    assert list(closes.columns) == ['EQ:ABC']


def test_get_assets_historical_closes_restricts_to_the_range():
    """
    Checks that the returned frame is bounded by the requested dates.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )

    closes = source.get_assets_historical_closes(
        _utc('2020-01-02'), _utc('2020-01-02'), ['EQ:ABC']
    )

    assert list(closes['EQ:ABC']) == pytest.approx([115.0])


def test_adjusting_without_an_adjusted_close_column_is_rejected():
    """
    Checks that requesting adjusted prices for bars that carry no
    'Adj Close' column fails loudly.
    """
    with pytest.raises(ValueError):
        InMemoryDailyBarDataSource(
            {'EQ:ABC': BARS.drop(columns=['Adj Close'])}, adjust_prices=True
        )


def test_multiple_assets_are_converted_independently():
    """
    Checks that each asset keeps its own bid/ask frame.
    """
    other = BARS * 2.0

    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS, 'EQ:DEF': other}, adjust_prices=False
    )

    assert set(source.asset_bid_ask_frames) == {'EQ:ABC', 'EQ:DEF'}
    assert source.get_bid(_utc('2020-01-01 14:30'), 'EQ:ABC') == pytest.approx(100.0)
    assert source.get_bid(_utc('2020-01-01 14:30'), 'EQ:DEF') == pytest.approx(200.0)


def test_unknown_asset_becomes_a_nan_price_through_the_data_handler():
    """
    Checks the contract the source has with BacktestDataHandler: the source
    may raise for an asset it does not carry, because the handler catches it
    and substitutes NaN before any caller sees it.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS}, adjust_prices=False
    )
    handler = BacktestDataHandler(
        StaticUniverse(['EQ:ABC']), data_sources=[source]
    )

    with pytest.raises(KeyError):
        source.get_ask(_utc('2020-01-01 14:30'), 'EQ:XYZ')

    assert np.isnan(
        handler.get_asset_latest_ask_price(_utc('2020-01-01 14:30'), 'EQ:XYZ')
    )


def test_historical_closes_reject_an_adjusted_request_without_the_column():
    """
    Checks that asking for adjusted closes from bars that carry no
    'Adj Close' column is reported rather than falling back silently
    to unadjusted prices.
    """
    source = InMemoryDailyBarDataSource(
        {'EQ:ABC': BARS.drop(columns=['Adj Close'])}, adjust_prices=False
    )

    with pytest.raises(ValueError) as excinfo:
        source.get_assets_historical_closes(
            _utc('2020-01-01'), _utc('2020-01-03'), ['EQ:ABC'], adjusted=True
        )

    assert 'Adj Close' in str(excinfo.value)
    assert 'EQ:ABC' in str(excinfo.value)
