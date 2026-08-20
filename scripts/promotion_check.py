"""
Check whether a paper deployment has earned promotion to real money.

Reaching a real account is the one irreversible action in this project,
so the criteria for it are written down and, where possible, checked by
a machine rather than remembered. This script reads the ledger a paper
deployment produced and reports which criteria hold.

It cannot check everything. Whether a human has rehearsed a manual
liquidation, or agreed the real-money order cap, is not visible in a
database -- those are listed as manual and must be confirmed by the
person promoting. The script's job is to make sure the automatic half
is never waved through.

Usage:
    python scripts/promotion_check.py LEDGER_PATH [--min-days 20]
"""

import argparse
import sqlite3
import sys


DEFAULT_MIN_TRADING_DAYS = 20
MAX_STALE_RATIO = 0.2

MANUAL_CRITERIA = [
    'Paper smoke A-3, A-4 and A-5 have passed against a vps account.',
    'The real-money order cap and initial capital have been agreed, and '
    'are lower than the paper values unless there is a reason otherwise.',
    'A manual liquidation route has been rehearsed: you can flatten the '
    'account without this engine.',
    'The token issuer is settled. KIS refuses a re-issue for the same app '
    'key within sixty seconds, so if another bot shares the key, this '
    'engine must consume its token rather than mint one.',
    'Somebody is watching on the first real-money day.',
]


class Criterion:
    """
    One promotion criterion and its verdict.

    Parameters
    ----------
    name : `str`
        Short label.
    passed : `Boolean`
        Whether it holds.
    detail : `str`
        What was measured.
    """

    def __init__(self, name, passed, detail):
        self.name = name
        self.passed = passed
        self.detail = detail

    def __str__(self):
        return '%s %-28s %s' % (
            'PASS' if self.passed else 'FAIL', self.name, self.detail
        )


def check_ledger(path, min_trading_days=DEFAULT_MIN_TRADING_DAYS):
    """
    Evaluate every machine-checkable criterion against a ledger.

    Parameters
    ----------
    path : `str`
        Path to the ledger database a paper deployment produced.
    min_trading_days : `int`, optional
        How many days of paper trading to require.

    Returns
    -------
    `list[Criterion]`
        The verdicts, in reporting order.
    """
    conn = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [
            _check_days_run(conn, min_trading_days),
            _check_orders_placed(conn),
            _check_fills_booked(conn),
            _check_no_orphan_intents(conn),
            _check_stale_ratio(conn),
            _check_no_duplicate_fills(conn),
            _check_kill_switch_exercised(conn),
        ]
    finally:
        conn.close()


def _count(conn, sql, *params):
    """
    Return the first column of the first row of a counting query.
    """
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else 0


def _check_days_run(conn, minimum):
    """
    Require enough days of paper operation to have seen a bad one.
    """
    days = _count(conn, 'SELECT COUNT(*) FROM equity_curve')
    return Criterion(
        'days-run',
        days >= minimum,
        '%d day(s) recorded, %d required' % (days, minimum)
    )


def _check_orders_placed(conn):
    """
    Require that orders actually reached the venue.

    A deployment that ran for a month without trading has demonstrated
    nothing about trading.
    """
    submitted = _count(
        conn, "SELECT COUNT(*) FROM orders WHERE order_no IS NOT NULL"
    )
    return Criterion(
        'orders-placed', submitted > 0, '%d order(s) accepted' % submitted
    )


def _check_fills_booked(conn):
    """
    Require that fills came back and were accounted for.
    """
    fills = _count(conn, 'SELECT COUNT(*) FROM fills')
    return Criterion(
        'fills-booked', fills > 0, '%d fill(s) recorded' % fills
    )


def _check_no_orphan_intents(conn):
    """
    Require no order whose fate is unknown.

    An intent with no order number means a process died mid-submission
    and nobody established whether that order exists. Promoting with
    one outstanding means promoting without knowing the position.
    """
    orphans = _count(
        conn,
        "SELECT COUNT(*) FROM orders WHERE order_no IS NULL "
        "AND state = 'INTENT'"
    )
    return Criterion(
        'no-orphan-intents', orphans == 0, '%d unresolved' % orphans
    )


def _check_stale_ratio(conn):
    """
    Require that most orders finish inside the time budget.

    A high stale rate means the budget or the rebalance time is wrong,
    and real money would inherit that.
    """
    total = _count(conn, "SELECT COUNT(*) FROM orders WHERE order_no IS NOT NULL")
    stale = _count(conn, "SELECT COUNT(*) FROM orders WHERE state = 'STALE'")
    ratio = (stale / total) if total else 0.0
    return Criterion(
        'stale-ratio',
        total > 0 and ratio <= MAX_STALE_RATIO,
        '%d of %d stale (%.0f%%, limit %.0f%%)'
        % (stale, total, ratio * 100, MAX_STALE_RATIO * 100)
    )


def _check_no_duplicate_fills(conn):
    """
    Confirm the idempotency key held in practice.

    The constraint makes duplicates impossible, so this is a check that
    the constraint was actually in force -- a ledger created by an
    older schema would not have it.
    """
    duplicates = _count(
        conn,
        'SELECT COUNT(*) FROM (SELECT fill_key FROM fills '
        'GROUP BY fill_key HAVING COUNT(*) > 1)'
    )
    return Criterion(
        'no-duplicate-fills', duplicates == 0,
        '%d duplicated key(s)' % duplicates
    )


def _check_kill_switch_exercised(conn):
    """
    Require that the kill switch was tried at least once.

    A safety measure nobody has ever fired is a safety measure nobody
    knows works.
    """
    fired = _count(
        conn,
        "SELECT COUNT(*) FROM orders WHERE state = 'REJECTED' "
        "AND note LIKE '%Kill switch%'"
    )
    return Criterion(
        'kill-switch-exercised', fired > 0,
        '%d order(s) refused by the kill switch' % fired
    )


def main(argv=None):
    """
    Run the checks and report.

    Returns
    -------
    `int`
        Zero when every automatic criterion passes.
    """
    parser = argparse.ArgumentParser(
        description='Check paper-deployment evidence before promoting to '
                    'a real-money account.'
    )
    parser.add_argument('ledger', help='Path to the paper ledger database.')
    parser.add_argument(
        '--min-days', type=int, default=DEFAULT_MIN_TRADING_DAYS,
        help='Trading days of paper operation to require.'
    )
    args = parser.parse_args(argv)

    criteria = check_ledger(args.ledger, args.min_days)
    print('Automatic criteria')
    for criterion in criteria:
        print('  %s' % criterion)

    print('\nManual criteria — confirm each before promoting')
    for item in MANUAL_CRITERIA:
        print('  [ ] %s' % item)

    failed = [c for c in criteria if not c.passed]
    if failed:
        print(
            '\n%d automatic criterion/criteria not met. Not ready for a '
            'real-money account.' % len(failed)
        )
        return 1
    print(
        '\nEvery automatic criterion is met. Promotion still requires the '
        'manual list above.'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
