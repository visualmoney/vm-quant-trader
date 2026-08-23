"""
A ledger belongs to one deployment, and says which.

Before it did, nothing distinguished the database a paper rehearsal
wrote from the one a real account wrote. Both contained valid rows, so
pointing the promotion check at the wrong file, or letting two
deployments share one, produced a confident verdict about the wrong
thing.
"""

import pytest

from vmtrader.broker.live.ledger import (
    LedgerIdentityConflict, OrderLedger
)


def _ledger(tmp_path, name='ledger.db'):
    """
    Open a ledger on a real file, since identity spans connections.
    """
    return OrderLedger(str(tmp_path / name))


def test_a_fresh_ledger_carries_no_identity(tmp_path):
    """
    Tests that identity is absent until something stamps it.
    """
    assert _ledger(tmp_path).get_identity() is None


def test_stamping_records_the_deployment(tmp_path):
    """
    Tests that the first stamp is stored and read back whole.
    """
    ledger = _ledger(tmp_path)
    ledger.stamp_identity('kis', 'paper', 'kis-etf-01')
    assert ledger.get_identity() == {
        'venue': 'kis', 'mode': 'paper', 'account_id': 'kis-etf-01'
    }


def test_restamping_the_same_deployment_is_accepted(tmp_path):
    """
    Tests that reopening a ledger is not an error.

    Every launch stamps, because a live session is a cron one-shot and
    has no memory of having done so. Only a disagreement is a problem.
    """
    ledger = _ledger(tmp_path)
    ledger.stamp_identity('kis', 'paper', 'kis-etf-01')
    ledger.stamp_identity('kis', 'paper', 'kis-etf-01')
    assert ledger.get_identity()['mode'] == 'paper'


@pytest.mark.parametrize(
    'venue,mode,account_id',
    [
        ('kis', 'real', 'kis-etf-01'),
        ('dbs', 'paper', 'kis-etf-01'),
        ('kis', 'paper', 'kis-etf-02'),
    ],
    ids=['different mode', 'different venue', 'different account']
)
def test_a_different_deployment_is_refused(tmp_path, venue, mode, account_id):
    """
    Tests that a second deployment cannot append to this ledger.

    The mode case is the dangerous one -- real money writing into a
    paper ledger destroys the evidence the promotion check reads -- but
    all three are the same mistake, and none of them announces itself.
    """
    ledger = _ledger(tmp_path)
    ledger.stamp_identity('kis', 'paper', 'kis-etf-01')

    with pytest.raises(LedgerIdentityConflict, match='separate ledger'):
        ledger.stamp_identity(venue, mode, account_id)


def test_the_conflict_names_both_deployments(tmp_path):
    """
    Tests that the message says what the ledger is and what opened it.

    An operator seeing this is holding two paths and needs to know
    which one they pointed at the wrong process.
    """
    ledger = _ledger(tmp_path)
    ledger.stamp_identity('kis', 'paper', 'kis-etf-01')

    with pytest.raises(LedgerIdentityConflict) as err:
        ledger.stamp_identity('kis', 'real', 'kis-etf-01')

    message = str(err.value)
    assert 'mode=paper' in message
    assert 'mode=real' in message


def test_equity_rows_carry_the_mode(tmp_path):
    """
    Tests that the curve records the mode per row.

    The meta table is the authority, but a row-level record is what
    lets a ledger assembled before identities existed, or by hand,
    still be audited.
    """
    ledger = _ledger(tmp_path)
    ledger.record_equity('2026-08-20 15:40:00', 1000.0, mode='paper')
    ledger.record_equity('2026-08-21 15:40:00', 1010.0, mode='paper')
    assert [row['mode'] for row in ledger.get_equity_curve()] == [
        'paper', 'paper'
    ]


def test_an_unstamped_equity_row_is_unknown_rather_than_paper(tmp_path):
    """
    Tests that the mode defaults to 'unknown', not to something benign.

    A default of 'paper' would let every pre-existing ledger pass the
    promotion check for free, which is exactly the trust this replaces.
    """
    ledger = _ledger(tmp_path)
    ledger.record_equity('2026-08-20 15:40:00', 1000.0)
    assert ledger.get_equity_curve()[0]['mode'] == 'unknown'


def test_a_ledger_from_before_the_mode_column_is_upgraded(tmp_path):
    """
    Tests that an older ledger opens rather than failing on every write.

    'CREATE TABLE IF NOT EXISTS' leaves an existing table alone, so
    without a migration the first insert naming the new column would
    raise against every ledger already in production.
    """
    import sqlite3

    path = str(tmp_path / 'old.db')
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE equity_curve ('
        'recorded_at TEXT PRIMARY KEY, total_equity REAL NOT NULL)'
    )
    conn.execute(
        "INSERT INTO equity_curve VALUES ('2026-01-01 15:40:00', 500.0)"
    )
    conn.commit()
    conn.close()

    ledger = OrderLedger(path)
    ledger.record_equity('2026-01-02 15:40:00', 510.0, mode='paper')

    rows = {row['recorded_at']: row['mode'] for row in ledger.get_equity_curve()}
    assert rows['2026-01-01 15:40:00'] == 'unknown'
    assert rows['2026-01-02 15:40:00'] == 'paper'
