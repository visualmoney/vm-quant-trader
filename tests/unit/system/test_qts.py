from unittest.mock import Mock

from qstrader.execution.execution_algo.execution_algo import ExecutionAlgorithm
from qstrader.execution.execution_algo.market_order import (
    MarketOrderExecutionAlgorithm
)
from qstrader.portcon.optimiser.equal_weight import (
    EqualWeightPortfolioOptimiser
)
from qstrader.portcon.optimiser.fixed_weight import (
    FixedWeightPortfolioOptimiser
)
from qstrader.system.qts import QuantTradingSystem


class NullExecutionAlgorithm(ExecutionAlgorithm):
    """A stand-in used only to check that injection reaches the handler."""

    def __call__(self, dt, initial_orders):
        return []


def _quant_trading_system(**kwargs):
    return QuantTradingSystem(
        Mock(), Mock(), '1234', Mock(), Mock(),
        long_only=True, cash_buffer_percentage=0.05, **kwargs
    )


def test_defaults_are_used_when_nothing_is_supplied():
    """
    Checks that omitting the optimiser and execution algorithm still produces
    the pair the system has always defaulted to.
    """
    qts = _quant_trading_system()

    assert isinstance(
        qts.portfolio_construction_model.optimiser, FixedWeightPortfolioOptimiser
    )
    assert isinstance(
        qts.execution_handler.execution_algo, MarketOrderExecutionAlgorithm
    )


def test_a_supplied_optimiser_and_execution_algo_are_used():
    """
    Checks that both are injectable, as the fee model already was.

    Until 0.3.13 they were constructed inside _initialise_models with no way
    to supply either, so EqualWeightPortfolioOptimiser shipped with the
    package but could not be reached through QuantTradingSystem at all.
    """
    optimiser = EqualWeightPortfolioOptimiser()
    execution_algo = NullExecutionAlgorithm()

    qts = _quant_trading_system(
        optimiser=optimiser, execution_algo=execution_algo
    )

    assert qts.portfolio_construction_model.optimiser is optimiser
    assert qts.execution_handler.execution_algo is execution_algo
