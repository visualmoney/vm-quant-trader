"""
Pin the two import boundaries the live plane depends on.

The first is that a vendor's SDK is never imported by the package.
That is what lets the whole suite run with no broker library installed
and no network reachable, and it is asserted here rather than trusted,
because the failure is silent until a machine without the SDK tries to
run a backtest.

The second is that vendor-specific code is imported only by vendor
code. Before the live infrastructure moved out of 'broker/kis/', the
engine's own live session and live data handler imported from it, so
the neutral half of the live plane could not be reached without the
KIS half coming along. LiveDataHandler raised the KIS parser's
exception for a price it could not obtain, which a second venue would
have inherited.

Both are checked by reading the source rather than by importing, so a
violation is reported as the file and line that introduced it.
"""

import ast
import os

import pytest


PACKAGE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'vmtrader'
)

# Where a vendor's own code is allowed to live. Anything under this
# path may name that vendor; nothing else may.
VENDOR_PACKAGES = ('vmtrader/broker/kis',)

# Top-level modules belonging to a broker's SDK. The gateway script
# imports these, which is the point: it sits outside the package.
VENDOR_SDK_MODULES = frozenset([
    'kis_auth',
    'domestic_stock_functions',
])


def _package_modules():
    """
    Yield every source file in the package with its repo-relative path.

    Returns
    -------
    `list[tuple[str, str]]`
        (relative path, absolute path) pairs.
    """
    modules = []
    for dirpath, _, filenames in os.walk(PACKAGE_ROOT):
        if '__pycache__' in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith('.py'):
                continue
            absolute = os.path.join(dirpath, filename)
            relative = os.path.relpath(
                absolute, os.path.dirname(PACKAGE_ROOT)
            ).replace(os.sep, '/')
            modules.append((relative, absolute))
    return sorted(modules)


def _imported_modules(path):
    """
    Return every module name imported by a source file, with its line.

    Parameters
    ----------
    path : `str`
        Absolute path to the source file.

    Returns
    -------
    `list[tuple[str, int]]`
        (dotted module name, line number) pairs. A 'from x import y'
        contributes both 'x' and 'x.y', since the vendor name may sit
        on either side.
    """
    with open(path, encoding='utf-8') as handle:
        tree = ast.parse(handle.read(), filename=path)

    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None:
                continue
            imported.append((node.module, node.lineno))
            for alias in node.names:
                imported.append(
                    ('%s.%s' % (node.module, alias.name), node.lineno)
                )
    return imported


MODULES = _package_modules()


@pytest.mark.parametrize(
    'relative,absolute', MODULES, ids=[m[0] for m in MODULES]
)
def test_the_package_never_imports_a_broker_sdk(relative, absolute):
    """
    No module in the package may import a vendor SDK.

    The SDK is reached only through the BrokerClient Protocol, whose
    implementation lives in a gateway script outside the package.
    """
    offenders = [
        (name, lineno)
        for name, lineno in _imported_modules(absolute)
        if name.split('.')[0] in VENDOR_SDK_MODULES
    ]
    assert offenders == [], (
        "%s imports a broker SDK at line(s) %s. The SDK belongs in a "
        "gateway script outside the package; the engine speaks the "
        "BrokerClient Protocol." % (
            relative, ', '.join(str(lineno) for _, lineno in offenders)
        )
    )


@pytest.mark.parametrize(
    'relative,absolute', MODULES, ids=[m[0] for m in MODULES]
)
def test_only_vendor_code_imports_vendor_code(relative, absolute):
    """
    Vendor-specific modules are imported only from within that vendor's
    own package.

    The engine core and the neutral live infrastructure must both be
    reachable without naming a broker, so that a second venue needs a
    gateway rather than a fork.
    """
    if any(relative.startswith(pkg) for pkg in VENDOR_PACKAGES):
        pytest.skip('%s is vendor code and may import its own package' % relative)

    offenders = [
        (name, lineno)
        for name, lineno in _imported_modules(absolute)
        if any(
            name.startswith(pkg.replace('/', '.')) for pkg in VENDOR_PACKAGES
        )
    ]
    assert offenders == [], (
        "%s imports vendor-specific code at line(s) %s: %s. Neutral "
        "equivalents live in 'vmtrader/broker/live/'." % (
            relative,
            ', '.join(str(lineno) for _, lineno in offenders),
            ', '.join(sorted({name for name, _ in offenders}))
        )
    )


def test_the_neutral_live_package_names_no_vendor():
    """
    'broker/live/' is the half a second venue reuses unchanged, so it
    must not reach into any vendor package at all.
    """
    for relative, absolute in MODULES:
        if not relative.startswith('vmtrader/broker/live'):
            continue
        for name, lineno in _imported_modules(absolute):
            assert not any(
                name.startswith(pkg.replace('/', '.'))
                for pkg in VENDOR_PACKAGES
            ), (
                "%s:%d imports '%s'. The neutral live package is what a "
                "second venue reuses; a vendor import here forks it."
                % (relative, lineno, name)
            )
