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
