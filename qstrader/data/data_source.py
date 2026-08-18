from abc import ABC, abstractmethod


class DataSource(ABC):
    """
    Interface to a source of asset pricing data.

    A DataSource answers point-in-time price queries for a single asset and
    range queries for many assets at once. BacktestDataHandler holds a list of
    them and asks each in turn until one produces a price, so every subclass
    must be safe to query for an asset it does not carry.

    The contract below is the one BacktestDataHandler relies upon:

    * Symbols are QSTrader asset symbols, such as 'EQ:SPY', not bare tickers.
    * Timestamps are timezone-aware and in UTC.
    * A price that cannot be determined is returned as NaN rather than raised,
      since the handler treats an exception and a NaN identically.
    """

    @abstractmethod
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
            The bid price, or NaN if none is available at this timestamp.
        """
        raise NotImplementedError(
            "Should implement get_bid()"
        )

    @abstractmethod
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
            The ask price, or NaN if none is available at this timestamp.
        """
        raise NotImplementedError(
            "Should implement get_ask()"
        )

    @abstractmethod
    def get_assets_historical_closes(self, start_dt, end_dt, assets, adjusted=False):
        """
        Obtain a multi-asset historical range of closing prices as a DataFrame,
        indexed by timestamp with asset symbols as columns.

        Assets the source does not carry are omitted from the columns rather
        than returned as an all-NaN column.

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
        raise NotImplementedError(
            "Should implement get_assets_historical_closes()"
        )
