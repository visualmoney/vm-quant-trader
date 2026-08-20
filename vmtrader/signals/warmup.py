"""
Fill a signal's rolling buffers before it is asked for a value.

A backtest never needs this: it starts at the beginning of history and
the buffers fill as it runs. A live session does, because it holds no
memory between launches -- under a cron one-shot model every launch
starts with empty buffers, so without a warm-up a moving average would
be computed from a single day's price, every day, forever.

The prices come through the data handler's historical accessor, which
both planes implement with the same signature. Warming a live session
from a different source than the backtest used would give the same
strategy different signals, which is precisely what this integration
exists to avoid.
"""

import numpy as np
import pandas as pd


# Weekends and holidays mean roughly five trading days a week, and
# some names miss a session. Asking for a wider window than the
# lookback needs is cheap; coming up short is not.
CALENDAR_DAYS_PER_TRADING_DAY = 1.75
EXTRA_CALENDAR_DAYS = 10


def required_calendar_days(lookback):
    """
    Return how many calendar days to request for a lookback.

    Parameters
    ----------
    lookback : `int`
        The number of trading days the signal needs.

    Returns
    -------
    `int`
        Calendar days to request.
    """
    return int(lookback * CALENDAR_DAYS_PER_TRADING_DAY) + EXTRA_CALENDAR_DAYS


def warm_up_signals(signals, data_handler, end_dt, adjusted=True):
    """
    Prime every signal in a collection from historical closes.

    One request covers every asset and the longest lookback in the
    collection, because the venue's rate limit -- not the amount of
    data -- is what makes this expensive.

    Prices are appended oldest first, since the buffers are ordered
    deques and a signal computed over reversed history is not the same
    number.

    Parameters
    ----------
    signals : `SignalsCollection`
        The signals to warm.
    data_handler : `DataHandler`
        Supplies 'get_assets_historical_range_close_price'.
    end_dt : `pd.Timestamp`
        The last date to include, normally today.
    adjusted : `Boolean`, optional
        Whether to request corporate-action adjusted closes.

    Returns
    -------
    `dict{str: int}`
        How many prices each asset was warmed with, so a caller can
        tell a full warm-up from a partial one.
    """
    assets = sorted(
        set(
            asset
            for signal in signals.signals.values()
            for asset in signal.assets
        )
    )
    if not assets:
        return {}

    lookback = max(
        (
            max(signal.lookbacks)
            for signal in signals.signals.values()
            if signal.lookbacks
        ),
        default=0
    )
    if lookback <= 0:
        return {}

    end = pd.Timestamp(end_dt)
    start = end - pd.Timedelta(days=required_calendar_days(lookback))

    closes = data_handler.get_assets_historical_range_close_price(
        start, end, assets, adjusted=adjusted
    )
    if closes is None or closes.empty:
        return dict((asset, 0) for asset in assets)

    warmed = {}
    for asset in assets:
        if asset not in closes.columns:
            warmed[asset] = 0
            continue
        prices = closes[asset].dropna().tail(lookback)
        count = 0
        for price in prices:
            if price is None or not np.isfinite(price) or price <= 0.0:
                continue
            for signal in signals.signals.values():
                if asset in signal.assets:
                    signal.append(asset, float(price))
            count += 1
        warmed[asset] = count

    signals.warmup += min(warmed.values(), default=0)
    return warmed
