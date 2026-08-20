from vmtrader.broker.kis.parse import KisParseError


class LiveDataHandler:
    """
    Supplies sizing marks from the venue's current price.

    Implements the same four accessors as BacktestDataHandler, so the
    order sizers and the broker consume it without modification. The
    venue quotes one price rather than a book, so bid, ask and mid are
    all that price: a market order in Korean cash equities crosses the
    spread anyway, and inventing a spread here would make the sizing
    estimate look more precise than it is.

    Prices are cached for the duration of a cycle. A rebalance asks for
    the same symbol several times -- once to size, once to value, once
    to check a limit -- and the venue rate limit is the binding
    constraint on how many times it may be asked.

    Parameters
    ----------
    client : `BrokerClient`
        The venue client. Only 'get_price' is used.
    """

    def __init__(self, client):
        self.client = client
        self._marks = {}

    def clear_cache(self):
        """
        Forget cached prices, so the next request hits the venue.

        Called at the start of a cycle and before marking to market.
        """
        self._marks = {}

    def get_mark(self, asset_symbol):
        """
        Return the current price of an asset, consulting the cache.

        Raises rather than returning zero or NaN when the venue gives
        no usable price: the mark is the sizer's divisor, so a bad one
        must stop the trade for that asset instead of producing a
        nonsensical quantity.

        Parameters
        ----------
        asset_symbol : `str`
            The engine symbol, e.g. 'EQ:005930'.

        Returns
        -------
        `float`
            The current price.
        """
        if asset_symbol in self._marks:
            return self._marks[asset_symbol]

        price = self.client.get_price(asset_symbol)
        if price is None or price <= 0.0:
            raise KisParseError(
                "No usable price for '%s'; refusing to size against it."
                % asset_symbol
            )
        self._marks[asset_symbol] = float(price)
        return self._marks[asset_symbol]

    def get_asset_latest_bid_price(self, dt, asset_symbol):
        """
        Return the latest bid price of an asset.

        Parameters
        ----------
        dt : `pd.Timestamp`
            Unused; present for interface compatibility, since a live
            venue only ever quotes now.
        asset_symbol : `str`
            The engine symbol.

        Returns
        -------
        `float`
            The current price.
        """
        return self.get_mark(asset_symbol)

    def get_asset_latest_ask_price(self, dt, asset_symbol):
        """
        Return the latest ask price of an asset.

        Parameters
        ----------
        dt : `pd.Timestamp`
            Unused; present for interface compatibility.
        asset_symbol : `str`
            The engine symbol.

        Returns
        -------
        `float`
            The current price.
        """
        return self.get_mark(asset_symbol)

    def get_asset_latest_bid_ask_price(self, dt, asset_symbol):
        """
        Return the latest bid/ask pair of an asset.

        Parameters
        ----------
        dt : `pd.Timestamp`
            Unused; present for interface compatibility.
        asset_symbol : `str`
            The engine symbol.

        Returns
        -------
        `tuple[float, float]`
            The current price, twice.
        """
        price = self.get_mark(asset_symbol)
        return (price, price)

    def get_asset_latest_mid_price(self, dt, asset_symbol):
        """
        Return the latest mid price of an asset.

        Parameters
        ----------
        dt : `pd.Timestamp`
            Unused; present for interface compatibility.
        asset_symbol : `str`
            The engine symbol.

        Returns
        -------
        `float`
            The current price.
        """
        return self.get_mark(asset_symbol)
