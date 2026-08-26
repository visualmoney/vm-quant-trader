import pytest

from vmtrader.broker.live.guards import (
    KillSwitchEngaged, OrderLimitExceeded, SafetyGuard, TradingHalted
)
from vmtrader.errors import StopRequested


def test_no_limits_configured_allows_everything():
    """
    Tests that an unconfigured guard is inert, which is what unit tests
    of other components rely on.
    """
    guard = SafetyGuard()
    guard.check_order('EQ:005930', 1000000, 71000.0)
    assert guard.is_kill_switch_engaged() is False


def test_order_value_limit():
    """
    Tests that an order worth more than the cap is refused, and that
    one exactly at the cap is allowed.
    """
    guard = SafetyGuard(max_order_value=1000000.0)
    guard.check_order('EQ:005930', 10, 100000.0)
    with pytest.raises(OrderLimitExceeded, match='per-order limit'):
        guard.check_order('EQ:005930', 11, 100000.0)


def test_order_value_limit_uses_absolute_quantity():
    """
    Tests that a sale is measured by size, not by signed value, so a
    large sell cannot slip past a cap meant to bound both sides.
    """
    guard = SafetyGuard(max_order_value=1000000.0)
    with pytest.raises(OrderLimitExceeded):
        guard.check_order('EQ:005930', -11, 100000.0)


def test_session_order_count_limit():
    """
    Tests that the session budget is spent by submissions and refuses
    the order after it.
    """
    guard = SafetyGuard(max_orders_per_session=2)
    for _ in range(2):
        guard.check_order('EQ:005930', 1, 71000.0)
        guard.record_submission()
    with pytest.raises(OrderLimitExceeded, match='Session order limit'):
        guard.check_order('EQ:005930', 1, 71000.0)


def test_rejected_orders_do_not_consume_the_session_budget():
    """
    Tests that an order refused by the value cap leaves the count
    untouched, since it never reached the venue.
    """
    guard = SafetyGuard(max_order_value=100.0, max_orders_per_session=1)
    with pytest.raises(OrderLimitExceeded):
        guard.check_order('EQ:005930', 10, 71000.0)
    assert guard.orders_submitted == 0
    guard.check_order('EQ:005930', 1, 50.0)


def test_kill_switch_file_halts_trading(tmp_path):
    """
    Tests that creating the file halts trading and removing it resumes.
    """
    switch = tmp_path / 'HALT'
    guard = SafetyGuard(kill_switch_path=str(switch))

    guard.check_can_trade()
    guard.check_order('EQ:005930', 1, 71000.0)

    switch.write_text('halted by test')
    assert guard.is_kill_switch_engaged() is True
    with pytest.raises(KillSwitchEngaged):
        guard.check_can_trade()
    with pytest.raises(KillSwitchEngaged):
        guard.check_order('EQ:005930', 1, 71000.0)

    switch.unlink()
    guard.check_can_trade()


def test_kill_switch_is_read_each_time_not_cached(tmp_path):
    """
    Tests that the file is consulted on every check.

    An operator flipping the switch mid-session must be obeyed at the
    next opportunity, so the state cannot be read once at construction.
    """
    switch = tmp_path / 'HALT'
    guard = SafetyGuard(kill_switch_path=str(switch))
    assert guard.is_kill_switch_engaged() is False
    switch.write_text('')
    assert guard.is_kill_switch_engaged() is True


def test_the_gate_reads_every_stop_signal(tmp_path):
    """
    Tests that one function answers "may we trade".

    D14 invariant 4 asks for a single point where stop signals are
    checked. Until the reconciliation halt moved in there were four
    reading sites in three shapes -- and one of them returned quietly,
    so no loop could ever see it. Adding a signal is a branch here
    now, not a fourth place to remember.
    """
    switch = tmp_path / 'STOP'
    guard = SafetyGuard(kill_switch_path=str(switch))

    guard.check_can_trade()   # nothing engaged

    guard.halt('reconciliation found an overstatement')
    with pytest.raises(TradingHalted, match='overstatement'):
        guard.check_can_trade()

    guard.halted_reason = None
    switch.touch()
    with pytest.raises(KillSwitchEngaged):
        guard.check_can_trade()


def test_every_stop_signal_shares_one_base():
    """
    Tests the property that lets a loop name the family once.

    A consumer loop absorbs handler failures by design. It must not
    absorb a stop, and it can only tell them apart if every stop is
    catchable under one name.
    """
    assert issubclass(KillSwitchEngaged, StopRequested)
    assert issubclass(TradingHalted, StopRequested)
    # A limit is not a stop: it refuses one order and the cycle goes on.
    assert not issubclass(OrderLimitExceeded, StopRequested)


def test_a_halt_does_not_clear_itself():
    """
    Tests that resuming is a human decision.

    Believing we hold more than the venue reports is not the kind of
    thing that stops being true because time passed. Clearing it means
    a new session, once somebody has looked.
    """
    guard = SafetyGuard()
    guard.halt('overstated')

    assert guard.is_halted() is True
    with pytest.raises(TradingHalted):
        guard.check_can_trade()
    with pytest.raises(TradingHalted):
        guard.check_can_trade()
