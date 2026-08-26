from unittest.mock import Mock

import pandas as pd

from vmtrader.execution.execution_algo.execution_algo import ExecutionAlgorithm
from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.messaging import TargetWeights
from vmtrader.portcon.pcm import PortfolioConstructionModel
from vmtrader.execution.execution_algo.market_order import (
    MarketOrderExecutionAlgorithm
)
from vmtrader.portcon.optimiser.equal_weight import (
    EqualWeightPortfolioOptimiser
)
from vmtrader.portcon.optimiser.fixed_weight import (
    FixedWeightPortfolioOptimiser
)
from vmtrader.system.qts import QuantTradingSystem


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


class UnreachableBroker:
    """
    A collaborator that refuses to be read at all.

    Any attribute access raises, so a test using one proves the code
    under it never reached the thing -- not that it happened not to
    this time. Used for the broker and, in the venue test below, for
    the data handler: the two are different boundaries but the same
    kind of proof.
    """

    def __getattr__(self, name):
        raise AssertionError(
            'the decision half reached something it must not: %s' % name
        )


def test_deciding_weights_never_reaches_the_broker():
    """
    Tests the boundary decisions 9 and 10 are built on.

    Target weights are dimensionless, so choosing them needs no cash,
    no holdings and no open orders. That is what lets this half run on
    a thread that owns none of them, and what makes carrying an
    account snapshot across unnecessary. A step added here that reads
    the account belongs on the other side, and this fails loudly the
    day one is.
    """
    qts = _quant_trading_system()
    qts.portfolio_construction_model.broker = UnreachableBroker()
    qts.portfolio_construction_model.order_sizer = UnreachableBroker()
    qts.portfolio_construction_model.alpha_model = (
        lambda dt: {'EQ:005930': 0.6, 'EQ:000660': 0.4}
    )
    qts.portfolio_construction_model.risk_model = None

    command = qts.decide_weights(pd.Timestamp('2026-08-24 09:10'))

    assert command.as_dict() == {'EQ:005930': 0.6, 'EQ:000660': 0.4}


def test_deciding_weights_never_reaches_the_venue():
    """
    Tests the property the two-actor split is sold on.

    Section 3 promises that a strategy taking five seconds does not
    delay a fill being recorded. The gateway's throttle holds a
    module-level lock across its sleep, so the moment the deciding half
    asks the venue for a price it is contending for the same lock order
    submission needs -- and separate data handler instances would not
    help, because the lock is not per-instance (report 20260826-01, M3
    and 20260826-02, S5).

    It holds today: the optimisers and the shipped alpha models keep a
    data handler for interface parity and never call it, and signals
    are updated on the other plane. It is not enforced anywhere, which
    is why an alpha model that reads a price -- entirely legal to
    write -- would break it silently. This is what says so.

    Unlike the sibling test above, the alpha model here is a real one
    rather than a lambda: what is being checked is what actually runs,
    not what the plumbing around it does.
    """
    unreachable = UnreachableBroker()
    pcm = PortfolioConstructionModel(
        unreachable, 'live', StaticUniverse(['EQ:005930', 'EQ:000660']),
        unreachable,
        FixedWeightPortfolioOptimiser(data_handler=unreachable),
        alpha_model=FixedSignalsAlphaModel(
            {'EQ:005930': 0.6, 'EQ:000660': 0.4}
        ),
        data_handler=unreachable
    )

    weights = pcm.decide_weights(pd.Timestamp('2026-08-24 09:10'))

    assert weights == {'EQ:005930': 0.6, 'EQ:000660': 0.4}


def test_a_decision_is_carried_as_a_sorted_immutable_message():
    """
    Tests that the seam carries a message, not a mutable dictionary.

    The two halves become separate threads with a queue between them,
    so what crosses has to be safe to hand over: ordered by content so
    replays match, and unable to change underneath the consumer.
    """
    qts = _quant_trading_system()
    working = {'EQ:005930': 0.6, 'EQ:000660': 0.4}
    qts.portfolio_construction_model.alpha_model = lambda dt: working
    qts.portfolio_construction_model.risk_model = None
    qts.portfolio_construction_model.optimiser = (
        lambda dt, initial_weights=None: initial_weights
    )

    command = qts.decide_weights(pd.Timestamp('2026-08-24 09:10'))
    working['EQ:005930'] = 99.0

    assert command.weights == (('EQ:000660', 0.4), ('EQ:005930', 0.6))
    assert command.as_dict()['EQ:005930'] == 0.6


def test_sizing_uses_the_command_s_own_timestamp():
    """
    Tests that a command sizes the rebalance it was created for.

    Once a queue sits at the seam a command can be handled later than
    it was made. Reading a clock at that point would size a different
    moment than the one the weights were chosen for.
    """
    qts = _quant_trading_system()
    qts.portfolio_construction_model = Mock()
    qts.portfolio_construction_model.build_orders.return_value = []
    qts.execution_handler = Mock()

    decided_at = pd.Timestamp('2026-08-24 09:10')
    qts.size_and_submit(
        TargetWeights(dt=decided_at, weights=(('EQ:005930', 1.0),))
    )

    assert qts.portfolio_construction_model.build_orders.call_args[0][0] == (
        decided_at
    )
    assert qts.execution_handler.call_args[0][0] == decided_at
