import datetime
import json

from vmtrader.exchange.exchange import Exchange


def load_holidays(path):
    """
    Read a holiday calendar written by 'scripts/fetch_holidays.py'.

    The calendar is a file rather than a live call because the venue
    offers the endpoint only to real accounts, asks that it be called
    about once a day, and would otherwise be consulted on every
    launch. A file also means a session runs when the venue does not.

    Parameters
    ----------
    path : `str`
        Path to the JSON calendar.

    Returns
    -------
    `set[datetime.date]`
        Dates on which the exchange does not open.
    """
    with open(path, encoding='utf-8') as handle:
        payload = json.load(handle)

    holidays = set()
    for text in payload.get('holidays', []):
        holidays.add(datetime.date.fromisoformat(text))
    return holidays


def holiday_file_covers(path, dt):
    """
    Return whether a calendar file speaks for the given date.

    A calendar that has run out is worse than no calendar, because it
    reports every remaining day as a trading day. Callers check the
    range rather than trusting the file's silence.

    Parameters
    ----------
    path : `str`
        Path to the JSON calendar.
    dt : `pd.Timestamp` or `datetime.date`
        The date to check for.

    Returns
    -------
    `Boolean`
        Whether the date falls inside the fetched range.
    """
    with open(path, encoding='utf-8') as handle:
        payload = json.load(handle)

    start = payload.get('start')
    end = payload.get('end')
    if not start or not end:
        return False

    date = dt.date() if hasattr(dt, 'date') else dt
    return (
        datetime.date.fromisoformat(start)
        <= date
        <= datetime.date.fromisoformat(end)
    )


class KrxExchange(Exchange):
    """
    The Korea Exchange (KRX) trading calendar.

    Regular session is 09:00-15:30 Korea Standard Time. Unlike
    SimulatedExchange this class is timezone aware and understands
    holidays, because a live session that mistakes a holiday for a
    trading day submits orders into a closed market.

    Holidays are supplied by the caller rather than derived here. The
    Korean holiday calendar shifts every year -- substitute holidays,
    the lunar calendar and temporary closures all move it -- so the
    authority is the venue. KIS publishes it through the 'chk_holiday'
    endpoint, whose 'opnd_yn' field answers exactly the question this
    class asks. That endpoint is documented for roughly one call a day,
    so callers are expected to fetch once and pass the result in.

    Parameters
    ----------
    holidays : `set[datetime.date]`, optional
        Dates on which the exchange does not open, beyond weekends.
    open_time : `datetime.time`, optional
        The time the regular session opens. Defaults to 09:00.
    close_time : `datetime.time`, optional
        The time the regular session closes. Defaults to 15:30.
    """

    TIMEZONE = 'Asia/Seoul'

    def __init__(self, holidays=None, open_time=None, close_time=None):
        self.holidays = set(holidays) if holidays is not None else set()
        self.open_time = open_time or datetime.time(9, 0)
        self.close_time = close_time or datetime.time(15, 30)

    def _to_local(self, dt):
        """
        Return the timestamp expressed in Korea Standard Time.

        A timezone-aware timestamp is converted; a naive one is taken to
        be Korean local time already, since that is what an operator on
        a Seoul-configured host would write.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The timestamp to convert.

        Returns
        -------
        `pd.Timestamp`
            The timestamp in Korea Standard Time.
        """
        if dt.tzinfo is None:
            return dt
        return dt.tz_convert(self.TIMEZONE)

    def is_open_at_datetime(self, dt):
        """
        Check whether KRX is open at the provided timestamp.

        The close is exclusive: 15:30:00 itself is already shut.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The timestamp to check for open market hours.

        Returns
        -------
        `Boolean`
            Whether the exchange is open at this timestamp.
        """
        local_dt = self._to_local(dt)
        if not self.is_trading_day(local_dt):
            return False
        return self.open_time <= local_dt.time() < self.close_time

    def is_trading_day(self, dt):
        """
        Check whether the date of the provided timestamp is a trading
        day, irrespective of the time of day.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The timestamp whose date is checked.

        Returns
        -------
        `Boolean`
            Whether the exchange trades on this date.
        """
        local_dt = self._to_local(dt)
        if local_dt.weekday() > 4:
            return False
        return local_dt.date() not in self.holidays
