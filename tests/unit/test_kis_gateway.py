"""
The gateway is the only place the vendor SDK appears, so these tests
drive it with fakes standing in for that SDK. What they check is the
translation and the retry policy -- the two things that are ours rather
than the vendor's.
"""

import importlib.util
import os
import sys

import pytest


def _load_gateway():
    """
    Import the gateway from scripts/, which is not an installed package.

    Returns
    -------
    `module`
        The loaded gateway module.
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))),
        'scripts', 'kis_gateway.py'
    )
    spec = importlib.util.spec_from_file_location('kis_gateway', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['kis_gateway'] = module
    spec.loader.exec_module(module)
    return module


gateway = _load_gateway()


class FakeFunctions:
    """
    Stands in for the SDK's function module, recording its calls.
    """

    def __init__(self, order_rows=None, price_rows=None, ccld_rows=None,
                 balance=None, holiday_rows=None, empty_first=0):
        self.order_rows = order_rows
        self.price_rows = price_rows
        self.ccld_rows = ccld_rows
        self.balance = balance
        self.holiday_rows = holiday_rows
        self.empty_first = empty_first
        self.calls = []

    def order_cash(self, **kwargs):
        self.calls.append(('order_cash', kwargs))
        return self.order_rows

    def inquire_price(self, **kwargs):
        self.calls.append(('inquire_price', kwargs))
        if len([c for c in self.calls if c[0] == 'inquire_price']) <= (
            self.empty_first
        ):
            return []
        return self.price_rows

    def inquire_daily_ccld(self, **kwargs):
        self.calls.append(('inquire_daily_ccld', kwargs))
        return (self.ccld_rows, [])

    def inquire_balance(self, **kwargs):
        self.calls.append(('inquire_balance', kwargs))
        return self.balance

    def chk_holiday(self, **kwargs):
        self.calls.append(('chk_holiday', kwargs))
        return self.holiday_rows


class FakeAuth:
    """
    Stands in for the SDK's auth module, counting throttle calls.
    """

    def __init__(self):
        self.sleeps = 0

    def smart_sleep(self):
        self.sleeps += 1


def _gateway(functions, settle_seconds=0.0, sleeps=None):
    """
    Build a gateway around fake SDK modules.
    """
    return gateway.KisGateway(
        env_dv='demo',
        cano='12345678',
        acnt_prdt_cd='01',
        functions=functions,
        auth=FakeAuth(),
        settle_seconds=settle_seconds,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None))
    )


@pytest.mark.parametrize(
    'svr,expected', [('vps', 'demo'), ('prod', 'real')]
)
def test_env_dv_for(svr, expected):
    """
    Tests the server-to-environment mapping.
    """
    assert gateway.env_dv_for(svr) == expected


@pytest.mark.parametrize('svr', ['', 'demo', 'real', 'live', None])
def test_env_dv_for_rejects_anything_else(svr):
    """
    Tests that an unrecognised server name raises.

    Guessing here could route an order to real money.
    """
    with pytest.raises(ValueError):
        gateway.env_dv_for(svr)


def test_a_buy_is_translated_to_the_venue_vocabulary():
    """
    Tests symbol, side, quantity and market-order flags.
    """
    functions = FakeFunctions(order_rows=[{'ODNO': '0000117057'}])
    gw = _gateway(functions)

    order_no = gw.place_market_order('EQ:005930', 10)

    assert order_no == '0000117057'
    name, kwargs = functions.calls[0]
    assert name == 'order_cash'
    assert kwargs['pdno'] == '005930'
    assert kwargs['ord_dv'] == 'buy'
    assert kwargs['ord_qty'] == '10'
    assert kwargs['ord_dvsn'] == gateway.MARKET_ORDER
    assert kwargs['ord_unpr'] == '0'


def test_a_sell_sends_an_unsigned_quantity_with_the_sell_side():
    """
    Tests that the sign becomes the side, since the venue takes the
    quantity unsigned.
    """
    functions = FakeFunctions(order_rows=[{'ODNO': '0001'}])
    gw = _gateway(functions)

    gw.place_market_order('EQ:005930', -7)

    _, kwargs = functions.calls[0]
    assert kwargs['ord_dv'] == 'sell'
    assert kwargs['ord_qty'] == '7'


def test_an_order_pauses_first_and_is_never_retried():
    """
    Tests the rule that a duplicate order is worse than a failed one.

    The rate limit is what makes an order fail, and it cannot be
    recovered from by retrying a non-idempotent call, so the gateway
    pauses to avoid it instead.
    """
    functions = FakeFunctions(order_rows=[])
    sleeps = []
    gw = _gateway(functions, settle_seconds=1.0, sleeps=sleeps)

    with pytest.raises(RuntimeError):
        gw.place_market_order('EQ:005930', 10)

    assert sleeps == [1.0]
    assert len([c for c in functions.calls if c[0] == 'order_cash']) == 1


def test_a_query_is_retried_while_it_comes_back_empty():
    """
    Tests that an empty query response is retried, since it usually
    means the per-second limit was hit and repeating a query is safe.
    """
    functions = FakeFunctions(
        price_rows=[{'stck_prpr': '71000'}], empty_first=2
    )
    gw = _gateway(functions)

    assert gw.get_price('EQ:005930') == 71000.0
    assert len([c for c in functions.calls if c[0] == 'inquire_price']) == 3


def test_the_fill_enquiry_is_not_retried():
    """
    Tests that an empty fill response is taken at face value.

    An accepted but unfilled order and a throttled call look
    identical, so asking again cannot tell them apart -- the caller
    polls on its own schedule instead.
    """
    functions = FakeFunctions(ccld_rows=[])
    gw = _gateway(functions)

    report = gw.get_order_report('0001')

    assert report.filled_quantity == 0
    assert report.is_done is False
    assert len(
        [c for c in functions.calls if c[0] == 'inquire_daily_ccld']
    ) == 1


def test_a_fill_report_is_parsed():
    """
    Tests that a returned fill row becomes an OrderReport.
    """
    functions = FakeFunctions(ccld_rows=[{
        'odno': '0001', 'tot_ccld_qty': '10', 'rmn_qty': '0',
        'avg_prvs': '71,000', 'rjct_qty': '0', 'prsm_tlex_smtl': '105'
    }])
    gw = _gateway(functions)

    report = gw.get_order_report('0001')

    assert report.filled_quantity == 10
    assert report.average_price == 71000.0
    assert report.fees == 105.0
    assert report.is_done is True


def test_a_balance_is_parsed_with_projected_cash():
    """
    Tests that the account snapshot reads projected cash, not the
    settled deposit.
    """
    functions = FakeFunctions(balance=(
        [{'pdno': '005930', 'hldg_qty': '10', 'pchs_avg_pric': '70000'}],
        [{
            'prvs_rcdl_excc_amt': '1500000',
            'dnca_tot_amt': '2200000',
            'tot_evlu_amt': '2200000'
        }]
    ))
    gw = _gateway(functions)

    balance = gw.get_balance()

    assert balance.cash == 1500000.0
    assert balance.settled_cash == 2200000.0
    assert len(balance.holdings) == 1


def test_the_trading_day_is_read_from_the_opening_flag():
    """
    Tests the holiday enquiry.
    """
    functions = FakeFunctions(
        holiday_rows=[{'bass_dt': '20260817', 'opnd_yn': 'N'}]
    )
    gw = _gateway(functions)
    assert gw.get_trading_day('20260817') is False


def test_every_call_throttles_first():
    """
    Tests that the per-call delay is applied everywhere.

    A paper account hits the per-second limit with ordinary
    consecutive calls, not only with paginated ones.
    """
    functions = FakeFunctions(
        price_rows=[{'stck_prpr': '71000'}],
        order_rows=[{'ODNO': '0001'}]
    )
    gw = _gateway(functions)

    gw.get_price('EQ:005930')
    gw.place_market_order('EQ:005930', 1)

    assert gw.auth.sleeps == 2


def test_the_engine_does_not_import_the_gateway():
    """
    Tests the dependency boundary the design rests on.

    The engine must not reach the vendor SDK, and it does not import
    the gateway that does; the operator's script injects it.
    """
    import subprocess
    result = subprocess.run(
        ['grep', '-rn', 'kis_gateway', '--include=*.py', 'vmtrader/'],
        capture_output=True, text=True
    )
    assert result.stdout == ''


class ChartFunctions(FakeFunctions):
    """
    Stands in for the SDK's chart endpoint, serving pages of bars.
    """

    def __init__(self, pages):
        super().__init__()
        self.pages = list(pages)
        self.chart_calls = []

    def inquire_daily_itemchartprice(self, **kwargs):
        self.chart_calls.append(kwargs)
        if not self.pages:
            return ([], [])
        return ([], self.pages.pop(0))


def _bars(end_date, count, base=70000.0):
    """
    Build a page of chart rows ending on a date, newest first as the
    venue returns them.
    """
    import datetime
    end = datetime.datetime.strptime(end_date, '%Y%m%d')
    return [
        {
            'stck_bsop_date': (
                end - datetime.timedelta(days=offset)
            ).strftime('%Y%m%d'),
            'stck_clpr': str(base + offset)
        }
        for offset in range(count)
    ]


def test_daily_closes_are_returned_oldest_first():
    """
    Tests that the venue's newest-first page becomes an ascending
    series, since a signal buffer is filled in time order.
    """
    functions = ChartFunctions([_bars('20260820', 5)])
    gw = _gateway(functions)

    closes = gw.get_daily_closes('EQ:005930', '20260801', '20260820')

    dates = [date for date, _ in closes]
    assert dates == sorted(dates)
    assert len(closes) == 5


def test_a_short_page_ends_the_paging():
    """
    Tests that a page smaller than the limit stops the walk, since
    there is nothing older to find.
    """
    functions = ChartFunctions([_bars('20260820', 5), _bars('20260810', 5)])
    gw = _gateway(functions)

    gw.get_daily_closes('EQ:005930', '20260801', '20260820')

    assert len(functions.chart_calls) == 1


def test_a_full_page_is_followed_by_another_request():
    """
    Tests that a lookback longer than one page keeps asking.

    The venue serves at most a hundred bars per call, so a
    two-hundred-day lookback needs more than one.
    """
    functions = ChartFunctions([
        _bars('20260831', gateway.CHART_PAGE_SIZE),
        _bars('20260521', 20, base=60000.0),
    ])
    gw = _gateway(functions)

    gw.get_daily_closes('EQ:005930', '20260101', '20260831')

    assert len(functions.chart_calls) == 2
    # The second request ends the day before the first page's oldest bar.
    assert functions.chart_calls[1]['fid_input_date_2'] < (
        functions.chart_calls[0]['fid_input_date_2']
    )


def test_adjusted_prices_are_requested_by_default():
    """
    Tests the adjustment flag, where 0 means adjusted.

    An unadjusted split reads to a moving average as a crash.
    """
    functions = ChartFunctions([_bars('20260820', 5)])
    gw = _gateway(functions)

    gw.get_daily_closes('EQ:005930', '20260801', '20260820')
    assert functions.chart_calls[0]['fid_org_adj_prc'] == '0'

    functions.pages = [_bars('20260820', 5)]
    gw.get_daily_closes('EQ:005930', '20260801', '20260820', adjusted=False)
    assert functions.chart_calls[1]['fid_org_adj_prc'] == '1'


def test_the_symbol_is_translated_for_the_chart_endpoint():
    """
    Tests that the engine symbol becomes a product code.
    """
    functions = ChartFunctions([_bars('20260820', 5)])
    gw = _gateway(functions)

    gw.get_daily_closes('EQ:005930', '20260801', '20260820')

    assert functions.chart_calls[0]['fid_input_iscd'] == '005930'


def test_bars_outside_the_requested_range_are_dropped():
    """
    Tests that paging cannot return more than was asked for.
    """
    functions = ChartFunctions([_bars('20260820', 10)])
    gw = _gateway(functions)

    closes = gw.get_daily_closes('EQ:005930', '20260815', '20260820')

    assert all('20260815' <= date <= '20260820' for date, _ in closes)


def test_the_aggregate_module_directory_goes_on_the_path(tmp_path):
    """
    Tests that the directory holding 'domestic_stock_functions' is
    added, not merely the clone root.

    The clone ships the same endpoints twice: 'examples_user' has one
    aggregate module per asset class, and 'examples_llm' splits them
    one module per API. Only the first offers the module this gateway
    imports, and adding just the root or just examples_llm leaves it
    unimportable — which is how this was found, on a real clone.
    """
    home = tmp_path / 'open-trading-api'
    (home / 'examples_user' / 'domestic_stock').mkdir(parents=True)
    (home / 'examples_llm').mkdir()

    before = list(sys.path)
    try:
        gateway.add_ota_to_path(str(home))
        assert str(home / 'examples_user') in sys.path
        assert str(home / 'examples_user' / 'domestic_stock') in sys.path
        assert str(home / 'examples_llm') in sys.path
    finally:
        sys.path[:] = before


def test_a_missing_clone_says_so(tmp_path):
    """
    Tests that a wrong OTA_HOME fails with an actionable message.
    """
    with pytest.raises(FileNotFoundError, match='Clone koreainvestment'):
        gateway.add_ota_to_path(str(tmp_path / 'absent'))


def test_a_clone_without_the_expected_layout_is_rejected(tmp_path):
    """
    Tests that a partial checkout is caught at path setup rather than
    at the first import.
    """
    home = tmp_path / 'not-really-ota'
    home.mkdir()
    with pytest.raises(FileNotFoundError, match='expected layouts'):
        gateway.add_ota_to_path(str(home))


def test_an_unanswerable_holiday_enquiry_names_the_likely_cause():
    """
    Tests the error raised when the venue will not answer.

    The paper server returns OPSQ0002, 'no such service code', for this
    endpoint. The SDK prints that and hands back an empty frame, so an
    unavailable service and a date with no data are indistinguishable
    here — which is why the message says what to do rather than only
    what happened.
    """
    functions = FakeFunctions(holiday_rows=[])
    gw = _gateway(functions)

    with pytest.raises(gateway.HolidayServiceUnavailable) as excinfo:
        gw.get_trading_day('20260820')

    message = str(excinfo.value)
    assert 'paper server' in message
    assert 'KrxExchange(holidays=' in message


def test_an_answered_holiday_enquiry_still_works():
    """
    Tests that the new exception did not swallow the ordinary path.
    """
    functions = FakeFunctions(
        holiday_rows=[{'bass_dt': '20260820', 'opnd_yn': 'Y'}]
    )
    gw = _gateway(functions)
    assert gw.get_trading_day('20260820') is True


def test_calls_are_spaced_across_threads():
    """
    Tests the throttle NFR-8 required and a real run demanded.

    The SDK's own delay sleeps inside the calling thread, which orders
    nothing when the settle worker and the main thread both call. A
    paper account answered EGW00201 — the per-second limit — while
    polling two orders, so the gateway now enforces a minimum gap
    across all callers.
    """
    import threading

    functions = FakeFunctions(price_rows=[{'stck_prpr': '71000'}])
    slept = []
    gw = gateway.KisGateway(
        env_dv='demo', cano='1', acnt_prdt_cd='01',
        functions=functions, auth=FakeAuth(),
        sleep=slept.append, min_call_interval=0.7
    )

    def call():
        gw.get_price('EQ:005930')

    threads = [threading.Thread(target=call) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # The first call goes straight through; the rest wait.
    assert len(slept) == 2
    assert all(0.0 < delay <= 0.7 for delay in slept)


def test_spacing_is_disabled_by_default_for_injected_gateways():
    """
    Tests that a gateway built directly, as tests do, does not sleep.

    The interval is chosen by 'connect' from the server, so a unit test
    assembling the object by hand is not slowed by it.
    """
    functions = FakeFunctions(price_rows=[{'stck_prpr': '71000'}])
    slept = []
    gw = _gateway(functions, sleeps=slept)
    gw.get_price('EQ:005930')
    gw.get_price('EQ:005930')
    assert slept == []
