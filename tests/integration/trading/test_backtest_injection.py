import os

import pandas as pd
import pytest
import pytz

from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.portcon.optimiser.equal_weight import (
    EqualWeightPortfolioOptimiser
)
from vmtrader.trading.backtest import BacktestTradingSession


def _run(etf_filepath, **kwargs):
    os.environ['VMTRADER_CSV_DATA_DIR'] = etf_filepath

    universe = StaticUniverse(['EQ:ABC', 'EQ:DEF'])

    backtest = BacktestTradingSession(
        pd.Timestamp('2019-01-01 00:00:00', tz=pytz.UTC),
        pd.Timestamp('2019-01-31 23:59:00', tz=pytz.UTC),
        universe,
        FixedSignalsAlphaModel({'EQ:ABC': 0.6, 'EQ:DEF': 0.4}),
        portfolio_id='000001',
        rebalance='weekly',
        rebalance_weekday='WED',
        long_only=True,
        cash_buffer_percentage=0.05,
        **kwargs
    )
    backtest.run(results=False)
    return backtest


def test_an_injected_optimiser_changes_the_allocation(etf_filepath):
    """
    Checks that a supplied PortfolioOptimiser actually drives the backtest,
    by using the equal weight optimiser to override the alpha model's 60/40
    signal and confirming the resulting allocation is even.

    EqualWeightPortfolioOptimiser has shipped with the package since before
    0.3.0 but could not be reached through BacktestTradingSession until
    0.3.13, because QuantTradingSystem constructed the fixed weight optimiser
    itself.
    """
    default = _run(etf_filepath)
    equal_weight = _run(etf_filepath, optimiser=EqualWeightPortfolioOptimiser())

    default_alloc = default.get_target_allocations().iloc[-1]
    equal_alloc = equal_weight.get_target_allocations().iloc[-1]

    assert default_alloc['EQ:ABC'] == pytest.approx(0.6)
    assert default_alloc['EQ:DEF'] == pytest.approx(0.4)

    assert equal_alloc['EQ:ABC'] == pytest.approx(0.5)
    assert equal_alloc['EQ:DEF'] == pytest.approx(0.5)


def test_an_injected_execution_algo_is_used(etf_filepath):
    """
    Checks that a supplied ExecutionAlgorithm reaches the execution handler
    and that discarding every order leaves the portfolio untraded.
    """
    from vmtrader.execution.execution_algo.execution_algo import (
        ExecutionAlgorithm
    )

    class DiscardAllOrders(ExecutionAlgorithm):
        def __call__(self, dt, initial_orders):
            return []

    backtest = _run(etf_filepath, execution_algo=DiscardAllOrders())

    assert backtest.broker.portfolios['000001'].portfolio_to_dict() == {}
