from vmtrader.broker.live.errors import PriceUnavailable


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

    **One of these belongs to one actor.** Nothing here is guarded, and
    the cache is cleared wholesale at the start of a cycle and before
    marking, so a second actor reading it mid-decision re-fetches
    everything it had already paid for. Worse than the duplication is
    where the duplicate goes: the gateway's throttle holds a
    module-level lock across its sleep, so two actors asking for prices
    contend for the same lock that order submission needs -- and a slow
    strategy delays the orders, which is the one thing the two-actor
    split exists to prevent.

    The design's answer is that the strategy actor does not hold one of
    these at all: it is given a price snapshot taken before the
    rebalance, the same way ADR-0006 has the sizer work from a single
    snapshot. Until that lands, sharing one instance across both actors
    is safe only because Phase 0 runs on one thread.

    See docs/dev/threading-and-event-architecture.md §3's ownership
    table and report 20260826-01, M3.

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
            raise PriceUnavailable(
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

    def get_assets_historical_range_close_price(
        self, start_dt, end_dt, asset_symbols, adjusted=True
    ):
        """
        Return daily closes for several assets over a range.

        Deliberately the same method name and shape that
        BacktestDataHandler exposes, so anything that warms a signal
        works identically against either plane. A live session that
        primed its buffers from a different source than the backtest
        would produce different signals from the same strategy, which
        is the whole thing this integration exists to avoid.

        Corporate actions are adjusted for by default. An unadjusted
        split reads to a moving average as a fifty per cent crash.

        Parameters
        ----------
        start_dt : `pd.Timestamp`
            Inclusive start of the range.
        end_dt : `pd.Timestamp`
            Inclusive end of the range.
        asset_symbols : `list[str]`
            The engine symbols to fetch.
        adjusted : `Boolean`, optional
            Whether to adjust for corporate actions.

        Returns
        -------
        `pd.DataFrame`
            Closes indexed by date, one column per asset. Assets the
            venue will not price are omitted rather than returned as
            an all-empty column.
        """
        import pandas as pd

        start = pd.Timestamp(start_dt).strftime('%Y%m%d')
        end = pd.Timestamp(end_dt).strftime('%Y%m%d')

        series = {}
        for symbol in asset_symbols:
            try:
                closes = self.client.get_daily_closes(
                    symbol, start, end, adjusted=adjusted
                )
            except Exception:
                # A symbol the venue will not chart is left out. The
                # caller sees a missing column, which is honest, rather
                # than a column of zeros, which is not.
                continue
            if not closes:
                continue
            series[symbol] = pd.Series(
                dict(
                    (pd.Timestamp(date), close) for date, close in closes
                )
            )

        if not series:
            return pd.DataFrame()
        return pd.DataFrame(series).sort_index()

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
