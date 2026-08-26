"""
Lifecycle events -- the clock-driven moments of a trading day.

They do not all go to the same place. Each is addressed to whichever
actor owns the state its handler touches: 'RebalanceDue' to the
strategy executor, which needs no account state to choose target
weights, and 'PollDue' and 'EndOfDay' to the broker, which owns the
orders, the portfolio and the ledger they read and write.

One event, one addressee. Posting a copy to both mailboxes would make
this an event bus rather than a set of mailboxes, and would let two
actors handle the same moment in no particular order. When another
actor needs to know, the addressee finishes its work and sends a
fresh notification -- past tense by then, because it has happened.

The planes differ only in who produces them: the simulation engine in
a backtest, the session under cron, a scheduler once resident.

See docs/dev/threading-and-event-architecture.md, decision 11.

Where an order event reports what a venue did, these report what the
clock reached, so they are named for what is now due rather than in
the past tense. They share the same base class all the same: one
mailbox should carry one vocabulary, and a consumer that has to know
which of two unrelated hierarchies an item belongs to before it can
read the topic has lost the point of having topics.
"""

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from vmtrader.messaging.trading_events import TradingEvent, TradingEventMessage


@dataclass(frozen=True, slots=True, kw_only=True)
class RebalanceDue(TradingEventMessage):
    """
    Trading is due at this timestamp.

    The handler for this event is where 'qts(dt)' is called -- the
    single confluence point of both planes, unchanged, just reached
    through the mailbox instead of directly.

    Parameters
    ----------
    dt : `pd.Timestamp`
        The time 'now' for the rebalance.
    """

    event_name: ClassVar[str] = TradingEvent.REBALANCE_DUE

    dt: pd.Timestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class EndOfDay(TradingEventMessage):
    """
    The trading day is over; valuation and recording may run.

    Parameters
    ----------
    dt : `pd.Timestamp`
        The time 'now' for the end-of-day pass.
    """

    event_name: ClassVar[str] = TradingEvent.END_OF_DAY

    dt: pd.Timestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class PollDue(TradingEventMessage):
    """
    It is time to ask the venue about the orders still open.

    The counterpart to every other event in this package: those
    arrive because the venue spoke, this one because the engine
    decided to ask. Keeping the pull on the same line as the pushes
    is what stops the two from racing -- a poll's answer and a
    pushed fill for the same order are handled one after the other,
    in the order they were posted, by the one consumer.

    It is a lifecycle event rather than an order event because
    nothing about a venue produced it, and because it names no order:
    a poll asks about whatever is open at the time it is handled, and
    freezing a list of order numbers into the event would mean
    polling for orders that closed while it waited in the queue.

    Under cron one-shot (ADR-0009) nothing posts this -- 'settle'
    runs its own polling loop inside a single rebalance cycle. It
    exists for the resident process, where the interval between polls
    is the scheduler's business rather than a loop's.

    Parameters
    ----------
    dt : `pd.Timestamp`
        The time 'now' for the poll.
    """

    event_name: ClassVar[str] = TradingEvent.POLL_DUE

    dt: pd.Timestamp
