"""
The smoke script places real orders, so the parts that decide how much
and where are tested here rather than discovered on an account.
"""

import argparse
import importlib.util
import os
import sys

import pytest


def _load():
    """
    Import the smoke script from scripts/, which is not a package.
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))),
        'scripts', 'kis_smoke.py'
    )
    spec = importlib.util.spec_from_file_location('kis_smoke', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['kis_smoke'] = module
    spec.loader.exec_module(module)
    return module


smoke = _load()


def _args(**overrides):
    """
    Build a namespace resembling parsed arguments.
    """
    defaults = dict(
        server='vps', ota_home=None, universe=smoke.DEFAULT_UNIVERSE,
        budget=smoke.DEFAULT_BUDGET, max_order_value=600000.0,
        ledger='/tmp/never-created.db', kill_switch='/tmp/never.HALT',
        place_orders=False, settle_minutes=1, poll_seconds=0.0
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.mark.parametrize('server', ['prod', 'real', 'PROD', ''])
def test_only_the_paper_server_is_accepted(server):
    """
    Tests that no argument reaches a real-money account.

    The refusal is in the builder rather than in argument parsing, so
    it holds however the script is called -- including from another
    script that imports it.
    """
    with pytest.raises(smoke.SmokeError, match='paper server'):
        smoke.build_stack(_args(server=server))


def test_the_rebalance_stage_refuses_without_explicit_consent():
    """
    Tests that running the script without thinking cannot trade.

    The check comes before authentication, so a missing flag fails
    immediately rather than after touching the venue.
    """
    with pytest.raises(smoke.SmokeError, match='--place-orders'):
        smoke.stage_rebalance(_args(place_orders=False))


def test_the_budget_is_expressed_as_a_fraction_of_equity():
    """
    Tests that a cash budget becomes weights the sizers understand.
    """
    weights = smoke.scaled_weights(
        ['EQ:005930', 'EQ:000660'], budget=1000000.0, total_equity=10000000.0
    )
    assert weights == {'EQ:005930': 0.05, 'EQ:000660': 0.05}
    assert sum(weights.values()) == pytest.approx(0.1)


def test_a_budget_larger_than_the_account_is_capped():
    """
    Tests that an oversized budget means 'all of it', not leverage.
    """
    weights = smoke.scaled_weights(
        ['EQ:005930', 'EQ:000660'], budget=99999999.0, total_equity=1000000.0
    )
    assert sum(weights.values()) == pytest.approx(1.0)


def test_an_empty_account_is_refused_rather_than_divided_by():
    """
    Tests that a zero-equity account fails with an explanation instead
    of a division error.
    """
    with pytest.raises(smoke.SmokeError, match='no equity'):
        smoke.scaled_weights(['EQ:005930'], budget=1000.0, total_equity=0.0)


def test_the_universe_is_two_liquid_names_by_default():
    """
    Tests the default universe.

    A market order in a thin name fills at a price that says nothing
    about whether the plumbing works.
    """
    assert smoke.DEFAULT_UNIVERSE == ['EQ:005930', 'EQ:000660']
    assert smoke.DEFAULT_MAX_ORDER_VALUE < smoke.DEFAULT_BUDGET


def test_every_stage_is_reachable_from_the_command_line():
    """
    Tests that the stage table and the parser agree.
    """
    assert sorted(smoke.STAGES) == [
        'connect', 'rebalance', 'restart', 'safety'
    ]


def test_the_ledger_default_is_outside_a_deployment_path():
    """
    Tests that a smoke run cannot pollute a real deployment's history.
    """
    assert 'smoke' in smoke.DEFAULT_LEDGER
    assert 'smoke' in smoke.DEFAULT_KILL_SWITCH
