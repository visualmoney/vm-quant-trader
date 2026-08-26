#!/bin/sh
#
# What CI runs, so that a push does not have to be the thing that
# tells you. Run this before pushing.
#
#   ./scripts/check.sh
#
# Lint first, though CI does it second: it takes a moment where the
# suite takes seconds, and a style break is the cheapest failure to
# find early. Which of them runs first does not matter; running only
# one of them does. A green suite says nothing about the lint, and a
# suite run without coverage says nothing about the floor .coveragerc
# holds -- both have been pushed on that assumption.
#
# Assumes 'uv sync' has been run. CI additionally passes --locked,
# which fails if uv.lock has drifted from pyproject.toml; that is a
# reproducibility check for the runner rather than for a working tree.
set -e

echo '--- ruff'
uv run ruff check

echo '--- pytest (with coverage, which enforces .coveragerc fail_under)'
uv run pytest --cov=vmtrader
