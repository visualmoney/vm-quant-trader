"""
Order events -- notifications that something already happened at the
venue.

Every event is past tense and immutable: it reports a fact, it does
not request an action. A strategy that wants to act on one sends a
new order through the broker's API; it never reaches into broker
state, which is what keeps the accounting single-writer.

Every event carries the venue's order number as its correlation id.
A stack trace dies at the queue boundary, so the order number is the
only thread that ties a strategy callback back to the submission that
caused it -- and, through the ledger's idempotency key
('order_no:cumulative_filled'), to the durable record of the fill.

Two of them carry a second id as well, for the two cases where the
venue's number alone is not enough to follow the trail. An amendment
or a cancellation is given a *new* order number, so those events also
name the 'original_order_no' they act on; and an error may happen
before any number was assigned, so 'OrderError' leans on the engine's
own 'order_id', which exists from the moment the intent is written.

What is here is what a KRX cash-equity venue actually reports. KIS
sends acceptance, amendment, cancellation, rejection and fill down
one channel, and nothing else: there is no assignment, exercise or
expiry, because those are derivatives events and this engine trades
cash equities.
"""

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from vmtrader.messaging.trading_events import TradingEvent, TradingEventMessage


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderAccepted(TradingEventMessage):
    """
    The venue took an order and gave it a number.

    Named for what the venue did rather than for what the engine did.
    The ledger already has a SUBMITTED state standing for our side of
    this same moment, and an event type sharing a name with a ledger
    state is the exact debt decision 7 exists to avoid: once the two
    are one word, neither vocabulary can move alone.

    This is the first event that can carry an order number, so it is
    where a strategy learns the correlation id that every later fill
    or rejection for this order will repeat.

    Parameters
    ----------
    order_no : `str`
        The venue's order number. The correlation id.
    order_id : `str`
        The engine's own id for the intent, written to the ledger
        before the venue was called. The other half of the trail: it
        is what ties this order back to the rebalance that wanted it.
    symbol : `str`
        The engine symbol, e.g. 'EQ:005930'.
    quantity : `int`
        The signed quantity actually sent, after clamping. Buys
        positive, sells negative, as everywhere else in the engine.
        Not necessarily the quantity the sizer asked for.
    dt : `pd.Timestamp`
        The engine time at which the venue accepted the order.
    """

    event_name: ClassVar[str] = TradingEvent.ACCEPTED_ORDER

    order_no: str
    order_id: str
    symbol: str
    quantity: int
    dt: pd.Timestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderModified(TradingEventMessage):
    """
    The venue accepted an amendment to an order still working.

    An amendment is not an edit in place. KRX answers one with a fresh
    order number and leaves the old one closed, so the correlation
    chain forks here: everything that happens from now on is reported
    under 'order_no', while 'original_order_no' is the only way back
    to the submission the strategy already knows about. A consumer
    that tracks orders by number and ignores the second field will
    quietly grow an entry that never completes and lose sight of one
    that did.

    Quantity already filled under the original number stays filled.
    An amendment can only change what is still working, so this event
    never implies that a booked fill was undone.

    Parameters
    ----------
    order_no : `str`
        The venue's *new* order number for the amended order. The
        correlation id every later event about it will carry.
    original_order_no : `str`
        The order number this amendment replaces.
    order_id : `str`
        The engine's id for the intent, unchanged by the amendment.
        It is what still ties both numbers to one rebalance.
    symbol : `str`
        The engine symbol, e.g. 'EQ:005930'.
    quantity : `int`
        The signed quantity now working, after the amendment. Buys
        positive, sells negative.
    dt : `pd.Timestamp`
        The engine time at which the venue accepted the amendment.
    """

    event_name: ClassVar[str] = TradingEvent.MODIFIED_ORDER

    order_no: str
    original_order_no: str
    order_id: str
    symbol: str
    quantity: int
    dt: pd.Timestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCanceled(TradingEventMessage):
    """
    The venue accepted a cancellation and stopped working an order.

    Cancellation reaches only the unfilled remainder. Anything already
    filled was already booked and stays booked, which is why this
    event names the quantity withdrawn rather than the quantity
    ordered: the two differ by exactly what filled before the
    cancellation landed, and a consumer that reads it as "the order
    never happened" would double back over real transactions.

    Like an amendment, a cancellation is given its own order number by
    the venue, so it too carries the original.

    Nothing in the engine currently sends one. It is defined now
    because the venue can report a cancellation the engine did not
    ask for -- an operator acting in the vendor's own app, or the
    venue withdrawing an order at the close -- and reconciliation
    should have a name for that fact rather than discovering it as an
    unexplained quantity difference.

    Parameters
    ----------
    order_no : `str`
        The venue's order number for the cancellation itself.
    original_order_no : `str`
        The order number that stopped working.
    order_id : `str`
        The engine's id for the intent behind the original order.
    symbol : `str`
        The engine symbol, e.g. 'EQ:005930'.
    quantity : `int`
        The signed quantity withdrawn -- the unfilled remainder, not
        the original order size.
    dt : `pd.Timestamp`
        The engine time at which the venue accepted the cancellation.
    """

    event_name: ClassVar[str] = TradingEvent.CANCELED_ORDER

    order_no: str
    original_order_no: str
    order_id: str
    symbol: str
    quantity: int
    dt: pd.Timestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderFilled(TradingEventMessage):
    """
    An increment of an order filled and booked.

    The venue reports cumulative totals, so the broker converts to an
    increment before booking and before publishing this event: two
    polls that see the same fill produce one event. 'quantity' is the
    increment; 'cumulative_filled' is the venue's running total after
    it, which is the second half of the ledger's idempotency key.

    Only the quantity is an increment. Price and cost are not, and
    are named so that no reader has to guess: the venue reports one
    running average and one estimated total per order, never a
    per-increment breakdown, and this event does not invent one.
    A consumer wanting the cost of a single increment must take the
    difference between successive events and accept that it is
    differencing an estimate.

    Parameters
    ----------
    order_no : `str`
        The venue's order number. The correlation id.
    symbol : `str`
        The engine symbol, e.g. 'EQ:005930'.
    quantity : `int`
        The increment just booked. Signed: buys positive, sells
        negative, as everywhere else in the engine. The only
        incremental field here.
    cumulative_filled : `int`
        The venue's cumulative filled quantity after this increment.
        Always non-negative.
    average_price : `float`
        Quantity-weighted average fill price of the whole order so
        far, as the venue reports it.
    cumulative_fees : `float`
        Commission and taxes for the whole order so far, as the venue
        estimates them. An estimate, not a settled figure -- KIS
        reports 'prsm_tlex_smtl', 예상 제비용 합계 -- so it may move
        between polls even when nothing else did. Zero when the venue
        reports none.
    dt : `pd.Timestamp`
        The engine time at which the increment was booked.
    """

    event_name: ClassVar[str] = TradingEvent.FILLED_ORDER

    order_no: str
    symbol: str
    quantity: int
    cumulative_filled: int
    average_price: float
    cumulative_fees: float
    dt: pd.Timestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderRejected(TradingEventMessage):
    """
    The venue refused an order.

    Published so a strategy can react; the loud half of the failure
    already happened -- the ledger row is REJECTED and the log line is
    written before this event is posted. The event is a notification,
    not the record.

    A rejection is a verdict: the venue looked at the order and said
    no, so the engine knows with certainty that no position was taken.
    That certainty is the whole difference from 'OrderError', and the
    reason the two are separate types rather than one with a flag.

    Parameters
    ----------
    order_no : `str`
        The venue's order number, or the engine's intent id when the
        rejection preceded an order number being assigned.
    symbol : `str`
        The engine symbol.
    quantity : `int`
        The signed quantity that was refused.
    reason : `str`
        The venue's stated reason, verbatim. Empty if it gave none.
    dt : `pd.Timestamp`
        The engine time at which the rejection was recorded.
    """

    event_name: ClassVar[str] = TradingEvent.REJECTED_ORDER

    order_no: str
    symbol: str
    quantity: int
    reason: str
    dt: pd.Timestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderError(TradingEventMessage):
    """
    The engine could not complete an exchange with the venue.

    This is the absence of an answer, not a bad one. A timeout, a
    dropped connection, a response that would not parse: in every case
    the request may have been carried out, and the engine has no way
    to tell. An order sent into a socket that then went quiet either
    reached the exchange or did not, and the difference is a position.

    That is why this is not a rejection. 'OrderRejected' means the
    venue decided; this means nobody knows yet. Today the broker
    records both as REJECTED in the ledger, which reads a maybe-open
    order as certainly refused -- the gap this type exists to close.

    Two rules follow from the uncertainty and neither is optional.
    The engine does not retry, because the venue's order endpoint is
    not idempotent and a retry against an order that did land buys a
    duplicate position. And nothing is booked, because booking
    requires knowing; the next launch's 'reconcile()' compares the
    engine's view against the venue's holdings and settles what
    actually happened. The recovery path is the ordinary startup path
    (ADR-0009), which is what makes leaving this unresolved safe.

    Parameters
    ----------
    order_id : `str`
        The engine's id for the intent. Listed first because it is
        the only id guaranteed to exist: it is written to the ledger
        before the venue is called, which is precisely so that a call
        that dies mid-flight still leaves a name for what was
        attempted.
    order_no : `str`
        The venue's order number, or an empty string when the failure
        came before one was assigned -- the common case, since the
        number arrives in the very response that went missing.
    symbol : `str`
        The engine symbol, e.g. 'EQ:005930'.
    quantity : `int`
        The signed quantity that was attempted.
    reason : `str`
        What went wrong, as the exception described it. Operator
        text: nothing branches on it.
    dt : `pd.Timestamp`
        The engine time at which the failure was recorded.
    """

    event_name: ClassVar[str] = TradingEvent.ERROR_ORDER

    order_id: str
    order_no: str
    symbol: str
    quantity: int
    reason: str
    dt: pd.Timestamp
