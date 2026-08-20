"""
The fetcher talks to the real account, so the parts that decide where
its token lands are tested here rather than discovered in production.
"""

import importlib.util
import os
import sys

import pytest


def _load():
    """
    Import the fetcher from scripts/, which is not a package.
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))),
        'scripts', 'fetch_holidays.py'
    )
    spec = importlib.util.spec_from_file_location('fetch_holidays', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['fetch_holidays'] = module
    spec.loader.exec_module(module)
    return module


fetcher = _load()


def test_the_sdk_config_is_copied_into_a_private_home(tmp_path):
    """
    Tests the isolation that keeps a real-account token away from the
    paper deployment.

    The SDK writes its token to '$HOME/KIS/config/KIS<date>', a name
    that records the date but not the server. Authenticate against the
    real server in the same day as a paper session and that session
    reads the real token back out and fails.
    """
    real_home = tmp_path / 'real'
    (real_home / 'KIS' / 'config').mkdir(parents=True)
    (real_home / 'KIS' / 'config' / 'kis_devlp.yaml').write_text(
        'my_app: "key"\n', encoding='utf-8'
    )
    isolated = tmp_path / 'private'

    previous = os.environ.get('HOME')
    try:
        config_dir = fetcher.isolate_sdk_home(
            str(isolated), real_home=str(real_home)
        )
        assert os.environ['HOME'] == str(isolated)
        assert os.path.isfile(os.path.join(config_dir, 'kis_devlp.yaml'))
        # A copy, so a token written beside it cannot follow a link
        # back to the directory the paper deployment reads.
        assert not os.path.islink(
            os.path.join(config_dir, 'kis_devlp.yaml')
        )
    finally:
        if previous is not None:
            os.environ['HOME'] = previous


def test_the_copied_credentials_are_not_world_readable(tmp_path):
    """
    Tests that copying the credentials does not loosen them.
    """
    real_home = tmp_path / 'real'
    (real_home / 'KIS' / 'config').mkdir(parents=True)
    (real_home / 'KIS' / 'config' / 'kis_devlp.yaml').write_text(
        'my_app: "key"\n', encoding='utf-8'
    )

    previous = os.environ.get('HOME')
    try:
        config_dir = fetcher.isolate_sdk_home(
            str(tmp_path / 'private'), real_home=str(real_home)
        )
        mode = os.stat(os.path.join(config_dir, 'kis_devlp.yaml')).st_mode
        assert oct(mode)[-3:] == '600'
    finally:
        if previous is not None:
            os.environ['HOME'] = previous


def test_absent_credentials_say_where_they_belong(tmp_path):
    """
    Tests that a missing config names the path the SDK reads.
    """
    with pytest.raises(FileNotFoundError, match='kis_devlp.yaml'):
        fetcher.isolate_sdk_home(
            str(tmp_path / 'private'), real_home=str(tmp_path / 'empty')
        )


def test_dates_past_the_requested_range_do_not_widen_the_coverage(tmp_path):
    """
    Tests that the file cannot claim to speak for days it skipped.

    The venue answers past the range asked for. Counting those dates as
    covered while dropping their holidays would produce a calendar that
    reports, say, Labour Day as a trading day — and the range check
    would wave it through, because the file says it covers that date.
    """
    import datetime

    class OneShotVenue:
        """
        Answers a single page reaching well past the requested end.
        """

        def chk_holiday(self, bass_dt=None, **kwargs):
            base = datetime.date(2026, 8, 20)
            rows = []
            for offset in range(120):
                day = base + datetime.timedelta(days=offset)
                rows.append({
                    'bass_dt': day.strftime('%Y%m%d'),
                    'opnd_yn': 'N' if day.weekday() > 4 else 'Y',
                })
            return rows

    class Auth:
        def auth(self, svr=None):
            pass

        def smart_sleep(self):
            pass

        def getTREnv(self):
            raise AssertionError('not needed')

    venue, auth = OneShotVenue(), Auth()
    sys.modules['domestic_stock_functions'] = venue
    sys.modules['kis_auth'] = auth
    try:
        payload = fetcher.fetch(
            svr='prod', days=30, ota_home=None,
            start=datetime.date(2026, 8, 20)
        )
    finally:
        del sys.modules['domestic_stock_functions']
        del sys.modules['kis_auth']

    end = datetime.date.fromisoformat(payload['end'])
    assert end <= datetime.date(2026, 9, 19)
    for text in payload['holidays']:
        assert datetime.date.fromisoformat(text) <= end
