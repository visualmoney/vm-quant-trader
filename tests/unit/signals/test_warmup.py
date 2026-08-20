"""
A live session holds no memory between launches, so its signals start
empty every time. These tests pin what filling them must guarantee.
"""

import numpy as np
import pandas as pd
import pytest

from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.signals.signals_collection import SignalsCollection
from vmtrader.signals.sma import SMASignal
from vmtrader.signals.warmup import required_calendar_days, warm_up_signals


SAMSUNG = 'EQ:005930'
HYNIX = 'EQ:000660'


class FrameHandler:
    """
    A data handler that serves a prepared frame of closes.
    """

    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def get_assets_historical_range_close_price(
        self, start_dt, end_dt, asset_symbols, adjusted=True
    ):
        self.calls.append((start_dt, end_dt, tuple(asset_symbols), adjusted))
        return self.frame

    def get_asset_latest_mid_price(self, dt, asset_symbol):
        return float(self.frame[asset_symbol].iloc[-1])


def _collection(handler, lookbacks=(5,), assets=(SAMSUNG, HYNIX)):
    """
    Build a signals collection over the given assets.
    """
    start = pd.Timestamp('2026-08-20')
    universe = StaticUniverse(list(assets))
    sma = SMASignal(start, universe, list(lookbacks))
    return SignalsCollection({'sma': sma}, handler)


def _frame(days=30, assets=(SAMSUNG, HYNIX)):
    """
    Build a frame of ascending daily closes.
    """
    index = pd.date_range('2026-07-01', periods=days, freq='D')
    return pd.DataFrame(
        dict(
            (asset, np.arange(1, days + 1, dtype=float) * 100.0)
            for asset in assets
        ),
        index=index
    )


def test_buffers_are_filled_to_the_lookback():
    """
    Tests that each asset is warmed with exactly the lookback length.
    """
    handler = FrameHandler(_frame())
    signals = _collection(handler)

    warmed = warm_up_signals(signals, handler, pd.Timestamp('2026-08-20'))

    assert warmed == {SAMSUNG: 5, HYNIX: 5}
    assert len(signals['sma'].buffers.prices['%s_5' % SAMSUNG]) == 5


def test_prices_are_appended_oldest_first():
    """
    Tests the ordering, which decides the answer.

    The buffer is a bounded deque, so warming it in reverse would keep
    the oldest prices and discard the newest -- and a moving average
    over reversed history is a different number.
    """
    handler = FrameHandler(_frame())
    signals = _collection(handler)

    warm_up_signals(signals, handler, pd.Timestamp('2026-08-20'))

    buffer = list(signals['sma'].buffers.prices['%s_5' % SAMSUNG])
    assert buffer == sorted(buffer)
    # The last five closes of the frame, not the first five.
    assert buffer[-1] == 3000.0


def test_a_warmed_signal_matches_the_same_prices_fed_by_hand():
    """
    Tests that warming produces the value a backtest would have.

    A live session primed from history must agree with the same
    strategy run over the same prices in a backtest, or the two planes
    are not comparable.
    """
    frame = _frame()
    warmed_signals = _collection(FrameHandler(frame))
    warm_up_signals(
        warmed_signals, FrameHandler(frame), pd.Timestamp('2026-08-20')
    )

    by_hand = _collection(FrameHandler(frame))
    for price in frame[SAMSUNG].tail(5):
        by_hand['sma'].append(SAMSUNG, float(price))

    assert warmed_signals['sma'](SAMSUNG, 5) == pytest.approx(
        by_hand['sma'](SAMSUNG, 5)
    )


def test_the_request_covers_more_calendar_days_than_the_lookback():
    """
    Tests that the window accounts for weekends and holidays.

    Asking for exactly N calendar days for an N-day lookback would come
    up about thirty per cent short.
    """
    handler = FrameHandler(_frame(days=400))
    signals = _collection(handler, lookbacks=(200,))

    warm_up_signals(signals, handler, pd.Timestamp('2026-08-20'))

    start, end, _, _ = handler.calls[0]
    assert (end - start).days > 200
    assert required_calendar_days(200) > 200


def test_the_longest_lookback_decides_the_window():
    """
    Tests that one request serves every signal, since the venue's rate
    limit is what makes this expensive, not the amount of data.
    """
    handler = FrameHandler(_frame(days=100))
    signals = _collection(handler, lookbacks=(5, 50))

    warm_up_signals(signals, handler, pd.Timestamp('2026-08-20'))

    assert len(handler.calls) == 1
    start, end, _, _ = handler.calls[0]
    assert (end - start).days > 50


def test_adjusted_prices_are_requested():
    """
    Tests that corporate actions are adjusted for.

    An unadjusted split reads to a moving average as a fifty per cent
    crash, which is a trade signal that never happened.
    """
    handler = FrameHandler(_frame())
    signals = _collection(handler)

    warm_up_signals(signals, handler, pd.Timestamp('2026-08-20'))

    assert handler.calls[0][3] is True


def test_an_asset_with_no_history_is_reported_as_zero():
    """
    Tests that a missing column is visible to the caller.

    A signal computed from nothing still returns a number, so the
    caller has to be able to tell that it should not be trusted.
    """
    frame = _frame(assets=(SAMSUNG,))
    handler = FrameHandler(frame)
    signals = _collection(handler)

    warmed = warm_up_signals(signals, handler, pd.Timestamp('2026-08-20'))

    assert warmed[SAMSUNG] == 5
    assert warmed[HYNIX] == 0


def test_gaps_and_bad_prices_are_skipped():
    """
    Tests that missing days and non-positive prices are dropped rather
    than appended, since the buffer refuses a non-positive price.
    """
    frame = _frame()
    frame.loc[frame.index[-2], SAMSUNG] = np.nan
    handler = FrameHandler(frame)
    signals = _collection(handler)

    warmed = warm_up_signals(signals, handler, pd.Timestamp('2026-08-20'))

    assert warmed[SAMSUNG] == 5
    buffer = list(signals['sma'].buffers.prices['%s_5' % SAMSUNG])
    assert all(price > 0.0 for price in buffer)


def test_an_empty_response_warms_nothing_and_says_so():
    """
    Tests that a venue outage reports zero rather than raising, so the
    caller decides whether to trade.
    """
    handler = FrameHandler(pd.DataFrame())
    signals = _collection(handler)

    warmed = warm_up_signals(signals, handler, pd.Timestamp('2026-08-20'))

    assert warmed == {SAMSUNG: 0, HYNIX: 0}
