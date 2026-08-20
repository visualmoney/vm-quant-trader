from abc import ABC
import inspect

import pandas as pd
import pytest

from vmtrader.alpha_model.alpha_model import AlphaModel
from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.asset import Asset
from vmtrader.asset.equity import Equity
from vmtrader.asset.universe.universe import Universe
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.broker.broker import Broker
from vmtrader.broker.fee_model.fee_model import FeeModel
from vmtrader.broker.fee_model.zero_fee_model import ZeroFeeModel
from vmtrader.exchange.exchange import Exchange
from vmtrader.execution.execution_algo.execution_algo import ExecutionAlgorithm
from vmtrader.execution.execution_algo.market_order import (
    MarketOrderExecutionAlgorithm
)
from vmtrader.portcon.optimiser.optimiser import PortfolioOptimiser
from vmtrader.portcon.optimiser.equal_weight import (
    EqualWeightPortfolioOptimiser
)
from vmtrader.portcon.optimiser.fixed_weight import (
    FixedWeightPortfolioOptimiser
)
from vmtrader.portcon.order_sizer.order_sizer import OrderSizer
from vmtrader.risk_model.risk_model import RiskModel
from vmtrader.signals.signal import Signal
from vmtrader.simulation.sim_engine import SimulationEngine
from vmtrader.statistics.statistics import Statistics
from vmtrader.statistics.tearsheet import TearsheetStatistics
from vmtrader.system.rebalance.rebalance import Rebalance
from vmtrader.system.rebalance.buy_and_hold import BuyAndHoldRebalance
from vmtrader.system.rebalance.daily import DailyRebalance
from vmtrader.system.rebalance.end_of_month import EndOfMonthRebalance
from vmtrader.system.rebalance.weekly import WeeklyRebalance
from vmtrader.trading.trading_session import TradingSession


# Every abstract base class in the package. Prior to the Python 3 conversion
# these declared '__metaclass__ = ABCMeta', which is a Python 2 idiom and a
# silent no-op under Python 3, so none of the @abstractmethod markers were
# ever enforced.
ABSTRACT_BASE_CLASSES = [
    AlphaModel,
    Asset,
    Broker,
    Exchange,
    ExecutionAlgorithm,
    FeeModel,
    OrderSizer,
    PortfolioOptimiser,
    Rebalance,
    RiskModel,
    Signal,
    SimulationEngine,
    Statistics,
    TradingSession,
    Universe,
]

# Asset declares no abstract methods, so it stays instantiable by design.
ENFORCING_BASE_CLASSES = [
    cls for cls in ABSTRACT_BASE_CLASSES if cls is not Asset
]


@pytest.mark.parametrize(
    "cls", ABSTRACT_BASE_CLASSES, ids=lambda c: c.__name__
)
def test_is_a_real_abc(cls):
    """
    Each base class uses abc.ABC, so that @abstractmethod is enforced,
    rather than the Python 2 '__metaclass__' assignment that never was.
    """
    assert inspect.isabstract(cls) or not cls.__abstractmethods__
    assert issubclass(cls, ABC)
    assert not hasattr(cls, '__metaclass__')


@pytest.mark.parametrize(
    "cls", ENFORCING_BASE_CLASSES, ids=lambda c: c.__name__
)
def test_cannot_instantiate_abstract_base_class(cls):
    """
    Instantiating a base class that still has unimplemented abstract
    methods raises TypeError.
    """
    with pytest.raises(TypeError, match='abstract'):
        cls()


@pytest.mark.parametrize(
    "cls", ENFORCING_BASE_CLASSES, ids=lambda c: c.__name__
)
def test_incomplete_subclass_cannot_be_instantiated(cls):
    """
    A subclass that implements none of the abstract methods inherits
    them, and so is itself abstract.
    """
    incomplete = type('Incomplete%s' % cls.__name__, (cls,), {})
    with pytest.raises(TypeError, match='abstract'):
        incomplete()


def test_asset_declares_no_abstract_methods():
    """
    Asset carries no abstract methods, so unlike the other base classes
    it remains directly instantiable. This pins that deliberate difference.
    """
    assert Asset.__abstractmethods__ == frozenset()
    assert Asset() is not None


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Equity('SPDR S&P 500 ETF Trust', 'SPY'),
        lambda: StaticUniverse(['EQ:SPY']),
        lambda: ZeroFeeModel(),
        lambda: MarketOrderExecutionAlgorithm(),
        lambda: EqualWeightPortfolioOptimiser(),
        lambda: FixedSignalsAlphaModel({'EQ:SPY': 1.0}),
        lambda: TearsheetStatistics(None, title='title'),
        lambda: BuyAndHoldRebalance(pd.Timestamp('2020-01-01', tz='UTC')),
    ],
)
def test_concrete_subclasses_remain_instantiable(factory):
    """
    Turning enforcement on must not make any shipped concrete class
    uninstantiable.
    """
    assert factory() is not None


def test_tearsheet_implements_the_full_statistics_interface():
    """
    TearsheetStatistics previously implemented only get_results() and
    plot_results(); update() and save() are part of the interface too.
    """
    assert TearsheetStatistics.__abstractmethods__ == frozenset()
    for name in ('update', 'get_results', 'plot_results', 'save'):
        assert callable(getattr(TearsheetStatistics, name))


def test_rebalance_subclasses_implement_generate_rebalances():
    """
    The Rebalance contract is _generate_rebalances(), which populates the
    'rebalances' attribute that BacktestTradingSession reads.
    """
    for cls in (
        BuyAndHoldRebalance, DailyRebalance, EndOfMonthRebalance,
        WeeklyRebalance
    ):
        assert issubclass(cls, Rebalance)
        assert '_generate_rebalances' in vars(cls)
        assert cls.__abstractmethods__ == frozenset()


def test_statistics_get_results_signature_matches_implementation():
    """
    The base get_results() must accept 'equity_df'. It previously declared
    no parameters while TearsheetStatistics required one, so the only
    implementation did not satisfy the interface it declared.
    """
    base = inspect.signature(Statistics.get_results).parameters
    assert 'equity_df' in base
    impl = inspect.signature(TearsheetStatistics.get_results).parameters
    assert impl.keys() == base.keys()


def test_portfolio_optimiser_signature_matches_implementations():
    """
    The base __call__ must accept 'initial_weights', which is how
    PortfolioConstructionModel invokes the optimiser.
    """
    base = inspect.signature(PortfolioOptimiser.__call__).parameters
    assert 'initial_weights' in base
    for cls in (EqualWeightPortfolioOptimiser, FixedWeightPortfolioOptimiser):
        assert inspect.signature(cls.__call__).parameters.keys() == base.keys()


def test_broker_requires_update():
    """
    'update(dt)' is part of the Broker contract, not an informal
    convention.

    The execution handler calls it after every order and the trading
    session calls it on every event, so a Broker that omits it used to
    instantiate cleanly and then fail with AttributeError partway
    through a session. Making it abstract moves that failure to
    construction, where a live broker cannot take it into the market.
    """
    assert 'update' in Broker.__abstractmethods__

    class BrokerWithoutUpdate(Broker):
        pass

    with pytest.raises(TypeError, match='update'):
        BrokerWithoutUpdate()
