# file: examples/env_file.py
"""
Minimal '.env' file loading for the QSTrader examples.

This deliberately avoids a dependency on 'python-dotenv': the examples only
need to pick up a handful of QSTrader settings such as QSTRADER_CSV_DATA_DIR
and QSTRADER_OUTPUT_DIR, and QSTrader itself reads them straight from
'os.environ'.

Variables already present in the environment always win, so an explicit
'export QSTRADER_CSV_DATA_DIR=...' or a variable set by the shell is never
overwritten by the '.env' file.

The '.env' file is searched for in the following order, and the first one
found is used:

1. The path in the QSTRADER_ENV_FILE environment variable, if set.
2. '.env' in the current working directory.
3. '.env' in the repository root (the parent of this 'examples' directory).

Supported syntax
----------------
    # comments and blank lines are ignored
    KEY=value
    export KEY=value            # an 'export' prefix is allowed
    KEY = value                 # surrounding whitespace is stripped
    KEY="quoted value"          # matching quotes are stripped
    KEY=value  # trailing comment on an unquoted value is stripped
"""

import os


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENV_FILENAME = '.env'


def find_env_file():
    """
    Locate the '.env' file to load, if any.

    Returns
    -------
    `str` or `None`
        The path of the first '.env' file found, or None if there is none.
    """
    explicit = os.environ.get('QSTRADER_ENV_FILE')
    if explicit:
        return explicit if os.path.isfile(explicit) else None

    candidates = [
        os.path.join(os.getcwd(), ENV_FILENAME),
        os.path.join(REPO_ROOT, ENV_FILENAME),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def parse_env_value(raw):
    """
    Strip quoting and any trailing inline comment from a raw '.env' value.

    Parameters
    ----------
    raw : `str`
        The text to the right of the first '=' on the line.

    Returns
    -------
    `str`
        The cleaned value.
    """
    value = raw.strip()

    # 따옴표로 감싼 값은 그대로 사용하고, 따옴표만 제거한다
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]

    # 따옴표가 없는 값은 공백 뒤의 인라인 주석을 잘라낸다
    for index, char in enumerate(value):
        if char == '#' and (index == 0 or value[index - 1].isspace()):
            value = value[:index]
            break
    return value.strip()


def parse_env_file(path):
    """
    Parse a '.env' file into an ordered dictionary of key/value pairs.

    Malformed lines (those with no '=' or no key) are skipped rather than
    raising, so that a stray line cannot stop an example from running.

    Parameters
    ----------
    path : `str`
        The path of the '.env' file.

    Returns
    -------
    `dict{str: str}`
        The parsed key/value pairs.
    """
    values = {}
    with open(path, encoding='utf-8') as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[len('export '):]
            if '=' not in line:
                continue
            key, _, raw = line.partition('=')
            key = key.strip()
            if not key:
                continue
            values[key] = parse_env_value(raw)
    return values


def load_env_file(path=None, verbose=True):
    """
    Load a '.env' file into 'os.environ' without overriding existing values.

    Parameters
    ----------
    path : `str`, optional
        The '.env' file to load. Defaults to the first file located by
        'find_env_file'.
    verbose : `Boolean`, optional
        Whether to print a one-line summary of what was applied.
        Defaults to True.

    Returns
    -------
    `dict{str: str}`
        The variables that were actually applied to 'os.environ'. Variables
        already set in the environment are excluded, as is everything when
        no '.env' file exists.
    """
    if path is None:
        path = find_env_file()
    if path is None or not os.path.isfile(path):
        return {}

    applied = {}
    for key, value in parse_env_file(path).items():
        if key in os.environ:
            # 셸에서 이미 지정한 값이 우선한다
            continue
        os.environ[key] = value
        applied[key] = value

    if verbose and applied:
        print("Loaded %s from %s" % (', '.join(sorted(applied)), path))
    return applied
