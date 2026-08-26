"""
Pin the leaf status of the messaging package.

Both the broker and the strategy executor import this vocabulary, so
the moment it imports either of them back, the import graph has a
cycle and the vocabulary has an owner. The package stays importable
by everyone precisely because it imports nothing of the engine, and
that is asserted here rather than trusted -- the failure would be
silent until the cycle closes.
"""

import ast
import os


PACKAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ))),
    'vmtrader', 'messaging'
)

# The whole allowance: the standard library, pandas for timestamps,
# and the package's own modules. Nothing else, and never the engine.
# 'typing' is here for ClassVar, which is what keeps a topic name a
# property of the event type instead of a constructor argument.
ALLOWED_TOP_LEVEL = frozenset(
    ['dataclasses', 'queue', 'threading', 'typing', 'pandas']
)
ALLOWED_INTERNAL_PREFIX = 'vmtrader.messaging'


def _imports(path):
    """
    Yield (lineno, module) for every import in a source file.

    Parameters
    ----------
    path : `str`
        The file to read.

    Yields
    ------
    `tuple[int, str]`
        Line number and the imported module path.
    """
    with open(path) as handle:
        tree = ast.parse(handle.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


def test_messaging_imports_nothing_from_the_engine():
    """
    Tests that the vocabulary has no owner.

    An import of broker or alpha_model from here would couple both
    actors through their shared vocabulary -- the exact dependency
    the package exists to dissolve.
    """
    violations = []
    for filename in sorted(os.listdir(PACKAGE_DIR)):
        if not filename.endswith('.py'):
            continue
        path = os.path.join(PACKAGE_DIR, filename)
        for lineno, module in _imports(path):
            top = module.split('.')[0]
            if module.startswith(ALLOWED_INTERNAL_PREFIX):
                continue
            if top not in ALLOWED_TOP_LEVEL:
                violations.append(f'{filename}:{lineno} imports {module}')
    assert violations == []
