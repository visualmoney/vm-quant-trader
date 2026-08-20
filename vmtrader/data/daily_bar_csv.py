import os

import pandas as pd
import pytz

from vmtrader import settings
from vmtrader.data.daily_bar import DailyBarDataSource


class CSVDailyBarDataSource(DailyBarDataSource):
    """
    Encapsulates loading, preparation and querying of CSV files of
    daily 'bar' OHLCV data. The CSV files are converted into a intraday
    timestamped Pandas DataFrame with opening and closing prices.

    Optionally utilises adjusted closing prices (if available) to
    adjust both the close and open.

    Parameters
    ----------
    csv_dir : `str`
        The full path to the directory where the CSV is located.
    asset_type : `str`
        The asset type that the price/volume data is for.
        TODO: Unused at this stage and currently hardcoded to Equity.
    adjust_prices : `Boolean`, optional
        Whether to utilise corporate-action adjusted prices for both
        the open and closing prices. Defaults to True.
    csv_symbols : `list`, optional
        An optional list of CSV symbols to restrict the data source to.
        The alternative is to convert all CSVs found within the
        provided directory.
    """

    def __init__(self, csv_dir, asset_type, adjust_prices=True, csv_symbols=None):
        self.csv_dir = csv_dir
        self.asset_type = asset_type
        self.csv_symbols = csv_symbols

        super().__init__(
            self._load_csvs_into_dfs(), adjust_prices=adjust_prices
        )

    def _obtain_asset_csv_files(self):
        """
        Obtain the list of all CSV filenames in the CSV directory.

        Returns
        -------
        `list[str]`
            The list of all CSV filenames.
        """
        return [
            file for file in os.listdir(self.csv_dir)
            if file.endswith('.csv')
        ]

    def _obtain_asset_symbol_from_filename(self, csv_file):
        """
        Return the VMTrader symbology for the asset.

        TODO: Remove hardcoding to Equity asset types.

        Parameters
        ----------
        csv_file : `str`
            The name of the CSV file.

        Returns
        -------
        `str`
            The VMTrader symbology of the asset. e.g. 'EQ:SPY'.
        """
        return 'EQ:%s' % csv_file.replace('.csv', '')

    def _load_csv_into_df(self, csv_file):
        """
        Loads the CSV file into a Pandas DataFrame with dates parsed,
        sorted on datetime localised to UTC.

        Parameters
        ----------
        csv_file : `str`
            The name of the CSV file.

        Returns
        -------
        `pd.DataFrame`
            DataFrame of the CSV file with timestamps localised to UTC.
        """
        csv_df = pd.read_csv(
            os.path.join(self.csv_dir, csv_file),
            index_col='Date',
            parse_dates=True
        ).sort_index()

        # Ensure all timestamps are set to UTC for consistency
        csv_df = csv_df.set_index(csv_df.index.tz_localize(pytz.UTC))
        return csv_df

    def _load_csvs_into_dfs(self):
        """
        Load all CSVs in the CSV directory into Pandas DataFrames.

        Returns
        -------
        `dict{pd.DataFrame}`
            The asset-symbol keyed dictionary of Pandas DataFrames
            containing the timestamped price/volume data.
        """
        if settings.PRINT_EVENTS:
            print("Loading CSV files into DataFrames...")
        if self.csv_symbols is not None:
            # TODO/NOTE: This assumes existence of CSV symbols
            # within the provided directory.
            csv_files = ['%s.csv' % symbol for symbol in self.csv_symbols]
        else:
            csv_files = self._obtain_asset_csv_files()

        asset_frames = {}
        for csv_file in csv_files:
            asset_symbol = self._obtain_asset_symbol_from_filename(csv_file)
            if settings.PRINT_EVENTS:
                print("Loading CSV file for symbol '%s'..." % asset_symbol)
            csv_df = self._load_csv_into_df(csv_file)
            asset_frames[asset_symbol] = csv_df
        return asset_frames
