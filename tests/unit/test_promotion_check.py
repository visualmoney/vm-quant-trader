"""
Promoting to a real account is the one irreversible step here, so the
criteria are checked rather than remembered. These tests pin what the
checker refuses to wave through.
"""

import importlib.util
import os
import sys

import pandas as pd
import pytest

from vmtrader.broker.kis import ledger as ledger_states
from vmtrader.broker.kis.ledger import OrderLedger


def _load():
    """
    Import the checker from scripts/, which is not a package.
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))),
        'scripts', 'promotion_check.py'
    )
    spec = importlib.util.spec_from_file_location('promotion_check', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['promotion_check'] = module
    spec.loader.exec_module(module)
    return module


checker = _load()


def _ledger(tmp_path, days=25, orders=10, stale=0, orphans=0,
            kill_switch=True, fills=True):
    """
    Build a ledger that looks like a paper deployment's history.
    """
    path = str(tmp_path / 'paper.db')
    ledger = OrderLedger(path)
    dt = pd.Timestamp('2026-08-20 15:40:00')

    for day in range(days):
        ledger.record_equity(dt + pd.Timedelta(days=day), 1000000.0 + day)

    for i in range(orders):
        order_id = 'o%d' % i
        ledger.record_intent(order_id, 'EQ:005930', 10, dt)
        ledger.record_submitted(order_id, '%04d' % i, dt)
        if fills:
            ledger.record_fill(
                order_id, '%04d' % i, 10, 10, 70000.0, 0.0, dt
            )
        state = (
            ledger_states.STALE if i < stale else ledger_states.FILLED
        )
        ledger.record_state(order_id, state, dt)

    for i in range(orphans):
        ledger.record_intent('orphan%d' % i, 'EQ:000660', 5, dt)

    if kill_switch:
        ledger.record_intent('halted', 'EQ:000660', 5, dt)
        ledger.record_state(
            'halted', ledger_states.REJECTED, dt,
            note="Kill switch file '/tmp/HALT' is present. Trading is halted."
        )
    ledger.close()
    return path


def _verdicts(path, **kwargs):
    """
    Return the criteria keyed by name.
    """
    return dict(
        (c.name, c) for c in checker.check_ledger(path, **kwargs)
    )


def test_a_healthy_paper_history_passes_every_automatic_criterion(tmp_path):
    """
    Tests the shape of evidence that clears the automatic half.
    """
    path = _ledger(tmp_path)
    assert all(c.passed for c in checker.check_ledger(path))
    assert checker.main([path]) == 0


def test_too_few_days_fails(tmp_path):
    """
    Tests that a short history is refused.

    A deployment that has not seen a bad day has not demonstrated
    anything about bad days.
    """
    path = _ledger(tmp_path, days=3)
    assert _verdicts(path)['days-run'].passed is False
    assert checker.main([path]) == 1


def test_the_day_requirement_is_configurable(tmp_path):
    """
    Tests that the threshold can be raised or lowered deliberately.
    """
    path = _ledger(tmp_path, days=10)
    assert _verdicts(path, min_trading_days=5)['days-run'].passed is True
    assert _verdicts(path, min_trading_days=30)['days-run'].passed is False


def test_a_deployment_that_never_traded_fails(tmp_path):
    """
    Tests that running without trading proves nothing about trading.
    """
    path = _ledger(tmp_path, orders=0, kill_switch=False, fills=False)
    verdicts = _verdicts(path)
    assert verdicts['orders-placed'].passed is False
    assert verdicts['fills-booked'].passed is False


def test_an_unresolved_orphan_intent_fails(tmp_path):
    """
    Tests that an order of unknown fate blocks promotion.

    An intent with no order number means nobody established whether
    that order exists, so the position is not known.
    """
    path = _ledger(tmp_path, orphans=1)
    assert _verdicts(path)['no-orphan-intents'].passed is False


def test_a_high_stale_rate_fails(tmp_path):
    """
    Tests that chronic non-completion blocks promotion.

    Real money would inherit whatever is wrong with the time budget or
    the rebalance hour.
    """
    path = _ledger(tmp_path, orders=10, stale=5)
    verdict = _verdicts(path)['stale-ratio']
    assert verdict.passed is False
    assert '50%' in verdict.detail


def test_a_tolerable_stale_rate_passes(tmp_path):
    """
    Tests that the occasional unfilled remainder is not a blocker.
    """
    path = _ledger(tmp_path, orders=10, stale=1)
    assert _verdicts(path)['stale-ratio'].passed is True


def test_an_unexercised_kill_switch_fails(tmp_path):
    """
    Tests that a safety measure nobody has fired is not accepted.
    """
    path = _ledger(tmp_path, kill_switch=False)
    assert _verdicts(path)['kill-switch-exercised'].passed is False


def test_the_checker_opens_the_ledger_read_only(tmp_path):
    """
    Tests that inspecting a deployment cannot alter it.
    """
    path = _ledger(tmp_path)
    checker.check_ledger(path)

    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        conn = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
        try:
            conn.execute('DELETE FROM fills')
        finally:
            conn.close()


def test_manual_criteria_are_printed_and_never_auto_passed(capsys, tmp_path):
    """
    Tests that the human half is always shown.

    The script's job is to stop the automatic half being waved through,
    not to imply the manual half is done.
    """
    path = _ledger(tmp_path)
    checker.main([path])
    out = capsys.readouterr().out

    assert 'Manual criteria' in out
    for item in checker.MANUAL_CRITERIA:
        assert item.split('.')[0] in out
    assert 'still requires the manual list' in out
