"""
Fetch the KRX trading calendar and cache it to a file.

The venue offers this endpoint to real accounts only -- a paper account
answers OPSQ0002, 'no such service code' -- and asks that it be called
about once a day. So it is fetched by its own scheduled job, from the
real account, and written to a file that paper and real deployments
alike read.

Nothing here can move money. The endpoint is a pure query, and no other
call is made. What does need care is the SDK's token cache, whose
filename carries the date but not the server: authenticate against the
real server in the same day as a paper session and the paper session
will read the real token back out and fail. This script therefore runs
with its own HOME, which moves the SDK's whole config directory
somewhere the paper deployment never looks.

Usage:
    python scripts/fetch_holidays.py --out ~/data/vmtrader/krx-holidays.json
"""

import argparse
import datetime
import json
import os
import shutil
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO_ROOT, 'out', 'krx-holidays.json')
DEFAULT_ISOLATED_HOME = os.path.expanduser('~/.vmtrader/holiday-home')
DEFAULT_DAYS = 400


def isolate_sdk_home(isolated_home, real_home=None):
    """
    Point the SDK's config directory somewhere private, and populate it.

    The SDK reads credentials and writes its token under '$HOME/KIS/
    config', deriving the path at import time. Giving this process its
    own HOME keeps a real-account token out of the directory the paper
    deployment reads, since the token filename does not record which
    server issued it.

    Parameters
    ----------
    isolated_home : `str`
        Directory to use as HOME.
    real_home : `str`, optional
        Where the credentials actually live. Defaults to the current
        HOME.

    Returns
    -------
    `str`
        The configuration directory now in use.
    """
    source = os.path.join(
        real_home or os.path.expanduser('~'), 'KIS', 'config',
        'kis_devlp.yaml'
    )
    if not os.path.isfile(source):
        raise FileNotFoundError(
            "No KIS credentials at '%s'. The SDK reads them from "
            "~/KIS/config/kis_devlp.yaml." % source
        )

    config_dir = os.path.join(isolated_home, 'KIS', 'config')
    os.makedirs(config_dir, mode=0o700, exist_ok=True)
    target = os.path.join(config_dir, 'kis_devlp.yaml')
    # Copied rather than linked, so a token written beside it cannot
    # land next to the original by following the link back.
    shutil.copyfile(source, target)
    os.chmod(target, 0o600)

    os.environ['HOME'] = isolated_home
    return config_dir


def fetch(svr='prod', days=DEFAULT_DAYS, ota_home=None, start=None):
    """
    Ask the venue which of the next N days it opens on.

    Parameters
    ----------
    svr : `str`, optional
        Which server to ask. Only the real one answers.
    days : `int`, optional
        How far ahead to fetch.
    ota_home : `str`, optional
        The SDK clone.
    start : `datetime.date`, optional
        First date to ask about. Defaults to today.

    Returns
    -------
    `dict`
        The calendar payload, ready to serialise.
    """
    sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))
    from kis_gateway import _rows, add_ota_to_path, env_dv_for

    env_dv_for(svr)
    add_ota_to_path(ota_home)

    import kis_auth as ka
    import domestic_stock_functions as fn

    ka.auth(svr=svr)

    begin = start or datetime.date.today()
    end = begin + datetime.timedelta(days=days)

    holidays = []
    open_days = 0
    cursor = begin
    seen = set()

    while cursor <= end:
        ka.smart_sleep()
        frame = fn.chk_holiday(bass_dt=cursor.strftime('%Y%m%d'))
        rows = _rows(frame)
        if not rows:
            break

        latest = cursor
        for row in rows:
            text = str(row.get('bass_dt', '')).strip()
            if not text or text in seen:
                continue
            date = datetime.datetime.strptime(text, '%Y%m%d').date()
            if date > end:
                # Recorded neither as covered nor as a holiday. The
                # venue answers past the range asked for, and counting
                # those dates as covered while dropping their holidays
                # would make the file claim to speak for days it never
                # examined -- the exact failure the range check exists
                # to catch.
                continue
            seen.add(text)
            latest = max(latest, date)
            if str(row.get('opnd_yn', '')).strip().upper() == 'Y':
                open_days += 1
            else:
                holidays.append(date.isoformat())

        if latest <= cursor:
            break
        cursor = latest + datetime.timedelta(days=1)

    if not seen:
        raise RuntimeError(
            'The venue returned no calendar rows. On a paper account it '
            'answers OPSQ0002 for this endpoint; use the real server.'
        )

    covered = sorted(seen)
    return {
        'source': 'KIS chk_holiday (%s)' % svr,
        'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'start': datetime.datetime.strptime(
            covered[0], '%Y%m%d'
        ).date().isoformat(),
        'end': datetime.datetime.strptime(
            covered[-1], '%Y%m%d'
        ).date().isoformat(),
        'open_days': open_days,
        'holidays': sorted(holidays),
    }


def main(argv=None):
    """
    Fetch the calendar and write it out.

    Returns
    -------
    `int`
        Zero on success.
    """
    parser = argparse.ArgumentParser(
        description='Cache the KRX trading calendar from the venue.'
    )
    parser.add_argument('--out', default=DEFAULT_OUT)
    parser.add_argument(
        '--svr', default='prod',
        help='Only the real server answers this endpoint.'
    )
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS)
    parser.add_argument('--ota-home', default=None)
    parser.add_argument(
        '--isolated-home', default=DEFAULT_ISOLATED_HOME,
        help='HOME for this process, keeping its token cache away from '
             'the paper deployment.'
    )
    args = parser.parse_args(argv)

    isolate_sdk_home(args.isolated_home)
    payload = fetch(svr=args.svr, days=args.days, ota_home=args.ota_home)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write('\n')

    print(
        'Wrote %d holiday(s) and %d trading day(s) covering %s to %s -> %s'
        % (
            len(payload['holidays']), payload['open_days'],
            payload['start'], payload['end'], args.out
        )
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
