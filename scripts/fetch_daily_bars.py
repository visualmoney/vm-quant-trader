"""
Download daily bars from the venue into backtest-ready CSVs.

A backtest of Korean names needs Korean history, and the obvious place
to get it is the venue the strategy will actually trade against. Using
one source for both planes is the point: a backtest fed by a different
vendor's adjustment method would disagree with the live signals for
reasons that have nothing to do with the strategy.

Prices are adjusted for corporate actions, so 'Close' and 'Adj Close'
carry the same value. That is honest rather than lazy -- the venue
gives one adjusted series, and writing an invented unadjusted column
beside it would imply a distinction the data does not make.

Usage:
    python scripts/fetch_daily_bars.py 069500 114260 --years 4
"""

import argparse
import datetime
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))

DEFAULT_OUT = os.path.join(REPO_ROOT, 'data')
DEFAULT_YEARS = 4


def fetch_bars(gateway, symbol, start_date, end_date, adjusted=True):
    """
    Pull daily OHLC bars for one asset, paging backwards.

    Parameters
    ----------
    gateway : `KisGateway`
        An authenticated gateway.
    symbol : `str`
        The engine symbol, e.g. 'EQ:069500'.
    start_date : `str`
        Inclusive start, 'YYYYMMDD'.
    end_date : `str`
        Inclusive end, 'YYYYMMDD'.
    adjusted : `Boolean`, optional
        Whether to adjust for corporate actions.

    Returns
    -------
    `list[dict]`
        Bars with date, open and close, oldest first.
    """
    from kis_gateway import (
        CHART_PAGE_SIZE, MAX_CHART_PAGES, _rows, call_with_retry
    )
    from vmtrader.broker.kis.parse import parse_float, to_venue_symbol

    pdno = to_venue_symbol(symbol)
    collected = {}
    cursor = end_date

    for _ in range(MAX_CHART_PAGES * 6):
        if cursor < start_date:
            break
        gateway._throttle()
        # Retried, because an empty response here is ambiguous: the
        # venue returns nothing both when the history runs out and when
        # the per-second limit is hit. Reading the second as the first
        # ends the download early and silently, leaving a CSV that
        # looks complete and covers five months instead of four years.
        frame = call_with_retry(
            gateway.functions.inquire_daily_itemchartprice,
            attempts=4,
            backoff=1.0,
            sleep=gateway.sleep,
            env_dv=gateway.env_dv,
            fid_cond_mrkt_div_code='J',
            fid_input_iscd=pdno,
            fid_input_date_1=start_date,
            fid_input_date_2=cursor,
            fid_period_div_code='D',
            fid_org_adj_prc='0' if adjusted else '1'
        )
        output2 = frame[1] if isinstance(frame, tuple) else frame
        rows = _rows(output2)
        if not rows:
            break

        dates = []
        for row in rows:
            date = str(row.get('stck_bsop_date', '')).strip()
            if not date or not (start_date <= date <= end_date):
                continue
            close = parse_float(row, 'stck_clpr', default=0.0)
            open_ = parse_float(row, 'stck_oprc', default=0.0)
            if close <= 0.0:
                continue
            collected[date] = {
                'Date': '%s-%s-%s' % (date[:4], date[4:6], date[6:]),
                'Open': open_ if open_ > 0.0 else close,
                'Close': close,
            }
            dates.append(date)

        if not dates:
            break
        earliest = min(dates)
        if len(rows) < CHART_PAGE_SIZE:
            break
        cursor = (
            datetime.datetime.strptime(earliest, '%Y%m%d')
            - datetime.timedelta(days=1)
        ).strftime('%Y%m%d')

    return [collected[date] for date in sorted(collected)]


def write_csv(bars, path):
    """
    Write bars in the shape the CSV data source expects.

    Parameters
    ----------
    bars : `list[dict]`
        The bars, oldest first.
    path : `str`
        Destination file.
    """
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write('Date,Open,Close,Adj Close\n')
        for bar in bars:
            # The venue serves one adjusted series, so the adjusted
            # close is the close. Fabricating a different unadjusted
            # column would imply a distinction the data does not carry.
            handle.write(
                '%s,%s,%s,%s\n'
                % (bar['Date'], bar['Open'], bar['Close'], bar['Close'])
            )


def main(argv=None):
    """
    Download the requested symbols.

    Returns
    -------
    `int`
        Zero on success.
    """
    parser = argparse.ArgumentParser(
        description='Download daily bars from KIS into backtest CSVs.'
    )
    parser.add_argument('symbols', nargs='+', help='Six digit codes.')
    parser.add_argument('--years', type=float, default=DEFAULT_YEARS)
    parser.add_argument('--out', default=DEFAULT_OUT)
    parser.add_argument('--svr', default='vps')
    parser.add_argument('--ota-home', default=None)
    args = parser.parse_args(argv)

    from kis_gateway import KisGateway

    gateway = KisGateway.connect(svr=args.svr, ota_home=args.ota_home)
    end = datetime.date.today()
    start = end - datetime.timedelta(days=int(args.years * 365.25))
    os.makedirs(args.out, exist_ok=True)

    for code in args.symbols:
        symbol = code if code.startswith('EQ:') else 'EQ:%s' % code
        bars = fetch_bars(
            gateway, symbol,
            start.strftime('%Y%m%d'), end.strftime('%Y%m%d')
        )
        if not bars:
            print('%s: no bars returned' % symbol)
            continue
        path = os.path.join(args.out, '%s.csv' % symbol.replace('EQ:', ''))
        write_csv(bars, path)
        print(
            '%s: %d bars, %s to %s -> %s'
            % (symbol, len(bars), bars[0]['Date'], bars[-1]['Date'], path)
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
