# file: examples/download_data.py
"""
Download daily OHLCV bar data from Yahoo! Finance into VMTrader-compatible
CSV files, one file per symbol, named '<SYMBOL>.csv'.

Usage
-----
    # 기본 심볼(SPY, AGG) 다운로드
    python examples/download_data.py

    # 임의의 심볼 다운로드
    python examples/download_data.py --data SPY AGG QQQ
    python examples/download_data.py --data SPY,AGG,QQQ

    # 저장 위치 및 기간 지정
    python examples/download_data.py --data SPY --output-dir /path/to/csvs
    python examples/download_data.py --data SPY --start 2010-01-01 --end 2020-01-01

저장 위치는 '--output-dir', 환경변수 VMTRADER_CSV_DATA_DIR, 그리고 '.env' 파일의
VMTRADER_CSV_DATA_DIR 순으로 결정된다. '.env' 처리는 'vmtrader.env_file' 모듈을 참고.
"""

import argparse
import os
import sys

import yfinance as yf

from vmtrader.env_file import load_env_file


# VMTrader의 CSVDailyBarDataSource는 'Date'를 인덱스로 하고
# Open/High/Low/Close/Adj Close/Volume 컬럼을 가진 단일 헤더 CSV를 기대한다.
# 최신 yfinance는 기본적으로 MultiIndex 컬럼(Price/Ticker)과 auto_adjust=True를
# 사용하므로, 컬럼을 평탄화하고 'Adj Close'를 포함시켜 저장한다.
COLUMNS = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']

default_data_symbols = ['SPY', 'AGG']


def default_output_dir():
    """
    Resolve the default CSV output directory.

    This matches where the examples look for their CSV files, namely
    'os.environ.get('VMTRADER_CSV_DATA_DIR', '.')'.

    Returns
    -------
    `str`
        The default output directory.
    """
    return os.environ.get('VMTRADER_CSV_DATA_DIR', '.')


def parse_symbols(values):
    """
    Flatten the '--data' values into a de-duplicated list of uppercased
    symbols, accepting both space- and comma-separated forms.

    Parameters
    ----------
    values : `list[str]`
        The raw '--data' argument values. e.g. ['SPY', 'AGG,QQQ'].

    Returns
    -------
    `list[str]`
        The ordered, de-duplicated symbols. e.g. ['SPY', 'AGG', 'QQQ'].
    """
    symbols = []
    for value in values:
        for symbol in value.split(','):
            symbol = symbol.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def download_to_csv(symbol, output_dir, period='max', start=None, end=None):
    """
    Download the daily bars for a single symbol and write them to a
    VMTrader-compatible CSV file within the output directory.

    Parameters
    ----------
    symbol : `str`
        The Yahoo! Finance ticker. e.g. 'SPY'.
    output_dir : `str`
        The directory to write '<SYMBOL>.csv' into.
    period : `str`, optional
        The yfinance period to download. Ignored if 'start' is provided.
    start : `str`, optional
        The inclusive start date, as 'YYYY-MM-DD'.
    end : `str`, optional
        The exclusive end date, as 'YYYY-MM-DD'.

    Returns
    -------
    `str`
        The full path of the written CSV file.
    """
    print("Downloading %s data..." % symbol)
    if start is not None or end is not None:
        data = yf.download(
            symbol, start=start, end=end, auto_adjust=False, progress=False
        )
    else:
        data = yf.download(
            symbol, period=period, auto_adjust=False, progress=False
        )

    if data.empty:
        raise ValueError(
            "No data returned for symbol '%s'. Check that the ticker and "
            "date range are valid." % symbol
        )

    # MultiIndex 컬럼('Price', 'Ticker')을 단일 레벨로 평탄화
    if hasattr(data.columns, 'nlevels') and data.columns.nlevels > 1:
        data.columns = data.columns.get_level_values(0)
    data.columns.name = None
    data.index.name = 'Date'

    missing = [col for col in COLUMNS if col not in data.columns]
    if missing:
        raise ValueError(
            "Missing expected columns %s for symbol '%s'." % (missing, symbol)
        )
    data = data.loc[:, COLUMNS]

    csv_path = os.path.join(output_dir, '%s.csv' % symbol)
    data.to_csv(csv_path)
    print("%s 저장 완료! (%s rows)" % (csv_path, len(data)))
    return csv_path


def parse_args(argv=None):
    # 기본값을 계산하기 전에 '.env'를 반영한다.
    # 셸에 이미 설정된 값은 덮어쓰지 않는다.
    load_env_file()

    parser = argparse.ArgumentParser(
        prog='download_data.py',
        description=(
            'Yahoo! Finance에서 일봉 OHLCV 데이터를 받아 VMTrader가 읽을 수 있는 '
            'CSV(<SYMBOL>.csv)로 저장합니다.'
        ),
        epilog=(
            '사용 예시:\n'
            '  python examples/download_data.py\n'
            '  python examples/download_data.py --data SPY AGG QQQ\n'
            '  python examples/download_data.py --data SPY,AGG,QQQ\n'
            '  python examples/download_data.py --data SPY --start 2010-01-01 --end 2020-01-01\n'
            '  python examples/download_data.py --data SPY --output-dir /path/to/csvs\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '-d', '--data',
        nargs='+',
        metavar='SYMBOL',
        default=default_data_symbols,
        help=(
            "다운로드할 심볼 목록. 공백 또는 쉼표로 구분합니다. "
            "(기본값: %s)" % ' '.join(default_data_symbols)
        )
    )
    parser.add_argument(
        '-o', '--output-dir',
        default=default_output_dir(),
        metavar='DIR',
        help=(
            "CSV를 저장할 디렉토리. 예제가 CSV를 읽는 위치와 같아야 합니다. "
            "(기본값: 환경변수 VMTRADER_CSV_DATA_DIR 또는 '.env'의 값, 없으면 현재 디렉토리)"
        )
    )
    parser.add_argument(
        '-p', '--period',
        default='max',
        help="yfinance 다운로드 기간. --start 사용 시 무시됩니다. (기본값: max)"
    )
    parser.add_argument(
        '-s', '--start',
        default=None,
        metavar='YYYY-MM-DD',
        help="시작일. 지정하면 --period 대신 사용됩니다."
    )
    parser.add_argument(
        '-e', '--end',
        default=None,
        metavar='YYYY-MM-DD',
        help="종료일(미포함)."
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    symbols = parse_symbols(args.data)
    if not symbols:
        print("다운로드할 심볼이 없습니다. --data 옵션을 확인하세요.", file=sys.stderr)
        return 1

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    failures = []
    for symbol in symbols:
        try:
            download_to_csv(
                symbol,
                output_dir,
                period=args.period,
                start=args.start,
                end=args.end
            )
        except Exception as exc:
            print("'%s' 다운로드 실패: %s" % (symbol, exc), file=sys.stderr)
            failures.append(symbol)

    if failures:
        print("실패한 심볼: %s" % ', '.join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
