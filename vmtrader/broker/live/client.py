from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OrderReport:
    """
    The state of a submitted order as the venue reports it.

    The venue reports cumulative totals, not increments: 'filled' is
    everything filled so far for this order number, and a caller that
    polls twice sees the same fill twice. Converting to an increment is
    the caller's job, and is what keeps a fill from being booked into
    the portfolio more than once.

    Parameters
    ----------
    order_no : `str`
        The venue's order number.
    filled_quantity : `int`
        Cumulative quantity filled, always non-negative. The side lives
        on the originating Order, not here.
    average_price : `float`
        Quantity-weighted average fill price. Zero while unfilled.
    remaining_quantity : `int`
        Quantity still open at the venue.
    rejected_quantity : `int`
        Quantity the venue rejected.
    fees : `float`
        Fees as the venue estimates them, or zero if it reports none.
    is_done : `bool`
        Whether the order has reached a terminal state.
    """

    order_no: str
    filled_quantity: int
    average_price: float
    remaining_quantity: int
    rejected_quantity: int
    fees: float
    is_done: bool


@dataclass(frozen=True)
class Holding:
    """
    A single position as the venue reports it.

    Parameters
    ----------
    symbol : `str`
        The engine symbol, e.g. 'EQ:005930'.
    quantity : `int`
        The quantity held.
    average_price : `float`
        The average purchase price.
    """

    symbol: str
    quantity: int
    average_price: float


@dataclass(frozen=True)
class AccountBalance:
    """
    An account snapshot as the venue reports it.

    Cash is the projected figure that accounts for the day's trades,
    not the settled deposit. Korean equities settle at D+2, so the
    settled deposit structurally disagrees with a ledger that deducts
    cash at fill time, and reconciling against it raises a false alarm
    every day.

    Parameters
    ----------
    cash : `float`
        Projected cash, including the day's unsettled trades.
    settled_cash : `float`
        The settled deposit. Informational only; do not reconcile
        against it.
    total_equity : `float`
        Total account valuation as the venue computes it.
    holdings : `tuple[Holding, ...]`
        The positions held.
    """

    cash: float
    settled_cash: float
    total_equity: float
    holdings: tuple


class BrokerClient(Protocol):
    """
    The venue operations the engine needs, stated without reference to
    any SDK.

    The engine depends on this Protocol and never on the vendor library.
    An implementation lives outside the package, in a gateway script,
    which is the only place the KIS SDK is imported. That boundary is
    what lets the entire test suite run with no network and no SDK
    installed.

    Implementations are expected to translate symbols at the boundary:
    the engine speaks 'EQ:005930' and the venue speaks '005930'.

    Attributes
    ----------
    venue : `str`
        Short name of the broker, e.g. 'kis'. Used to label logs and
        to stamp the ledger.
    mode : `str`
        'paper' or 'real'. The engine cannot infer this -- a paper
        account answers the same endpoints with the same shapes --
        so the gateway, which chose the server, must declare it. It
        is what lets a ledger refuse to mix a rehearsal with real
        money, and what lets the promotion check prove it judged a
        paper deployment rather than trusting the file it was given.
    """

    venue: str
    mode: str

    def place_market_order(self, symbol: str, quantity: int) -> str:
        """
        Submit a market order and return the venue's order number.

        Never retried by the engine: the venue's order endpoint is not
        idempotent, so a retry risks a duplicate position.

        Parameters
        ----------
        symbol : `str`
            The engine symbol, e.g. 'EQ:005930'.
        quantity : `int`
            The signed quantity, negative for a sale.

        Returns
        -------
        `str`
            The venue's order number.
        """
        ...

    def get_order_report(self, order_no: str) -> OrderReport:
        """
        Return the current state of a submitted order.

        Parameters
        ----------
        order_no : `str`
            The venue's order number.

        Returns
        -------
        `OrderReport`
            The cumulative state of the order.
        """
        ...

    def get_balance(self) -> AccountBalance:
        """
        Return the account snapshot: cash, valuation and holdings.

        Returns
        -------
        `AccountBalance`
            The account snapshot.
        """
        ...

    def get_price(self, symbol: str) -> float:
        """
        Return the current price of an asset, used as the sizing mark.

        Parameters
        ----------
        symbol : `str`
            The engine symbol, e.g. 'EQ:005930'.

        Returns
        -------
        `float`
            The current price.
        """
        ...

    def get_daily_closes(
        self, symbol: str, start_date: str, end_date: str,
        adjusted: bool = True
    ) -> list:
        """
        Return daily closing prices over a date range.

        Signals need history, and a live process has none: it starts
        with empty rolling buffers every time it launches. This is how
        they are filled.

        Parameters
        ----------
        symbol : `str`
            The engine symbol, e.g. 'EQ:005930'.
        start_date : `str`
            Inclusive start, as 'YYYYMMDD'.
        end_date : `str`
            Inclusive end, as 'YYYYMMDD'.
        adjusted : `bool`, optional
            Whether to adjust for corporate actions. Defaults to true,
            since an unadjusted split looks like a crash to a signal.

        Returns
        -------
        `list[tuple[str, float]]`
            (date, close) pairs, oldest first.
        """
        ...

    def get_trading_day(self, date_str: str) -> bool:
        """
        Return whether the venue opens on the provided date.

        Parameters
        ----------
        date_str : `str`
            The date in 'YYYYMMDD' form.

        Returns
        -------
        `Boolean`
            Whether the venue opens that day.
        """
        ...
