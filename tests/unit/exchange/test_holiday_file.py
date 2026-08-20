"""
The calendar is a file because the venue offers it to real accounts
only and asks to be called about once a day. These tests cover reading
it, and noticing when it has run out.
"""

import datetime
import json

import pandas as pd
import pytest

from vmtrader.exchange.krx_exchange import (
    KrxExchange, holiday_file_covers, load_holidays
)


def _write(tmp_path, holidays, start='2026-01-01', end='2027-01-31'):
    """
    Write a calendar file.
    """
    path = tmp_path / 'krx-holidays.json'
    path.write_text(json.dumps({
        'source': 'KIS chk_holiday (prod)',
        'fetched_at': '2026-08-20T18:00:00',
        'start': start,
        'end': end,
        'open_days': 250,
        'holidays': holidays,
    }), encoding='utf-8')
    return str(path)


def test_holidays_are_read_as_dates(tmp_path):
    """
    Tests that the file becomes what KrxExchange expects.
    """
    path = _write(tmp_path, ['2026-08-17', '2027-01-01'])
    holidays = load_holidays(path)
    assert holidays == {
        datetime.date(2026, 8, 17), datetime.date(2027, 1, 1)
    }


def test_a_loaded_calendar_closes_the_market(tmp_path):
    """
    Tests the loader against the exchange it feeds.
    """
    path = _write(tmp_path, ['2026-08-17'])
    exchange = KrxExchange(holidays=load_holidays(path))

    assert exchange.is_open_at_datetime(
        pd.Timestamp('2026-08-17 10:00:00')
    ) is False
    assert exchange.is_open_at_datetime(
        pd.Timestamp('2026-08-18 10:00:00')
    ) is True


def test_an_exhausted_calendar_is_detectable(tmp_path):
    """
    Tests the range check.

    A calendar that has run out is worse than none, because every date
    past its end looks like a trading day. Callers ask whether the file
    speaks for the date rather than trusting its silence.
    """
    path = _write(tmp_path, ['2026-08-17'], start='2026-01-01',
                  end='2026-12-31')

    assert holiday_file_covers(path, pd.Timestamp('2026-08-20')) is True
    assert holiday_file_covers(path, pd.Timestamp('2027-01-02')) is False
    assert holiday_file_covers(path, datetime.date(2025, 12, 31)) is False


def test_a_file_without_a_range_does_not_claim_coverage(tmp_path):
    """
    Tests that a malformed file reports no coverage rather than
    pretending to speak for every date.
    """
    path = tmp_path / 'broken.json'
    path.write_text(json.dumps({'holidays': []}), encoding='utf-8')
    assert holiday_file_covers(str(path), pd.Timestamp('2026-08-20')) is False


def test_a_missing_file_raises(tmp_path):
    """
    Tests that an absent calendar is loud.

    Silently continuing with no holidays would filter weekends only,
    and the session would try to trade on a public holiday.
    """
    with pytest.raises(FileNotFoundError):
        load_holidays(str(tmp_path / 'absent.json'))
