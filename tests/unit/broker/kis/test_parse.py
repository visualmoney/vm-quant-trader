import pytest

from vmtrader.broker.kis import parse
from vmtrader.broker.kis.parse import KisParseError


def test_symbol_round_trip():
    """
    Tests that engine and venue symbologies convert both ways.
    """
    assert parse.to_engine_symbol('005930') == 'EQ:005930'
    assert parse.to_venue_symbol('EQ:005930') == '005930'
    assert parse.to_engine_symbol(' 005930 ') == 'EQ:005930'


@pytest.mark.parametrize('bad', ['005930', 'EQ:', '', 'CASH:KRW'])
def test_to_venue_symbol_rejects_non_equity_symbols(bad):
    """
    Tests that anything that is not an engine equity symbol raises.
    """
    with pytest.raises(KisParseError):
        parse.to_venue_symbol(bad)


@pytest.mark.parametrize(
    'raw,expected',
    [
        ('71000', 71000.0),
        ('  71000  ', 71000.0),
        ('71,000', 71000.0),
        ('71000.5', 71000.5),
    ]
)
def test_parse_float_handles_venue_string_formats(raw, expected):
    """
    Tests padding and thousands separators, both of which KIS emits.
    """
    assert parse.parse_float({'stck_prpr': raw}, 'stck_prpr') == expected


@pytest.mark.parametrize('row', [{}, {'stck_prpr': ''}, {'stck_prpr': None}])
def test_parse_float_raises_without_a_default(row):
    """
    Tests that an absent field raises when no default is given.
    """
    with pytest.raises(KisParseError):
        parse.parse_float(row, 'stck_prpr')


def test_parse_float_returns_the_default_when_given_one():
    """
    Tests that an absent field falls back to a supplied default.
    """
    assert parse.parse_float({}, 'prsm_tlex_smtl', default=0.0) == 0.0


def test_parse_float_raises_on_non_numeric_text():
    """
    Tests that unparseable text raises rather than becoming zero.
    """
    with pytest.raises(KisParseError):
        parse.parse_float({'stck_prpr': 'N/A'}, 'stck_prpr')


def test_parse_price_fails_loudly_when_absent():
    """
    Tests that a missing price raises.

    The price is the sizer's divisor, so defaulting it to zero would
    let a position size run away rather than skipping the asset.
    """
    with pytest.raises(KisParseError):
        parse.parse_price({})


@pytest.mark.parametrize('price', ['0', '-100'])
def test_parse_price_rejects_non_positive_prices(price):
    """
    Tests that a zero or negative price raises.
    """
    with pytest.raises(KisParseError):
        parse.parse_price({'stck_prpr': price})


def test_parse_order_no():
    """
    Tests that the order number is read and stripped.
    """
    assert parse.parse_order_no({'ODNO': ' 0000117057 '}) == '0000117057'


@pytest.mark.parametrize('row', [{}, {'ODNO': ''}, {'ODNO': '   '}])
def test_parse_order_no_raises_when_absent(row):
    """
    Tests that an order response without a number raises, since the
    engine cannot track a fill it has no handle on.
    """
    with pytest.raises(KisParseError):
        parse.parse_order_no(row)


def test_parse_order_report_fully_filled():
    """
    Tests a completed order.
    """
    rows = [{
        'odno': '0001', 'tot_ccld_qty': '10', 'rmn_qty': '0',
        'avg_prvs': '71,000', 'rjct_qty': '0', 'prsm_tlex_smtl': '105'
    }]
    report = parse.parse_order_report(rows, '0001')
    assert report.filled_quantity == 10
    assert report.average_price == 71000.0
    assert report.remaining_quantity == 0
    assert report.fees == 105.0
    assert report.is_done is True


def test_parse_order_report_partially_filled_is_not_done():
    """
    Tests that an order with quantity outstanding stays open.
    """
    rows = [{
        'odno': '0001', 'tot_ccld_qty': '4', 'rmn_qty': '6',
        'avg_prvs': '71000', 'rjct_qty': '0'
    }]
    report = parse.parse_order_report(rows, '0001')
    assert report.filled_quantity == 4
    assert report.remaining_quantity == 6
    assert report.is_done is False


def test_parse_order_report_reads_rejected_quantity():
    """
    Tests that a rejection is visible when the venue returns the row.

    An empty response cannot be told apart from an unfilled order, but
    a returned row carries the rejected quantity explicitly.
    """
    rows = [{
        'odno': '0001', 'tot_ccld_qty': '0', 'rmn_qty': '0',
        'avg_prvs': '0', 'rjct_qty': '10'
    }]
    report = parse.parse_order_report(rows, '0001')
    assert report.rejected_quantity == 10
    assert report.filled_quantity == 0


@pytest.mark.parametrize('rows', [None, [], [{'odno': '9999'}]])
def test_parse_order_report_treats_no_matching_row_as_unfilled(rows):
    """
    Tests that an absent row reports an unfilled, still open order.

    An accepted but unfilled order returns nothing, and so does a
    rate-limited response, so the two are deliberately not
    distinguished here.
    """
    report = parse.parse_order_report(rows, '0001')
    assert report.filled_quantity == 0
    assert report.is_done is False


def test_parse_order_report_ignores_other_orders():
    """
    Tests that rows belonging to other order numbers are not counted.
    """
    rows = [
        {'odno': '9999', 'tot_ccld_qty': '99', 'rmn_qty': '0'},
        {'odno': '0001', 'tot_ccld_qty': '5', 'rmn_qty': '5'},
    ]
    report = parse.parse_order_report(rows, '0001')
    assert report.filled_quantity == 5


def test_parse_holdings_drops_sold_out_products():
    """
    Tests that zero-quantity rows are dropped.

    KIS keeps reporting a product for the rest of the session after it
    has been sold out, and a zero-quantity position is not a position.
    """
    rows = [
        {'pdno': '005930', 'hldg_qty': '10', 'pchs_avg_pric': '70000'},
        {'pdno': '000660', 'hldg_qty': '0', 'pchs_avg_pric': '150000'},
    ]
    holdings = parse.parse_holdings(rows)
    assert len(holdings) == 1
    assert holdings[0].symbol == 'EQ:005930'
    assert holdings[0].quantity == 10
    assert holdings[0].average_price == 70000.0


def test_parse_balance_reads_projected_cash_not_the_settled_deposit():
    """
    Tests that cash comes from the projected figure.

    Korean equities settle at D+2, so the settled deposit disagrees
    with a ledger that deducts cash at fill time. Reconciling against
    it would raise a false alarm every day, so it is carried only for
    the record.
    """
    output1 = [{'pdno': '005930', 'hldg_qty': '10', 'pchs_avg_pric': '70000'}]
    output2 = {
        'prvs_rcdl_excc_amt': '1,500,000',
        'dnca_tot_amt': '2,200,000',
        'tot_evlu_amt': '2,200,000'
    }
    balance = parse.parse_balance(output1, output2)
    assert balance.cash == 1500000.0
    assert balance.settled_cash == 2200000.0
    assert balance.total_equity == 2200000.0
    assert len(balance.holdings) == 1


def test_parse_balance_accepts_a_summary_list():
    """
    Tests that output2 is accepted either as a row or as a list of one,
    since the venue helper wraps it in a frame.
    """
    balance = parse.parse_balance([], [{'prvs_rcdl_excc_amt': '100'}])
    assert balance.cash == 100.0


@pytest.mark.parametrize('summary', [None, {}, []])
def test_parse_balance_raises_without_a_summary(summary):
    """
    Tests that a balance response with no summary raises.
    """
    with pytest.raises(KisParseError):
        parse.parse_balance([], summary)


@pytest.mark.parametrize(
    'opnd_yn,expected', [('Y', True), ('N', False), (' y ', True)]
)
def test_parse_is_trading_day(opnd_yn, expected):
    """
    Tests that the opening flag decides the trading day.
    """
    rows = [{'bass_dt': '20260820', 'opnd_yn': opnd_yn}]
    assert parse.parse_is_trading_day(rows, '20260820') is expected


def test_parse_is_trading_day_raises_when_the_date_is_absent():
    """
    Tests that a response without the requested date raises rather than
    guessing that the market is open.
    """
    with pytest.raises(KisParseError):
        parse.parse_is_trading_day([{'bass_dt': '20260819'}], '20260820')
