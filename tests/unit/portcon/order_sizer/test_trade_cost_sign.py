"""
The sizer must hand the fee model a signed trade, because a fee model
that charges the two sides differently -- a sell-side-only transaction
tax, say -- cannot otherwise tell which side it is pricing.
"""

from unittest.mock import Mock

import pytest

from vmtrader.broker.fee_model.korea_fee_model import KoreaStockFeeModel
from vmtrader.portcon.order_sizer.dollar_weighted import (
    DollarWeightedCashBufferedOrderSizer
)
from vmtrader.portcon.order_sizer.long_short import (
    LongShortLeveragedOrderSizer
)


def _sizer(cls, fee_model):
    """
    Build a sizer whose broker carries the supplied fee model.

    Parameters
    ----------
    cls : `class`
        The order sizer class to build.
    fee_model : `FeeModel`
        The fee model the broker exposes.

    Returns
    -------
    `OrderSizer`
        The constructed sizer.
    """
    broker = Mock()
    broker.fee_model = fee_model
    if cls is LongShortLeveragedOrderSizer:
        return cls(broker, '1234', Mock(), 1.0)
    return cls(broker, '1234', Mock(), 0.0)


SIZERS = [LongShortLeveragedOrderSizer, DollarWeightedCashBufferedOrderSizer]


@pytest.mark.parametrize('cls', SIZERS)
def test_buy_passes_a_positive_quantity(cls):
    """
    Tests that increasing a position is priced as a buy.
    """
    fee_model = Mock()
    fee_model.calc_total_cost.return_value = 0.0
    sizer = _sizer(cls, fee_model)

    # Hold nothing, target 100,000: a buy.
    sizer._estimate_trade_costs('EQ:005930', 100000.0, 0, 1000.0)

    args = fee_model.calc_total_cost.call_args[0]
    assert args[1] == 100
    assert args[2] > 0.0


@pytest.mark.parametrize('cls', SIZERS)
def test_sell_passes_a_negative_quantity(cls):
    """
    Tests that reducing a position is priced as a sell.
    """
    fee_model = Mock()
    fee_model.calc_total_cost.return_value = 0.0
    sizer = _sizer(cls, fee_model)

    # Hold 100, target 20,000 at 1,000: a sell of 80.
    sizer._estimate_trade_costs('EQ:005930', 20000.0, 100, 1000.0)

    args = fee_model.calc_total_cost.call_args[0]
    assert args[1] == -80
    assert args[2] < 0.0


@pytest.mark.parametrize('cls', SIZERS)
def test_estimated_magnitude_is_unchanged_for_symmetric_fee_models(cls):
    """
    Tests that a fee model which ignores the side sees no change.

    Every fee model bundled before this one prices 'abs(consideration)',
    so signing the arguments must leave existing backtests identical.
    """
    fee_model = Mock()
    fee_model.calc_total_cost.return_value = 0.0
    sizer = _sizer(cls, fee_model)

    sizer._estimate_trade_costs('EQ:005930', 20000.0, 100, 1000.0)
    args = fee_model.calc_total_cost.call_args[0]
    assert abs(args[1]) == 80
    assert abs(args[2]) == pytest.approx(80000.0)


@pytest.mark.parametrize('cls', SIZERS)
def test_korean_tax_is_reserved_on_sells_only(cls):
    """
    Tests the behaviour the sign exists for: a sell reserves cash for
    the transaction tax and an equally sized buy does not.
    """
    fee_model = KoreaStockFeeModel(commission_pct=0.00015, tax_pct=0.0018)
    sizer = _sizer(cls, fee_model)

    buy = sizer._estimate_trade_costs('EQ:005930', 80000.0, 0, 1000.0)
    sell = sizer._estimate_trade_costs('EQ:005930', 20000.0, 100, 1000.0)

    assert buy == pytest.approx(0.00015 * 80000.0)
    assert sell == pytest.approx((0.00015 + 0.0018) * 80000.0)
    assert sell > buy


@pytest.mark.parametrize('cls', SIZERS)
def test_holding_the_target_costs_nothing(cls):
    """
    Tests that a position already at target is not charged, and is not
    mistaken for a sale by the sign convention.
    """
    fee_model = KoreaStockFeeModel(commission_pct=0.00015, tax_pct=0.0018)
    sizer = _sizer(cls, fee_model)
    assert sizer._estimate_trade_costs(
        'EQ:005930', 100000.0, 100, 1000.0
    ) == pytest.approx(0.0)
