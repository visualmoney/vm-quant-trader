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


def test_the_budget_survives_the_sizer_normalising_the_weights():
    """
    Tests the defect the first real run exposed.

    The sizer rescales the weight vector to sum to one, so scaling
    weights down does not reduce exposure — asking for a million won
    produced two orders worth 237 million each. What does bound it is
    the cash buffer, and this is where that is computed.
    """
    weights, cash_buffer, _ = smoke.smoke_plan(
        ['EQ:005930', 'EQ:000660'], budget=1000000.0,
        total_equity=500000000.0, holdings={}
    )
    assert weights == {'EQ:005930': 500000.0, 'EQ:000660': 500000.0}

    # What the sizer will actually deploy, by its own arithmetic.
    deployed = 500000000.0 * (1.0 - cash_buffer)
    assert deployed == pytest.approx(1000000.0)

    # And after normalisation each name still receives its half.
    total = sum(weights.values())
    for value in weights.values():
        assert deployed * (value / total) == pytest.approx(500000.0)


def test_holdings_outside_the_universe_are_carried_not_sold():
    """
    Tests the other defect the first run exposed.

    Portfolio construction zeroes anything absent from the target, so a
    two-name smoke against an account holding other things liquidates
    them — which is exactly what happened. Held names are carried at
    their current value, which sizes to no trade.
    """
    holdings = {'EQ:069500': 433540.0, 'EQ:360750': 560889.0}
    weights, cash_buffer, universe = smoke.smoke_plan(
        ['EQ:005930'], budget=1000000.0, total_equity=500000000.0,
        holdings=holdings
    )

    assert 'EQ:069500' in universe and 'EQ:360750' in universe
    deployed = 500000000.0 * (1.0 - cash_buffer)
    total = sum(weights.values())
    for symbol, value in holdings.items():
        # Target equals current value, so the increment is nothing.
        assert deployed * (weights[symbol] / total) == pytest.approx(value)


def test_a_held_name_inside_the_universe_is_topped_up_by_the_budget():
    """
    Tests that trading a name already held adds the budget to it
    rather than replacing the position.
    """
    weights, _, universe = smoke.smoke_plan(
        ['EQ:005930'], budget=1000000.0, total_equity=500000000.0,
        holdings={'EQ:005930': 200000.0}
    )
    assert weights == {'EQ:005930': 1200000.0}
    assert universe == ['EQ:005930']


def test_a_budget_larger_than_the_account_is_refused():
    """
    Tests that an oversized budget stops rather than silently
    deploying everything.
    """
    with pytest.raises(smoke.SmokeError, match='Lower --budget'):
        smoke.smoke_plan(
            ['EQ:005930'], budget=99999999.0, total_equity=1000000.0,
            holdings={}
        )


def test_an_empty_account_is_refused_rather_than_divided_by():
    """
    Tests that a zero-equity account fails with an explanation instead
    of a division error.
    """
    with pytest.raises(smoke.SmokeError, match='no equity'):
        smoke.smoke_plan(
            ['EQ:005930'], budget=1000.0, total_equity=0.0, holdings={}
        )


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


def test_the_session_clock_lands_inside_market_hours():
    """
    Tests the clock the safety stage runs its checks on.

    Two of those checks sit behind the market-hours gate in
    'submit_order'. Run after the close they would be refused for being
    out of hours instead — the short check passing for the wrong reason
    and the kill switch never firing at all.
    """
    from vmtrader.exchange.krx_exchange import KrxExchange

    exchange = KrxExchange()
    for now in [
        pd.Timestamp('2026-08-20 16:00:00'),   # after the close
        pd.Timestamp('2026-08-20 07:00:00'),   # before the open
        pd.Timestamp('2026-08-22 11:00:00'),   # Saturday
        pd.Timestamp('2026-08-23 11:00:00'),   # Sunday
        pd.Timestamp('2026-08-20 12:00:00'),   # mid-session
    ]:
        session = smoke.last_session_timestamp(now)
        assert exchange.is_open_at_datetime(session), now
        assert session <= now


def test_the_session_clock_does_not_jump_to_a_future_session():
    """
    Tests that a run before the open uses yesterday, not today.

    Asking the venue about a session that has not happened yet would
    be a different kind of wrong answer.
    """
    session = smoke.last_session_timestamp(
        pd.Timestamp('2026-08-20 07:00:00')
    )
    assert session.date() == pd.Timestamp('2026-08-19').date()
