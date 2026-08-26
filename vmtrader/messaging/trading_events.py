"""
The base class every event message shares, and the topic names.

An event is a fact in transit: built once, read by another thread,
never edited. That is precisely what a frozen dataclass already is, so
this base hands the work to 'dataclasses' instead of hand-rolling
'__slots__' and a '_set()' back door, which is how an earlier draft of
this module did it.

Three decorator flags carry the contract, and every subclass repeats
them:

    @dataclass(frozen=True, slots=True, kw_only=True)

'frozen' is the immutability the mailbox depends on -- a consumer that
could edit a message would be sharing state with its producer, which
is the one thing the mailbox exists to prevent. 'slots' keeps a
mistyped attribute from silently becoming a new one. 'kw_only' lets a
subclass declare its fields in the order a reader wants to see them
rather than the order Python's default-argument rule demands: without
it, one field carrying a default poisons every field after it and the
class fails to define at import time. Events are constructed by
keyword everywhere anyway, so nothing is given up for it.

Forgetting a flag would leave a message that still passes every other
test, so tests/unit/messaging/test_events.py asserts all three on
every subclass rather than trusting this docstring to be read.

Topic names live here too, and they are not ledger states. The
ledger's strings answer "where is this order now"; a topic answers
"what just happened", or in the lifecycle group, "what is now due".
Keeping the two vocabularies separate is what lets either of them
change without dragging the other along
(docs/dev/threading-and-event-architecture.md, decision 7).
"""

from dataclasses import dataclass, fields
from typing import Any, ClassVar


class TradingEvent:
    """
    The topic each kind of event is published under.

    A message's dataclass type is its identity; the topic is the
    stable label that identity travels under -- in a log line, or as
    the key a handler is registered against.

    The order group is exactly what a KRX cash-equity venue reports.
    KIS delivers all of it down one real-time channel: "주문·정정·취소·
    거부 접수 통보 와 체결 통보 가 모두 수신됩니다" (H0STCNI0). Options
    and futures events -- assignment, exercise, expiry, cash
    settlement -- have no topic here, because this engine trades cash
    equities and a topic no venue ever publishes is a vocabulary
    someone will one day write a handler for and never see fire.

    The lifecycle group is the clock speaking rather than the venue,
    which is why those topics read "due" instead of past tense.
    """

    # The venue speaking: past tense, one per thing that happened.
    ACCEPTED_ORDER = 'accepted'
    MODIFIED_ORDER = 'modified'
    CANCELED_ORDER = 'canceled'
    FILLED_ORDER = 'filled'
    REJECTED_ORDER = 'rejected'
    ERROR_ORDER = 'error'

    # The clock speaking: something is now due.
    REBALANCE_DUE = 'rebalance_due'
    END_OF_DAY = 'end_of_day'
    POLL_DUE = 'poll_due'

    # The strategy speaking: the one topic that asks rather than tells.
    TARGET_WEIGHTS = 'target_weights'


@dataclass(frozen=True, slots=True)
class TradingEventMessage:
    """
    Base class for every message that crosses a mailbox.

    Holds no fields of its own. It exists to give the vocabulary one
    common type to name in a signature, one place for the topic to
    live, and one way to turn a message into handler arguments.

    Attributes
    ----------
    event_name : `str`
        The topic this message is published under. Declared as a
        ClassVar so that 'dataclasses' treats it as an attribute of
        the type rather than a field of the instance: a topic is a
        property of the kind of event, and making it a constructor
        argument would let a caller post a fill under the rejection
        topic.
    """

    event_name: ClassVar[str] = ''

    def to_payload(self) -> dict[str, Any]:
        """
        Return the message's fields as keyword arguments.

        The topic is deliberately absent. This is the bundle that gets
        splatted into a handler call, and a handler takes the event's
        facts, not the label they arrived under; 'event_name' is
        readable from the message or its class when the topic itself
        is what is wanted.

        Returns
        -------
        `dict{str: object}`
            One entry per declared field, in declaration order.
        """
        return {f.name: getattr(self, f.name) for f in fields(self)}
