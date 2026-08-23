"""
Turn KIS response rows into engine values.

Every field the venue returns is a string, often padded, sometimes
empty, and occasionally absent. This module is the single place that
knows those field names, so the rest of the engine never sees a KIS
spelling.

It fails loudly on a missing price. A mark of zero is a division in the
sizer, and silently sizing against zero is how a position runs away, so
an absent price raises rather than defaults.
"""

from vmtrader.broker.live.client import AccountBalance, Holding, OrderReport
from vmtrader.broker.live.errors import VenueParseError


SYMBOL_PREFIX = 'EQ:'


class KisParseError(VenueParseError):
    """
    Raised when a KIS response cannot be turned into an engine value.

    Subclasses the venue-neutral VenueParseError so that a caller
    handling any venue's malformed response need not name KIS, while
    one that only cares about KIS still can. VenueParseError inherits
    ValueError, which this class was raised as before.
    """


def to_engine_symbol(pdno):
    """
    Convert a venue product code into an engine symbol.

    Parameters
    ----------
    pdno : `str`
        The six digit product code, e.g. '005930'.

    Returns
    -------
    `str`
        The engine symbol, e.g. 'EQ:005930'.
    """
    code = str(pdno).strip()
    if not code:
        raise KisParseError('Empty product code in KIS response.')
    return '%s%s' % (SYMBOL_PREFIX, code)


def to_venue_symbol(symbol):
    """
    Convert an engine symbol into a venue product code.

    Parameters
    ----------
    symbol : `str`
        The engine symbol, e.g. 'EQ:005930'.

    Returns
    -------
    `str`
        The venue product code, e.g. '005930'.
    """
    text = str(symbol).strip()
    if not text.startswith(SYMBOL_PREFIX):
        raise KisParseError(
            "Symbol '%s' is not an engine equity symbol." % symbol
        )
    code = text[len(SYMBOL_PREFIX):]
    if not code:
        raise KisParseError(
            "Symbol '%s' has no product code." % symbol
        )
    return code


def parse_int(row, field, default=None):
    """
    Read an integer field from a KIS response row.

    Parameters
    ----------
    row : `dict`
        The response row.
    field : `str`
        The KIS field name.
    default : `int`, optional
        Returned when the field is absent or blank. Without one, an
        absent or blank field raises.

    Returns
    -------
    `int`
        The parsed value.
    """
    return int(_parse_number(row, field, default, float))


def parse_float(row, field, default=None):
    """
    Read a float field from a KIS response row.

    Parameters
    ----------
    row : `dict`
        The response row.
    field : `str`
        The KIS field name.
    default : `float`, optional
        Returned when the field is absent or blank. Without one, an
        absent or blank field raises.

    Returns
    -------
    `float`
        The parsed value.
    """
    return float(_parse_number(row, field, default, float))


def _parse_number(row, field, default, caster):
    """
    Shared numeric parsing for 'parse_int' and 'parse_float'.

    Parameters
    ----------
    row : `dict`
        The response row.
    field : `str`
        The KIS field name.
    default : `int` or `float` or `None`
        Returned when the field is absent or blank.
    caster : `callable`
        The numeric type to parse the text with.

    Returns
    -------
    `float`
        The parsed value, or the default.
    """
    raw = row.get(field) if hasattr(row, 'get') else None
    text = '' if raw is None else str(raw).strip().replace(',', '')
    if text == '':
        if default is None:
            raise KisParseError(
                "Field '%s' is missing from the KIS response." % field
            )
        return caster(default)
    try:
        return caster(text)
    except ValueError:
        raise KisParseError(
            "Field '%s' has non-numeric value '%s'." % (field, raw)
        )


def parse_price(row):
    """
    Read the current price from a KIS quote response.

    Fails loudly rather than defaulting: the price is the divisor the
    sizer uses, so a missing one must stop the trade for that asset,
    not produce a nonsensical quantity.

    Parameters
    ----------
    row : `dict`
        The 'inquire_price' output row.

    Returns
    -------
    `float`
        The current price.
    """
    price = parse_float(row, 'stck_prpr')
    if price <= 0.0:
        raise KisParseError(
            'KIS returned a non-positive price of %s.' % price
        )
    return price


def parse_order_no(row):
    """
    Read the order number from a KIS order response.

    Parameters
    ----------
    row : `dict`
        The 'order_cash' output row.

    Returns
    -------
    `str`
        The venue order number.
    """
    raw = row.get('ODNO') if hasattr(row, 'get') else None
    order_no = '' if raw is None else str(raw).strip()
    if not order_no:
        raise KisParseError(
            'KIS accepted no order number (ODNO) in the response.'
        )
    return order_no


def parse_order_report(rows, order_no):
    """
    Build an OrderReport from the rows of a fill enquiry.

    An order that has been accepted but not yet filled returns no row
    at all, which is indistinguishable from a rate-limited empty
    response. Both are reported here as unfilled and still open; the
    caller keeps polling rather than retrying, since a retry cannot
    tell the two apart either.

    Parameters
    ----------
    rows : `list[dict]`
        The 'inquire_daily_ccld' output1 rows.
    order_no : `str`
        The venue order number being asked about.

    Returns
    -------
    `OrderReport`
        The cumulative state of the order.
    """
    matching = [
        row for row in (rows or [])
        if str(row.get('odno', '')).strip() == str(order_no).strip()
    ]
    if not matching:
        return OrderReport(
            order_no=order_no,
            filled_quantity=0,
            average_price=0.0,
            remaining_quantity=0,
            rejected_quantity=0,
            fees=0.0,
            is_done=False
        )

    row = matching[-1]
    filled = parse_int(row, 'tot_ccld_qty', default=0)
    remaining = parse_int(row, 'rmn_qty', default=0)
    rejected = parse_int(row, 'rjct_qty', default=0)
    average = parse_float(row, 'avg_prvs', default=0.0)
    fees = parse_float(row, 'prsm_tlex_smtl', default=0.0)
    return OrderReport(
        order_no=order_no,
        filled_quantity=filled,
        average_price=average,
        remaining_quantity=remaining,
        rejected_quantity=rejected,
        fees=fees,
        is_done=remaining <= 0
    )


def parse_holdings(rows):
    """
    Build the held positions from a balance enquiry.

    Rows with no quantity are dropped: KIS keeps reporting a product
    for the rest of the session after it has been sold out.

    Parameters
    ----------
    rows : `list[dict]`
        The 'inquire_balance' output1 rows.

    Returns
    -------
    `tuple[Holding, ...]`
        The positions held.
    """
    holdings = []
    for row in rows or []:
        quantity = parse_int(row, 'hldg_qty', default=0)
        if quantity == 0:
            continue
        holdings.append(
            Holding(
                symbol=to_engine_symbol(row.get('pdno')),
                quantity=quantity,
                average_price=parse_float(row, 'pchs_avg_pric', default=0.0)
            )
        )
    return tuple(holdings)


def parse_balance(output1, output2):
    """
    Build an AccountBalance from a balance enquiry.

    Cash is read from the projected figure, which accounts for the
    day's trades. The settled deposit is carried alongside for the
    record but must not be reconciled against, because Korean equities
    settle at D+2 and the engine's ledger deducts cash at fill time.

    Parameters
    ----------
    output1 : `list[dict]`
        The holdings rows.
    output2 : `dict` or `list[dict]`
        The account summary row.

    Returns
    -------
    `AccountBalance`
        The account snapshot.
    """
    if isinstance(output2, list):
        summary = output2[0] if output2 else None
    else:
        summary = output2
    if not summary:
        raise KisParseError(
            'KIS returned no account summary in the balance response.'
        )
    return AccountBalance(
        cash=parse_float(summary, 'prvs_rcdl_excc_amt'),
        settled_cash=parse_float(summary, 'dnca_tot_amt', default=0.0),
        total_equity=parse_float(summary, 'tot_evlu_amt', default=0.0),
        holdings=parse_holdings(output1)
    )


def parse_is_trading_day(rows, date_str):
    """
    Read whether the venue opens on a date, from a holiday enquiry.

    Parameters
    ----------
    rows : `list[dict]`
        The 'chk_holiday' output rows.
    date_str : `str`
        The date in 'YYYYMMDD' form.

    Returns
    -------
    `Boolean`
        Whether the venue opens that day.
    """
    for row in rows or []:
        if str(row.get('bass_dt', '')).strip() == str(date_str).strip():
            return str(row.get('opnd_yn', '')).strip().upper() == 'Y'
    raise KisParseError(
        "KIS returned no holiday row for date '%s'." % date_str
    )


def parse_daily_closes(rows):
    """
    Build a sorted series of daily closes from a chart response.

    Rows without a usable close are dropped rather than carried as
    zeros: a signal fed a zero reads it as a total loss, which is a
    worse answer than a shorter history.

    Parameters
    ----------
    rows : `list[dict]`
        The 'inquire_daily_itemchartprice' output2 rows.

    Returns
    -------
    `list[tuple[str, float]]`
        (date, close) pairs, oldest first, deduplicated by date.
    """
    closes = {}
    for row in rows or []:
        date = str(row.get('stck_bsop_date', '')).strip()
        if not date:
            continue
        try:
            close = parse_float(row, 'stck_clpr')
        except KisParseError:
            continue
        if close <= 0.0:
            continue
        closes[date] = close
    return [(date, closes[date]) for date in sorted(closes)]
