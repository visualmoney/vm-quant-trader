"""
The only file in this repository that imports the KIS SDK.

Everything above it speaks the BrokerClient Protocol, so the engine and
its entire test suite run with no vendor library installed and no
network reachable. Ported from the equivalent boundary in
vm-quant-lab, which has been running against real accounts.

Three rules are load-bearing here, and all three were learned from a
live account rather than from documentation.

Orders are never retried. 'order_cash' is not idempotent, so retrying
an empty response places a second order. Instead the gateway pauses
before ordering: the rate limiter is what makes an order fail, and a
pause is idempotent in a way a retry is not.

Queries are retried, because their empty response is ambiguous and
harmless to repeat -- with one exception. The fill enquiry is not
retried, because an unfilled order and a throttled response look
identical, and re-asking cannot tell them apart.

The paper server is the default. Reaching the real one takes an
explicit argument, so no configuration mistake can quietly route an
order to real money.
"""

import os
import sys
import time


MARKET_ORDER = '01'
KRX = 'KRX'
DEFAULT_OTA_HOME = '../open-trading-api'

# Paper accounts are rate limited far more tightly than real ones, and
# the venue rejects the order outright rather than queuing it.
SETTLE_SECONDS = {'vps': 1.0, 'prod': 0.2}


def env_dv_for(svr):
    """
    Derive the SDK's environment discriminator from the server name.

    Parameters
    ----------
    svr : `str`
        Either 'vps' (paper) or 'prod' (real money).

    Returns
    -------
    `str`
        'demo' or 'real'.
    """
    if svr == 'vps':
        return 'demo'
    if svr == 'prod':
        return 'real'
    raise ValueError(
        "Unknown KIS server '%s'. Use 'vps' for paper trading or 'prod' "
        "for real money." % svr
    )


def call_with_retry(fn, attempts=3, backoff=0.5, sleep=None, **kwargs):
    """
    Call a query, retrying while it returns nothing.

    An empty response from KIS usually means the per-second limit was
    hit, and the call is a query, so repeating it costs nothing but
    time. Never use this for orders.

    Parameters
    ----------
    fn : `callable`
        The SDK function to call.
    attempts : `int`, optional
        How many times to try in total.
    backoff : `float`, optional
        Seconds added to the wait on each successive attempt.
    sleep : `callable`, optional
        Injected sleep, so tests need not spend real time.
    **kwargs : `dict`
        Passed through to the SDK function.

    Returns
    -------
    The SDK's return value, which may still be empty on the last try.
    """
    sleeper = sleep if sleep is not None else time.sleep
    result = None
    for attempt in range(attempts):
        result = fn(**kwargs)
        if not _is_empty(result):
            return result
        if attempt < attempts - 1:
            sleeper(backoff * (attempt + 1))
    return result


def _is_empty(result):
    """
    Return whether an SDK response carries no rows.

    Parameters
    ----------
    result : object
        A DataFrame, a tuple of them, or None.

    Returns
    -------
    `Boolean`
        Whether the response is empty.
    """
    if result is None:
        return True
    if isinstance(result, tuple):
        return all(_is_empty(item) for item in result)
    try:
        return len(result) == 0
    except TypeError:
        return False


def _rows(frame):
    """
    Convert an SDK frame into a list of plain dictionaries.

    The parser deals in dictionaries so that it never depends on
    pandas, which keeps it usable from the lighter processes.

    Parameters
    ----------
    frame : `pd.DataFrame` or `None`
        The SDK response.

    Returns
    -------
    `list[dict]`
        The rows, possibly empty.
    """
    if frame is None:
        return []
    if isinstance(frame, list):
        return frame
    if hasattr(frame, 'to_dict'):
        return frame.to_dict('records')
    return list(frame)


def add_ota_to_path(ota_home=None):
    """
    Put the SDK clone on the import path.

    The SDK is a cloned repository of example scripts rather than a
    published package, so there is nothing to declare as a dependency
    and nothing to install.

    Parameters
    ----------
    ota_home : `str`, optional
        Path to the clone. Defaults to the OTA_HOME environment
        variable, then to a sibling directory.

    Returns
    -------
    `str`
        The path that was added.
    """
    home = (
        ota_home
        or os.environ.get('OTA_HOME')
        or DEFAULT_OTA_HOME
    )
    home = os.path.abspath(home)
    if not os.path.isdir(home):
        raise FileNotFoundError(
            "No KIS SDK clone at '%s'. Clone koreainvestment/"
            "open-trading-api and point OTA_HOME at it." % home
        )
    for sub in (home, os.path.join(home, 'examples_llm')):
        if os.path.isdir(sub) and sub not in sys.path:
            sys.path.append(sub)
    return home


class KisGateway:
    """
    Implements the BrokerClient Protocol against the KIS SDK.

    Built by 'connect', which authenticates. The constructor itself
    takes already-resolved dependencies so that tests can drive the
    translation logic with fakes and no SDK present.

    Parameters
    ----------
    env_dv : `str`
        'demo' or 'real'.
    cano : `str`
        The account number.
    acnt_prdt_cd : `str`
        The account product code.
    functions : object
        The SDK's domestic stock function module.
    auth : object
        The SDK's authentication module, used for its throttle.
    settle_seconds : `float`, optional
        Extra pause before an order, on top of the throttle.
    sleep : `callable`, optional
        Injected sleep.
    """

    def __init__(
        self,
        env_dv,
        cano,
        acnt_prdt_cd,
        functions,
        auth,
        settle_seconds=1.0,
        sleep=None
    ):
        self.env_dv = env_dv
        self.cano = cano
        self.acnt_prdt_cd = acnt_prdt_cd
        self.functions = functions
        self.auth = auth
        self.settle_seconds = settle_seconds
        self.sleep = sleep if sleep is not None else time.sleep

    @classmethod
    def connect(cls, svr='vps', ota_home=None, sleep=None):
        """
        Authenticate against KIS and return a ready gateway.

        Defaults to the paper server. Reaching real money requires
        passing 'prod' explicitly -- there is no configuration file or
        environment variable that can do it silently.

        Parameters
        ----------
        svr : `str`, optional
            'vps' for paper trading, 'prod' for real money.
        ota_home : `str`, optional
            Path to the SDK clone.
        sleep : `callable`, optional
            Injected sleep.

        Returns
        -------
        `KisGateway`
            An authenticated gateway.
        """
        env_dv = env_dv_for(svr)
        add_ota_to_path(ota_home)

        import kis_auth as ka
        import domestic_stock_functions as fn

        ka.auth(svr=svr)
        trenv = ka.getTREnv()
        return cls(
            env_dv=env_dv,
            cano=trenv.my_acct,
            acnt_prdt_cd=trenv.my_prod,
            functions=fn,
            auth=ka,
            settle_seconds=SETTLE_SECONDS.get(svr, 1.0),
            sleep=sleep
        )

    def _throttle(self):
        """
        Pause between calls, using the SDK's own per-server delay.

        The SDK applies this only to paginated follow-ups, but a paper
        account hits the per-second limit with ordinary consecutive
        calls, so it goes in front of every one.
        """
        self.auth.smart_sleep()

    # -- BrokerClient Protocol -------------------------------------------

    def place_market_order(self, symbol, quantity):
        """
        Place a market order and return the venue's order number.

        Pauses first. A retry cannot be used to survive the rate limit
        here, because a duplicate order is worse than a failed one, so
        the gateway avoids the limit instead of recovering from it.

        Parameters
        ----------
        symbol : `str`
            The engine symbol, e.g. 'EQ:005930'.
        quantity : `int`
            The signed quantity, negative to sell.

        Returns
        -------
        `str`
            The venue order number.
        """
        from vmtrader.broker.kis.parse import parse_order_no, to_venue_symbol

        self._throttle()
        if self.settle_seconds > 0:
            self.sleep(self.settle_seconds)

        frame = self.functions.order_cash(
            env_dv=self.env_dv,
            ord_dv='buy' if quantity > 0 else 'sell',
            cano=self.cano,
            acnt_prdt_cd=self.acnt_prdt_cd,
            pdno=to_venue_symbol(symbol),
            ord_dvsn=MARKET_ORDER,
            ord_qty=str(abs(int(quantity))),
            ord_unpr='0',
            excg_id_dvsn_cd=KRX
        )
        rows = _rows(frame)
        if not rows:
            raise RuntimeError(
                'KIS returned no order acknowledgement for %s. The order '
                'may or may not have been accepted; it is recorded as '
                'submitted and will be reconciled.' % symbol
            )
        return parse_order_no(rows[0])

    def get_order_report(self, order_no):
        """
        Return the venue's cumulative view of one order.

        Not retried on an empty response: an accepted but unfilled
        order returns nothing, and so does a throttled call, so asking
        again cannot distinguish them and the caller polls anyway.

        Parameters
        ----------
        order_no : `str`
            The venue order number.

        Returns
        -------
        `OrderReport`
            The cumulative state of the order.
        """
        from vmtrader.broker.kis.parse import parse_order_report

        self._throttle()
        today = self._today()
        frame = self.functions.inquire_daily_ccld(
            env_dv=self.env_dv,
            pd_dv='inner',
            cano=self.cano,
            acnt_prdt_cd=self.acnt_prdt_cd,
            inqr_strt_dt=today,
            inqr_end_dt=today,
            sll_buy_dvsn_cd='00',
            ccld_dvsn='00',
            inqr_dvsn='00',
            inqr_dvsn_3='00',
            odno=order_no
        )
        output1 = frame[0] if isinstance(frame, tuple) else frame
        return parse_order_report(_rows(output1), order_no)

    def get_balance(self):
        """
        Return the account snapshot.

        Returns
        -------
        `AccountBalance`
            Cash, valuation and holdings.
        """
        from vmtrader.broker.kis.parse import parse_balance

        self._throttle()
        frame = call_with_retry(
            self.functions.inquire_balance,
            sleep=self.sleep,
            env_dv=self.env_dv,
            cano=self.cano,
            acnt_prdt_cd=self.acnt_prdt_cd,
            afhr_flpr_yn='N',
            inqr_dvsn='01',
            unpr_dvsn='01',
            fund_sttl_icld_yn='N',
            fncg_amt_auto_rdpt_yn='N',
            prcs_dvsn='00'
        )
        if isinstance(frame, tuple):
            output1, output2 = frame[0], frame[1]
        else:
            output1, output2 = frame, None
        return parse_balance(_rows(output1), _rows(output2))

    def get_price(self, symbol):
        """
        Return the current price of an asset.

        Parameters
        ----------
        symbol : `str`
            The engine symbol.

        Returns
        -------
        `float`
            The current price.
        """
        from vmtrader.broker.kis.parse import parse_price, to_venue_symbol

        self._throttle()
        frame = call_with_retry(
            self.functions.inquire_price,
            sleep=self.sleep,
            env_dv=self.env_dv,
            fid_cond_mrkt_div_code='J',
            fid_input_iscd=to_venue_symbol(symbol)
        )
        rows = _rows(frame)
        if not rows:
            raise RuntimeError(
                'KIS returned no price for %s.' % symbol
            )
        return parse_price(rows[0])

    def get_trading_day(self, date_str):
        """
        Return whether the venue opens on a date.

        KIS asks that this be called about once a day, so callers are
        expected to cache the answer rather than ask per order.

        Parameters
        ----------
        date_str : `str`
            The date in 'YYYYMMDD' form.

        Returns
        -------
        `Boolean`
            Whether the venue opens that day.
        """
        from vmtrader.broker.kis.parse import parse_is_trading_day

        self._throttle()
        frame = call_with_retry(
            self.functions.chk_holiday,
            sleep=self.sleep,
            bass_dt=date_str
        )
        return parse_is_trading_day(_rows(frame), date_str)

    def _today(self):
        """
        Return today's date in the venue's format.

        Returns
        -------
        `str`
            The date as 'YYYYMMDD'.
        """
        import datetime
        return datetime.datetime.now().strftime('%Y%m%d')
