# file: examples/tearsheet_output.py
"""
Shared tearsheet output handling for the QSTrader examples.

By default the examples run headless: the tearsheet is written to
'out/tearsheet-<name>-<yyyymmdd-hhmmss>.png' relative to the repository root
and no interactive window is opened. Pass '--show' to display it instead.

Settings are also read from a '.env' file, via 'qstrader.env_file'.

Usage
-----
    # 기본값: 파일로만 저장 (헤드리스 환경에서 동작)
    python examples/sixty_forty.py

    # 차트 창을 띄우기 (저장도 함께 수행)
    python examples/sixty_forty.py --show

    # 저장 없이 창만 띄우기
    python examples/sixty_forty.py --show --no-save

    # 저장 위치 지정
    python examples/sixty_forty.py --output /path/to/tearsheet.png
    python examples/sixty_forty.py --output-dir /path/to/dir
"""

import argparse
import datetime
import os

from qstrader.env_file import load_env_file


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TIMESTAMP_FORMAT = '%Y%m%d-%H%M%S'


def default_output_dir():
    """
    Resolve the default directory for saved tearsheets.

    Returns
    -------
    `str`
        The QSTRADER_OUTPUT_DIR environment variable if set, otherwise the
        'out' directory at the repository root.
    """
    return os.environ.get('QSTRADER_OUTPUT_DIR', os.path.join(REPO_ROOT, 'out'))


def example_name(example_file):
    """
    Derive the tearsheet output slug from an example's file path.

    Parameters
    ----------
    example_file : `str`
        The example's '__file__' value. e.g. '/path/to/sixty_forty.py'.

    Returns
    -------
    `str`
        The hyphenated slug. e.g. 'sixty-forty'.
    """
    basename = os.path.splitext(os.path.basename(example_file))[0]
    return basename.replace('_', '-')


def default_filename(name, output_dir=None, now=None):
    """
    Build the timestamped default output path for a tearsheet.

    Parameters
    ----------
    name : `str`
        The example slug. e.g. 'sixty-forty'.
    output_dir : `str`, optional
        The directory to write into. Defaults to the 'out' directory at the
        repository root, or the QSTRADER_OUTPUT_DIR environment variable.
    now : `datetime.datetime`, optional
        The timestamp to embed. Defaults to the current local time.

    Returns
    -------
    `str`
        The full output path.
        e.g. '<repo>/out/tearsheet-sixty-forty-20260816-152300.png'
    """
    if output_dir is None:
        output_dir = default_output_dir()
    if now is None:
        now = datetime.datetime.now()
    filename = 'tearsheet-%s-%s.png' % (name, now.strftime(TIMESTAMP_FORMAT))
    return os.path.join(output_dir, filename)


def add_arguments(parser):
    """
    Add the shared tearsheet output arguments to an ArgumentParser.

    Parameters
    ----------
    parser : `argparse.ArgumentParser`
        The parser to extend.

    Returns
    -------
    `argparse.ArgumentParser`
        The same parser, for chaining.
    """
    parser.add_argument(
        '--show',
        action='store_true',
        help="차트를 인터랙티브 창으로 표시합니다. (기본값: 표시하지 않고 파일로만 저장)"
    )
    parser.add_argument(
        '--no-save',
        dest='save',
        action='store_false',
        help="차트를 파일로 저장하지 않습니다."
    )
    parser.add_argument(
        '-o', '--output',
        default=None,
        metavar='PATH',
        help=(
            "저장할 파일 경로를 직접 지정합니다. "
            "(기본값: <output-dir>/tearsheet-<example>-<yyyymmdd-hhmmss>.png)"
        )
    )
    parser.add_argument(
        '--output-dir',
        default=None,
        metavar='DIR',
        help=(
            "차트를 저장할 디렉토리. "
            "(기본값: 환경변수 QSTRADER_OUTPUT_DIR 또는 '.env'의 값, "
            "없으면 저장소 루트의 'out')"
        )
    )
    return parser


def parse_args(example_file, description=None, argv=None):
    """
    Parse the shared tearsheet output arguments for an example script.

    Parameters
    ----------
    example_file : `str`
        The example's '__file__' value, used to build the default filename.
    description : `str`, optional
        The description shown by '--help'.
    argv : `list[str]`, optional
        The argument list to parse. Defaults to 'sys.argv[1:]'.

    Returns
    -------
    `argparse.Namespace`
        The parsed arguments, with an added 'example_name' attribute.
    """
    # 예제 본문이 QSTRADER_CSV_DATA_DIR 등을 읽기 전에 '.env'를 반영한다.
    # 셸에 이미 설정된 값은 덮어쓰지 않는다.
    load_env_file()

    name = example_name(example_file)
    parser = argparse.ArgumentParser(
        prog='%s.py' % name.replace('-', '_'),
        description=description or (
            "QSTrader 예제 백테스트를 실행하고 tearsheet 차트를 생성합니다."
        ),
        epilog=(
            '사용 예시:\n'
            '  python examples/%(f)s.py\n'
            '  python examples/%(f)s.py --show\n'
            '  python examples/%(f)s.py --show --no-save\n'
            '  python examples/%(f)s.py --output out/my-tearsheet.png\n'
            '  python examples/%(f)s.py --output-dir /path/to/dir\n'
        ) % {'f': name.replace('-', '_')},
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_arguments(parser)
    args = parser.parse_args(argv)
    args.example_name = name
    return args


def output_tearsheet(tearsheet, args):
    """
    Save and/or display a tearsheet according to the parsed arguments.

    When the tearsheet is not being displayed, the non-interactive 'Agg'
    Matplotlib backend is selected so that the examples run on headless
    machines with no display available.

    Parameters
    ----------
    tearsheet : `TearsheetStatistics`
        The tearsheet to render.
    args : `argparse.Namespace`
        The arguments returned by 'parse_args'.

    Returns
    -------
    `str` or `None`
        The path the tearsheet was saved to, or None if it was not saved.
    """
    if not args.show:
        # 헤드리스 환경에서 디스플레이를 요구하지 않는 백엔드로 전환
        import matplotlib
        matplotlib.use('Agg')

    filename = None
    if args.save:
        filename = args.output
        if filename is None:
            filename = default_filename(
                args.example_name, output_dir=args.output_dir
            )

    tearsheet.plot_results(filename=filename, show=args.show)
    return filename
