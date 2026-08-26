"""
Canonical trading-event vocabulary and the single-consumer machinery
that delivers it.

Both actors of the event pipeline meet here: the broker (which
produces order events) and the strategy executor (which consumes
them). Neither side owns the vocabulary, so it lives in neither
package -- this one is a leaf, importing nothing from the rest of
the engine, which is what keeps broker and alpha_model free of each
other. tests/unit/messaging/test_leaf_boundary.py asserts that.

Event types are not order states. The ledger's state strings answer
"where is this order now"; an event answers "what just happened".
Keeping them as separate types is what lets either vocabulary change
without dragging the other along.

See docs/dev/threading-and-event-architecture.md, decisions 7 and 8.
"""

from vmtrader.messaging.command import TargetWeights
from vmtrader.messaging.lifecycle import EndOfDay, PollDue, RebalanceDue
from vmtrader.messaging.mailbox import Mailbox, MailboxClosed
from vmtrader.messaging.order import (
    OrderAccepted,
    OrderCanceled,
    OrderError,
    OrderFilled,
    OrderModified,
    OrderRejected,
)
from vmtrader.messaging.trading_events import TradingEvent, TradingEventMessage

__all__ = [
    'EndOfDay',
    'Mailbox',
    'MailboxClosed',
    'OrderAccepted',
    'OrderCanceled',
    'OrderError',
    'OrderFilled',
    'OrderModified',
    'OrderRejected',
    'PollDue',
    'RebalanceDue',
    'TargetWeights',
    'TradingEvent',
    'TradingEventMessage',
]
