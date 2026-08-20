import pandas as pd
import pytz

from vmtrader.data.daily_bar import DailyBarDataSource

REQUIRED_COLUMNS = ['Open', 'Close']
ADJUSTED_COLUMN = 'Adj Close'


class InMemoryDailyBarDataSource(DailyBarDataSource):
    """
    A daily 'bar' data source built from Pandas DataFrames supplied
    directly, rather than read from CSV files on disk.

    Useful wherever the bars already exist in memory: a database or web API
    client that has already produced DataFrames, a parameter sweep that would
    otherwise re-read and re-convert the same CSVs for every run, and tests
    that should not depend on files.

    The frames are keyed by VMTrader asset symbol, e.g. 'EQ:SPY', since that
    is what the rest of the system uses. CSVDailyBarDataSource derives those
    keys from its filenames; here the caller states them.

    Parameters
    ----------
    asset_bar_frames : `dict{str: pd.DataFrame}`
        Asset-symbol keyed daily bar DataFrames, indexed by date and
        carrying at least 'Open' and 'Close' columns, plus 'Adj Close'
        if adjust_prices is set. A naive index is taken to be UTC.
    adjust_prices : `Boolean`, optional
        Whether to utilise corporate-action adjusted prices for both
        the open and closing prices. Defaults to True.
    """

    def __init__(self, asset_bar_frames, adjust_prices=True):
        prepared = {
            asset_symbol: self._prepare_bar_frame(
                asset_symbol, bar_df, adjust_prices
            )
            for asset_symbol, bar_df in asset_bar_frames.items()
        }
        super().__init__(prepared, adjust_prices=adjust_prices)

    @staticmethod
    def _prepare_bar_frame(asset_symbol, bar_df, adjust_prices):
        """
        Validate a supplied bar DataFrame and normalise its index to
        sorted, UTC-localised timestamps.

        The validation exists because the caller builds these frames rather
        than the data source reading them from a known format. Without it a
        missing column surfaces much later, as a KeyError raised from inside
        the bar conversion.

        Parameters
        ----------
        asset_symbol : `str`
            The VMTrader asset symbol the frame is for, used in error messages.
        bar_df : `pd.DataFrame`
            The daily bar DataFrame supplied by the caller.
        adjust_prices : `Boolean`
            Whether adjusted prices will be required.

        Returns
        -------
        `pd.DataFrame`
            The validated frame, sorted and localised to UTC.
        """
        if not isinstance(bar_df.index, pd.DatetimeIndex):
            raise ValueError(
                "Bar data for asset '%s' must be indexed by a DatetimeIndex, "
                "not a '%s'." % (asset_symbol, type(bar_df.index).__name__)
            )

        required = list(REQUIRED_COLUMNS)
        if adjust_prices:
            required.append(ADJUSTED_COLUMN)
        missing = [column for column in required if column not in bar_df.columns]
        if missing:
            raise ValueError(
                "Bar data for asset '%s' is missing the required column(s) %s. "
                "Columns present: %s." % (
                    asset_symbol, ', '.join("'%s'" % c for c in missing),
                    ', '.join("'%s'" % c for c in bar_df.columns)
                )
            )

        bar_df = bar_df.sort_index()

        # Mirror the CSV source, which localises a naive index to UTC
        if bar_df.index.tz is None:
            bar_df = bar_df.set_index(bar_df.index.tz_localize(pytz.UTC))
        else:
            bar_df = bar_df.set_index(bar_df.index.tz_convert(pytz.UTC))
        return bar_df
