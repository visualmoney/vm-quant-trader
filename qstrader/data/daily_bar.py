import functools

import numpy as np
import pandas as pd

from qstrader import settings
from qstrader.data.data_source import DataSource


class DailyBarDataSource(DataSource):
    """
    Base class for data sources backed by daily OHLCV 'bar' data.

    Holds everything that is independent of where the bars came from: the
    conversion of each daily bar into separately timestamped opening and
    closing prices, and the point-in-time and range queries over the result.
    Subclasses are responsible only for producing the bar DataFrames.

    Each bar DataFrame must be indexed by a UTC-localised DatetimeIndex and
    carry 'Open' and 'Close' columns, plus 'Adj Close' when adjust_prices
    is set.

    Parameters
    ----------
    asset_bar_frames : `dict{str: pd.DataFrame}`
        The asset-symbol keyed dictionary of daily bar DataFrames.
    adjust_prices : `Boolean`, optional
        Whether to utilise corporate-action adjusted prices for both
        the open and closing prices. Defaults to True.
    """

    def __init__(self, asset_bar_frames, adjust_prices=True):
        self.adjust_prices = adjust_prices
        self.asset_bar_frames = asset_bar_frames
        self.asset_bid_ask_frames = self._convert_bars_into_bid_ask_dfs()

    def _convert_bar_frame_into_bid_ask_df(self, bar_df):
        """
        Converts the DataFrame from daily OHLCV 'bars' into a DataFrame
        of open and closing price timestamps.

        Optionally adjusts the open/close prices for corporate actions
        using any provided 'Adjusted Close' column.

        Parameters
        ----------
        bar_df : `pd.DataFrame`
            The daily 'bar' OHLCV DataFrame.

        Returns
        -------
        `pd.DataFrame`
            The individually-timestamped open/closing prices, optionally
            adjusted for corporate actions.
        """
        bar_df = bar_df.sort_index()
        if self.adjust_prices:
            if 'Adj Close' not in bar_df.columns:
                raise ValueError(
                    "Unable to locate Adjusted Close pricing column in the bar data. "
                    "Prices cannot be adjusted. Exiting."
                )

            # Restrict solely to the open/closing prices
            oc_df = bar_df.loc[:, ['Open', 'Close', 'Adj Close']]

            # Adjust opening prices
            oc_df['Adj Open'] = (oc_df['Adj Close'] / oc_df['Close']) * oc_df['Open']
            oc_df = oc_df.loc[:, ['Adj Open', 'Adj Close']]
            oc_df.columns = ['Open', 'Close']
        else:
            oc_df = bar_df.loc[:, ['Open', 'Close']]

        # Convert bars into separate rows for open/close prices
        # appropriately timestamped
        seq_oc_df = oc_df.T.unstack(level=0).reset_index()
        seq_oc_df.columns = ['Date', 'Market', 'Price']
        seq_oc_df.loc[seq_oc_df['Market'] == 'Open', 'Date'] += pd.Timedelta(hours=14, minutes=30)
        seq_oc_df.loc[seq_oc_df['Market'] == 'Close', 'Date'] += pd.Timedelta(hours=21, minutes=00)

        # TODO: Unable to distinguish between Bid/Ask, implement later
        dp_df = seq_oc_df[['Date', 'Price']]
        dp_df['Bid'] = dp_df['Price']
        dp_df['Ask'] = dp_df['Price']
        dp_df = dp_df.loc[:, ['Date', 'Bid', 'Ask']].ffill().set_index('Date').sort_index()
        return dp_df

    def _convert_bars_into_bid_ask_dfs(self):
        """
        Convert all of the daily OHLCV 'bar' based DataFrames into
        individually-timestamped open/closing price DataFrames.

        Returns
        -------
        `dict{pd.DataFrame}`
            The converted DataFrames.
        """
        if settings.PRINT_EVENTS:
            print("Adjusting pricing in bar data...")
        asset_bid_ask_frames = {}
        for asset_symbol, bar_df in self.asset_bar_frames.items():
            if settings.PRINT_EVENTS:
                print("Adjusting bar data for symbol '%s'..." % asset_symbol)
            asset_bid_ask_frames[asset_symbol] = \
                self._convert_bar_frame_into_bid_ask_df(bar_df)
        return asset_bid_ask_frames

    @functools.lru_cache(maxsize=1024 * 1024)
    def get_bid(self, dt, asset):
        """
        Obtain the bid price of an asset at the provided timestamp.

        Parameters
        ----------
        dt : `pd.Timestamp`
            When to obtain the bid price for.
        asset : `str`
            The asset symbol to obtain the bid price for.

        Returns
        -------
        `float`
            The bid price.
        """
        bid_ask_df = self.asset_bid_ask_frames[asset]

        # 'pad' returns -1 when no row precedes the timestamp. Passing that to
        # iloc would select the final row, so the query would answer with a
        # price from the end of the series
        index = bid_ask_df.index.get_indexer([dt], method='pad')[0]
        if index < 0:  # Before the first bar
            return np.nan
        return bid_ask_df['Bid'].iloc[index]

    @functools.lru_cache(maxsize=1024 * 1024)
    def get_ask(self, dt, asset):
        """
        Obtain the ask price of an asset at the provided timestamp.

        Parameters
        ----------
        dt : `pd.Timestamp`
            When to obtain the ask price for.
        asset : `str`
            The asset symbol to obtain the ask price for.

        Returns
        -------
        `float`
            The ask price.
        """
        bid_ask_df = self.asset_bid_ask_frames[asset]

        # 'pad' returns -1 when no row precedes the timestamp. Passing that to
        # iloc would select the final row, so the query would answer with a
        # price from the end of the series
        index = bid_ask_df.index.get_indexer([dt], method='pad')[0]
        if index < 0:  # Before the first bar
            return np.nan
        return bid_ask_df['Ask'].iloc[index]

    def get_assets_historical_closes(self, start_dt, end_dt, assets, adjusted=False):
        """
        Obtain a multi-asset historical range of closing prices as a DataFrame,
        indexed by timestamp with asset symbols as columns.

        Parameters
        ----------
        start_dt : `pd.Timestamp`
            The starting datetime of the range to obtain.
        end_dt : `pd.Timestamp`
            The ending datetime of the range to obtain.
        assets : `list[str]`
            The list of asset symbols to obtain closing prices for.
        adjusted : `Boolean`, optional
            Whether to return corporate-action adjusted closing prices.
            Defaults to unadjusted.

        Returns
        -------
        `pd.DataFrame`
            The multi-asset closing prices DataFrame.
        """
        close_column = 'Adj Close' if adjusted else 'Close'

        close_series = []
        for asset in assets:
            if asset in self.asset_bar_frames.keys():
                bar_df = self.asset_bar_frames[asset]
                if close_column not in bar_df.columns:
                    raise ValueError(
                        "Unable to locate '%s' pricing column for asset '%s'. "
                        "Closing prices cannot be returned." % (close_column, asset)
                    )
                asset_close_prices = bar_df[[close_column]]
                asset_close_prices.columns = [asset]
                close_series.append(asset_close_prices)

        prices_df = pd.concat(close_series, axis=1).dropna(how='all')
        prices_df = prices_df.loc[start_dt:end_dt]
        return prices_df
