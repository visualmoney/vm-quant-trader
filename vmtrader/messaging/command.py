"""
Commands -- what the strategy asks the broker to do.

The other direction of the pipeline, and the only one that is not
past tense. An order event reports something a venue already did; a
command reports a decision that has not happened yet and asks the
actor holding the state to carry it out.

They are kept in their own module because 'order.py' opens by
declaring that every event there "reports a fact, it does not request
an action". Putting a request beside them would make that sentence
false, and that sentence is the reason a strategy can trust an event.

The asymmetry is not only grammatical. A lost notification is
recovered by the next poll, but a lost command is a rebalance that
never happened -- which is why the broker's mailbox is consumed by a
non-daemon thread and why posting to a closed one raises rather than
returning quietly.

See docs/dev/threading-and-event-architecture.md, decision 9 and
appendix C.
"""

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from vmtrader.messaging.trading_events import TradingEvent, TradingEventMessage


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetWeights(TradingEventMessage):
    """
    The strategy has chosen its target weights. Size and submit them.

    This is the only value that crosses the actor boundary on the way
    down, and deliberately so. Weights are dimensionless, so producing
    them needs no cash, no holdings and no open orders -- which is
    what lets the strategy run on a thread that owns none of those.
    Everything that does need them, from sizing through submission,
    happens on the side that owns them.

    A per-order command would undo that. It would pull sizing back
    across the boundary, and sizing is the step that reads the cash
    balance.

    Parameters
    ----------
    dt : `pd.Timestamp`
        The time the rebalance is for. Carried rather than read from
        a clock, so that replaying the same command twice produces
        the same orders.
    weights : `tuple[tuple[str, float], ...]`
        Target weight per symbol, sorted by symbol.

        A tuple of pairs rather than a dict, and not for style. A
        frozen dataclass freezes the reference, not the object behind
        it: a dict would stay editable after the message was posted,
        so a producer reusing its working dictionary would change
        what the consumer sees, across a thread boundary, with no
        lock and no warning. That is the shared mutable state the
        mailbox exists to remove. Build it with
        'tuple(sorted(weights.items()))' -- the sort costs nothing and
        makes the order of a message a function of its content.
    """

    event_name: ClassVar[str] = TradingEvent.TARGET_WEIGHTS

    dt: pd.Timestamp
    weights: tuple

    def as_dict(self) -> dict:
        """
        Return the weights as a dictionary for the sizer.

        A fresh dictionary on every call. The consumer is free to
        mutate what it gets back, because what it gets back is not
        the message.

        Returns
        -------
        `dict{str: float}`
            Target weight per symbol.
        """
        return dict(self.weights)
