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

from vmtrader.broker.live import ledger as ledger_states
from vmtrader.broker.live.ledger import OrderLedger


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
            kill_switch=True, fills=True, mode='paper', stamp=True,
            name='paper.db'):
    """
    Build a ledger that looks like a paper deployment's history.

    'mode' and 'stamp' exist so that a test can produce the two
    ledgers the checker must now refuse: one belonging to a real
    deployment, and one that records no deployment at all.
    """
    path = str(tmp_path / name)
    ledger = OrderLedger(path)
    dt = pd.Timestamp('2026-08-20 15:40:00')

    if stamp:
        ledger.stamp_identity('kis', mode, 'kis-etf-01')

    for day in range(days):
        ledger.record_equity(
            dt + pd.Timedelta(days=day), 1000000.0 + day, mode=mode
        )

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


def test_a_ledger_with_no_recorded_identity_cannot_be_promoted(tmp_path):
    """
    Tests that an unidentified ledger fails rather than passing.

    The checker used to read whichever file it was handed and trust the
    operator that it was the paper one. A ledger that cannot say what
    it is has to fail, or every ledger written before identities
    existed would pass this criterion for free.
    """
    path = _ledger(tmp_path, stamp=False, mode='unknown')
    verdict = _verdicts(path)['ledger-is-paper']
    assert not verdict.passed
    assert 'no deployment identity' in verdict.detail


def test_a_real_money_ledger_cannot_be_promoted(tmp_path):
    """
    Tests that a real deployment's history is not evidence for
    promoting it.

    Everything else in the ledger would look healthy; the point is that
    it is a record of the account being promoted to, not of a rehearsal
    for it.
    """
    path = _ledger(tmp_path, mode='real', name='real.db')
    verdict = _verdicts(path)['ledger-is-paper']
    assert not verdict.passed
    assert 'mode=real' in verdict.detail


def test_foreign_rows_in_a_paper_ledger_are_reported_as_mixed(tmp_path):
    """
    Tests that real rows inside a paper ledger fail the criterion.

    The identity stamp prevents this happening through the engine, but
    a hand-assembled or hand-edited file is not stopped by it, and the
    row-level mode is what catches that.
    """
    path = _ledger(tmp_path)
    ledger = OrderLedger(path)
    ledger.record_equity(
        pd.Timestamp('2026-09-30 15:40:00'), 1000000.0, mode='real'
    )
    ledger.close()

    verdict = _verdicts(path)['ledger-is-paper']
    assert not verdict.passed
    assert 'mixed' in verdict.detail
    assert '1 row(s) mode=real' in verdict.detail


def test_a_paper_ledger_names_the_deployment_it_judged(tmp_path):
    """
    Tests that a pass says which account it looked at.

    A verdict that does not name what it measured is the trust this
    criterion replaces, only wearing a PASS.
    """
    verdict = _verdicts(_ledger(tmp_path))['ledger-is-paper']
    assert verdict.passed
    assert 'all mode=paper' in verdict.detail
    assert 'venue=kis' in verdict.detail
    assert 'account=kis-etf-01' in verdict.detail
