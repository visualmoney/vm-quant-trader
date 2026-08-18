import pytest

from qstrader.broker.fee_model.fixed_fee_model import FixedFeeModel


class AssetMock:
    def __init__(self):
        pass


class BrokerMock:
    def __init__(self):
        pass


@pytest.mark.parametrize(
    "commission,tax,quantity,consideration,"
    "expected_commission,expected_tax,expected_total", [
        (0.0, 0.0, 100, 1000.0, 0.0, 0.0, 0.0),
        (1.0, 0.0, 100, 1000.0, 1.0, 0.0, 1.0),
        (0.0, 0.5, 100, 1000.0, 0.0, 0.5, 0.5),
        (1.0, 0.5, 100, 1000.0, 1.0, 0.5, 1.5),
        # The charge does not scale with the size of the transaction
        (1.0, 0.5, 100000, 8542000.0, 1.0, 0.5, 1.5),
        # Nor with its direction
        (1.0, 0.5, -100, -1000.0, 1.0, 0.5, 1.5),
        # An empty transaction is not charged
        (1.0, 0.5, 0, 0.0, 0.0, 0.0, 0.0),
    ]
)
def test_fixed_commission(
    commission, tax, quantity, consideration,
    expected_commission, expected_tax, expected_total
):
    """
    Tests that each method returns the flat tax/commission regardless of the
    size or direction of the transaction, and charges nothing for an empty
    one.
    """
    ffm = FixedFeeModel(commission=commission, tax=tax)
    asset = AssetMock()
    broker = BrokerMock()

    assert ffm._calc_commission(asset, quantity, consideration, broker=broker) == expected_commission
    assert ffm._calc_tax(asset, quantity, consideration, broker=broker) == expected_tax
    assert ffm.calc_total_cost(asset, quantity, consideration, broker=broker) == expected_total


def test_splitting_an_order_multiplies_a_fixed_fee():
    """
    Checks the property that motivates this model: unlike a proportional
    charge, a flat one distinguishes one order from several smaller ones
    covering the same value.

    A PercentFeeModel charges the same total however an order is divided, so
    the simulator could not penalise over-trading at all.
    """
    ffm = FixedFeeModel(commission=1.0)
    asset = AssetMock()

    whole = ffm.calc_total_cost(asset, 100, 10000.0)
    in_five = sum(
        ffm.calc_total_cost(asset, 20, 2000.0) for _ in range(5)
    )

    assert whole == pytest.approx(1.0)
    assert in_five == pytest.approx(5.0)
