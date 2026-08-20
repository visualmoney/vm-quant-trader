import datetime

import pandas as pd
import pytest

from vmtrader.exchange.krx_exchange import KrxExchange


@pytest.mark.parametrize(
    'timestamp,expected',
    [
        # Thursday 2026-08-20 is an ordinary trading day.
        ('2026-08-20 08:59:59', False),
        ('2026-08-20 09:00:00', True),
        ('2026-08-20 12:00:00', True),
        ('2026-08-20 15:29:59', True),
        # The close is exclusive.
        ('2026-08-20 15:30:00', False),
        ('2026-08-20 18:00:00', False),
        # Saturday and Sunday.
        ('2026-08-22 10:00:00', False),
        ('2026-08-23 10:00:00', False),
    ]
)
def test_is_open_at_datetime_session_boundaries(timestamp, expected):
    """
    Tests the regular session boundaries and the weekend.
    """
    exchange = KrxExchange()
    assert exchange.is_open_at_datetime(pd.Timestamp(timestamp)) is expected


def test_holiday_closes_the_market():
    """
    Tests that a supplied holiday closes an otherwise ordinary weekday.
    """
    holiday = datetime.date(2026, 8, 17)
    exchange = KrxExchange(holidays={holiday})
    assert exchange.is_open_at_datetime(
        pd.Timestamp('2026-08-17 10:00:00')
    ) is False
    assert exchange.is_open_at_datetime(
        pd.Timestamp('2026-08-18 10:00:00')
    ) is True


def test_aware_timestamp_is_converted_to_korean_time():
    """
    Tests that a timezone-aware timestamp is judged in Korean local
    time, not in whatever zone it arrived in.
    """
    exchange = KrxExchange()
    # 00:30 UTC is 09:30 in Seoul, so the market is open.
    assert exchange.is_open_at_datetime(
        pd.Timestamp('2026-08-20 00:30:00', tz='UTC')
    ) is True
    # 07:00 UTC is 16:00 in Seoul, after the close.
    assert exchange.is_open_at_datetime(
        pd.Timestamp('2026-08-20 07:00:00', tz='UTC')
    ) is False


def test_is_trading_day_ignores_time_of_day():
    """
    Tests that trading-day judgement is about the date alone.
    """
    exchange = KrxExchange(holidays={datetime.date(2026, 8, 17)})
    assert exchange.is_trading_day(pd.Timestamp('2026-08-20 03:00:00')) is True
    assert exchange.is_trading_day(pd.Timestamp('2026-08-22 10:00:00')) is False
    assert exchange.is_trading_day(pd.Timestamp('2026-08-17 10:00:00')) is False


def test_custom_session_times():
    """
    Tests that shortened sessions can be expressed, which KRX runs on
    days such as the university entrance examination.
    """
    exchange = KrxExchange(
        open_time=datetime.time(10, 0), close_time=datetime.time(16, 30)
    )
    assert exchange.is_open_at_datetime(
        pd.Timestamp('2026-08-20 09:30:00')
    ) is False
    assert exchange.is_open_at_datetime(
        pd.Timestamp('2026-08-20 16:00:00')
    ) is True
