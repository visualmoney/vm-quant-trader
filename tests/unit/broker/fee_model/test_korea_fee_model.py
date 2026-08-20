import pytest

from vmtrader.broker.fee_model.korea_fee_model import KoreaStockFeeModel


@pytest.mark.parametrize(
    'commission_pct,tax_pct,quantity,consideration,expected',
    [
        # A buy pays commission only.
        (0.00015, 0.0018, 100, 1000000.0, 150.0),
        # A sell of the same size pays commission and tax.
        (0.00015, 0.0018, -100, -1000000.0, 1950.0),
        # Zero rates cost nothing on either side.
        (0.0, 0.0, 100, 1000000.0, 0.0),
        (0.0, 0.0, -100, -1000000.0, 0.0),
        # A zero quantity is not a sale, so it is not taxed.
        (0.00015, 0.0018, 0, 0.0, 0.0),
    ]
)
def test_calc_total_cost(
    commission_pct, tax_pct, quantity, consideration, expected
):
    """
    Tests that total cost is charged per side at the given rates.
    """
    fee_model = KoreaStockFeeModel(
        commission_pct=commission_pct, tax_pct=tax_pct
    )
    assert fee_model.calc_total_cost(
        'EQ:005930', quantity, consideration
    ) == pytest.approx(expected)


def test_tax_is_asymmetric_between_sides():
    """
    Tests that an identically sized buy and sell do not cost the same,
    which is the entire point of the model.
    """
    fee_model = KoreaStockFeeModel(commission_pct=0.00015, tax_pct=0.0018)
    buy = fee_model.calc_total_cost('EQ:005930', 100, 1000000.0)
    sell = fee_model.calc_total_cost('EQ:005930', -100, -1000000.0)
    assert sell > buy
    assert sell - buy == pytest.approx(0.0018 * 1000000.0)


def test_sign_of_consideration_does_not_decide_the_side():
    """
    Tests that the quantity decides the side, not the consideration.

    A caller that passes an unsigned consideration alongside a negative
    quantity must still be charged tax, since the quantity is the
    documented carrier of the side.
    """
    fee_model = KoreaStockFeeModel(commission_pct=0.0, tax_pct=0.0018)
    assert fee_model.calc_total_cost(
        'EQ:005930', -100, 1000000.0
    ) == pytest.approx(1800.0)
