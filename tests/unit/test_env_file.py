import os

import pytest

from vmtrader.env_file import (
    find_env_file, load_env_file, parse_env_file, parse_env_value
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('value', 'value'),
        ('  spaced value  ', 'spaced value'),
        ('"quoted value"', 'quoted value'),
        ("'quoted value'", 'quoted value'),
        ('"value # with hash"', 'value # with hash'),
        ('value  # trailing comment', 'value'),
        ('va#lue', 'va#lue'),
        ('', ''),
    ]
)
def test_parse_env_value(raw, expected):
    """
    Tests that quoting and trailing inline comments are stripped from a
    raw '.env' value, while a '#' inside a value is preserved.
    """
    assert parse_env_value(raw) == expected


def test_parse_env_file(tmp_path):
    """
    Tests that a '.env' file is parsed into the expected key/value pairs,
    with comments, blank lines, 'export' prefixes and malformed lines all
    handled.
    """
    env_path = tmp_path / '.env'
    env_path.write_text(
        '# a comment\n'
        '\n'
        'VMTRADER_CSV_DATA_DIR=data\n'
        'export EXPORTED=exported_value\n'
        '  SPACED  =  spaced value\n'
        'QUOTED="quoted value"\n'
        'INLINE=value  # trailing comment\n'
        'EMPTY=\n'
        'NO_EQUALS_SIGN\n'
        '=no_key\n',
        encoding='utf-8'
    )

    assert parse_env_file(str(env_path)) == {
        'VMTRADER_CSV_DATA_DIR': 'data',
        'EXPORTED': 'exported_value',
        'SPACED': 'spaced value',
        'QUOTED': 'quoted value',
        'INLINE': 'value',
        'EMPTY': '',
    }


def test_load_env_file_sets_missing_variables(tmp_path, monkeypatch):
    """
    Tests that variables absent from the environment are applied.
    """
    env_path = tmp_path / '.env'
    env_path.write_text('VMTRADER_TEST_VALUE=from_file\n', encoding='utf-8')
    monkeypatch.delenv('VMTRADER_TEST_VALUE', raising=False)

    applied = load_env_file(str(env_path), verbose=False)

    assert applied == {'VMTRADER_TEST_VALUE': 'from_file'}
    assert os.environ['VMTRADER_TEST_VALUE'] == 'from_file'


def test_load_env_file_does_not_override_environment(tmp_path, monkeypatch):
    """
    Tests that a variable already set in the environment takes precedence
    over the value in the '.env' file.
    """
    env_path = tmp_path / '.env'
    env_path.write_text('VMTRADER_TEST_VALUE=from_file\n', encoding='utf-8')
    monkeypatch.setenv('VMTRADER_TEST_VALUE', 'from_environment')

    applied = load_env_file(str(env_path), verbose=False)

    assert applied == {}
    assert os.environ['VMTRADER_TEST_VALUE'] == 'from_environment'


def test_load_env_file_absent(tmp_path):
    """
    Tests that a missing '.env' file is a no-op rather than an error.
    """
    assert load_env_file(str(tmp_path / 'does_not_exist.env'), verbose=False) == {}


def test_find_env_file_walks_upwards(tmp_path, monkeypatch):
    """
    Tests that a '.env' file is located in a parent directory when it is
    not present in the starting directory.
    """
    monkeypatch.delenv('VMTRADER_ENV_FILE', raising=False)
    (tmp_path / '.env').write_text('VMTRADER_TEST_VALUE=parent\n', encoding='utf-8')
    nested = tmp_path / 'nested' / 'deeper'
    nested.mkdir(parents=True)

    assert find_env_file(str(nested)) == str(tmp_path / '.env')


def test_find_env_file_honours_explicit_path(tmp_path, monkeypatch):
    """
    Tests that VMTRADER_ENV_FILE overrides the directory search, and that
    an explicit path pointing at a missing file yields None.
    """
    explicit = tmp_path / 'custom.env'
    explicit.write_text('VMTRADER_TEST_VALUE=explicit\n', encoding='utf-8')

    monkeypatch.setenv('VMTRADER_ENV_FILE', str(explicit))
    assert find_env_file(str(tmp_path)) == str(explicit)

    monkeypatch.setenv('VMTRADER_ENV_FILE', str(tmp_path / 'missing.env'))
    assert find_env_file(str(tmp_path)) is None
