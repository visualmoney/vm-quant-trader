import dataclasses

import pandas as pd
import pytest

import vmtrader.messaging as messaging
from vmtrader.messaging import (
    EndOfDay,
    OrderCanceled,
    OrderError,
    OrderFilled,
    OrderModified,
    OrderRejected,
    RebalanceDue,
    TargetWeights,
    TradingEventMessage,
)


def _message_classes():
    """
    Return every exported event message class.

    Enumerated from '__all__' rather than from '__subclasses__()',
    because 'dataclass(slots=True)' builds a replacement class and
    leaves the undecorated original registered as a subclass too. The
    ghost has no '__slots__' and would fail the contract that the real
    class satisfies.

    Returns
    -------
    `list[type]`
        The concrete message classes, base excluded.
    """
    exported = [getattr(messaging, name) for name in messaging.__all__]
    return [
        obj for obj in exported
        if isinstance(obj, type)
        and issubclass(obj, TradingEventMessage)
        and obj is not TradingEventMessage
    ]


def _a_fill():
    """
    Build a representative fill event.

    Returns
    -------
    `OrderFilled`
        The event.
    """
    return OrderFilled(
        order_no='0000117057',
        symbol='EQ:005930',
        quantity=3,
        cumulative_filled=10,
        average_price=71200.0,
        cumulative_fees=105.0,
        dt=pd.Timestamp('2026-08-24 10:00', tz='Asia/Seoul'),
    )


def test_events_are_immutable():
    """
    Tests that an event is a fact, not a mutable record.

    An event crosses a thread boundary; a consumer that could edit it
    would be sharing state with the producer, which is exactly what
    the mailbox exists to prevent.
    """
    fill = _a_fill()
    with pytest.raises(dataclasses.FrozenInstanceError):
        fill.quantity = 99


def test_order_events_carry_the_correlation_id():
    """
    Tests that every order event names its order.

    The stack trace dies at the queue; the order number is the only
    thread from a strategy callback back to the submission and to the
    ledger's idempotency key.
    """
    fill = _a_fill()
    rejection = OrderRejected(
        order_no='0000117058',
        symbol='EQ:005930',
        quantity=-5,
        reason='장 종료',
        dt=fill.dt,
    )
    assert fill.order_no == '0000117057'
    assert rejection.order_no == '0000117058'


def test_amendment_and_cancellation_name_the_original_order():
    """
    Tests that a forked correlation chain keeps both ends.

    KRX answers an amendment or a cancellation with a fresh order
    number and closes the old one, so the number a strategy is
    holding stops matching the moment either happens. Carrying
    'original_order_no' alongside is the only way back; without it a
    consumer grows an order that never completes and loses one that
    did.
    """
    dt = pd.Timestamp('2026-08-24 10:05', tz='Asia/Seoul')
    for message_class in (OrderModified, OrderCanceled):
        event = message_class(
            order_no='0000117099',
            original_order_no='0000117057',
            order_id='intent-1',
            symbol='EQ:005930',
            quantity=2,
            dt=dt,
        )
        assert event.order_no != event.original_order_no
        assert event.original_order_no == '0000117057'
        # The intent outlives both numbers, which is what still ties
        # the pair to the rebalance that wanted the position.
        assert event.order_id == 'intent-1'


def test_an_error_is_not_a_rejection():
    """
    Tests that indeterminate failure has its own type.

    A rejection is the venue's verdict and proves no position was
    taken; an error is a missing answer and proves nothing, so the
    order may well exist. Collapsing the two would let a maybe-open
    order be read as certainly refused.
    """
    dt = pd.Timestamp('2026-08-24 10:06', tz='Asia/Seoul')
    error = OrderError(
        order_id='intent-2',
        order_no='',
        symbol='EQ:005930',
        quantity=7,
        reason='read timed out after 15s',
        dt=dt,
    )
    assert OrderError.event_name != OrderRejected.event_name
    # The venue number is the field that goes missing, since it
    # arrives in the very response that never came back. The engine's
    # own id is written before the call, so it is always there.
    assert error.order_no == ''
    assert error.order_id == 'intent-2'


def test_a_command_does_not_share_the_producer_s_dictionary():
    """
    Tests the trap 'frozen=True' does not catch.

    Freezing a dataclass freezes the reference, not the object behind
    it. Had the weights been carried as a dict, a producer reusing
    its working dictionary between cycles would rewrite what the
    consumer sees -- across a thread boundary, with no lock and no
    warning. Carrying pairs is what makes that impossible rather than
    merely discouraged.
    """
    working = {'EQ:005930': 0.6, 'EQ:000660': 0.4}
    command = TargetWeights(
        dt=pd.Timestamp('2026-08-24 09:10', tz='Asia/Seoul'),
        weights=tuple(sorted(working.items())),
    )

    working['EQ:005930'] = 99.0
    working['EQ:035720'] = 1.0

    assert command.as_dict() == {'EQ:005930': 0.6, 'EQ:000660': 0.4}


def test_a_command_hands_out_a_fresh_dictionary():
    """
    Tests that the consumer cannot reach back into the message.

    The sizer wants a dict, so the message builds one on request. If
    it handed out the same one twice, the first consumer to normalise
    weights in place would corrupt the second reading.
    """
    command = TargetWeights(
        dt=pd.Timestamp('2026-08-24 09:10', tz='Asia/Seoul'),
        weights=(('EQ:000660', 0.4), ('EQ:005930', 0.6)),
    )
    first = command.as_dict()
    first['EQ:005930'] = 99.0

    assert command.as_dict()['EQ:005930'] == 0.6


def test_command_weights_are_ordered_by_symbol():
    """
    Tests that a message's order is a function of its content.

    Two runs that decide the same weights must produce the same
    message, whatever order the strategy happened to build them in.
    Without that, a '.dat' comparison could differ on dictionary
    ordering alone.
    """
    dt = pd.Timestamp('2026-08-24 09:10', tz='Asia/Seoul')
    one = {'EQ:005930': 0.6, 'EQ:000660': 0.4}
    other = {'EQ:000660': 0.4, 'EQ:005930': 0.6}

    assert TargetWeights(dt=dt, weights=tuple(sorted(one.items()))) == (
        TargetWeights(dt=dt, weights=tuple(sorted(other.items())))
    )


def test_event_types_are_not_ledger_states():
    """
    Tests the separation of event vocabulary from order state.

    A single constant moonlighting as both an event topic and a state
    value is the debt this package was created to avoid: once
    'order.status = EVENT_FILLED' spreads, neither vocabulary can
    change without the other.
    """
    from vmtrader.broker.live import ledger

    event_names = {
        OrderFilled.__name__,
        OrderRejected.__name__,
        RebalanceDue.__name__,
        EndOfDay.__name__,
    }
    state_values = set(ledger.TERMINAL_STATES) | {
        ledger.INTENT, ledger.SUBMITTED
    }
    assert not event_names & state_values


def test_every_message_class_carries_the_three_flags():
    """
    Tests the decorator contract every event message must repeat.

    A subclass that forgets 'frozen' is mutable across a thread
    boundary, one that forgets 'slots' turns a mistyped attribute into
    a new one, and one that forgets 'kw_only' fails to define the
    moment a field with a default precedes a field without. The first
    two would pass every other test in this file, which is why the
    flags are asserted rather than left to the docstring.
    """
    for message_class in _message_classes():
        params = message_class.__dataclass_params__
        assert params.frozen, '%s is not frozen' % message_class.__name__
        assert '__slots__' in message_class.__dict__, (
            '%s has no __slots__' % message_class.__name__
        )
        for field in dataclasses.fields(message_class):
            assert field.kw_only, (
                '%s.%s is not keyword-only'
                % (message_class.__name__, field.name)
            )


def test_every_message_class_declares_its_topic():
    """
    Tests that a topic is set, distinct, and never a field.

    The base leaves 'event_name' empty, so a subclass that forgets to
    set one would publish under the empty topic and collide with every
    other forgetful subclass. Declaring it as a ClassVar is what keeps
    a caller from posting a fill under the rejection topic.
    """
    topics = []
    for message_class in _message_classes():
        assert message_class.event_name, (
            '%s has no topic' % message_class.__name__
        )
        field_names = {f.name for f in dataclasses.fields(message_class)}
        assert 'event_name' not in field_names, (
            '%s made its topic a field' % message_class.__name__
        )
        topics.append(message_class.event_name)
    assert len(topics) == len(set(topics)), 'topics collide: %s' % topics


def test_lifecycle_events_carry_the_engine_time():
    """
    Tests that a lifecycle event is the timestamp it stands for.

    The handler for RebalanceDue calls 'qts(dt)' with exactly this
    value -- the confluence point reached through the mailbox.
    """
    dt = pd.Timestamp('2026-08-24 09:10', tz='Asia/Seoul')
    assert RebalanceDue(dt=dt).dt == dt
    assert EndOfDay(dt=dt).dt == dt
