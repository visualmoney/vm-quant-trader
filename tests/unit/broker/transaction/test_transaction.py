import pandas as pd
import pytest

from qstrader.asset.equity import Equity
from qstrader.broker.transaction.transaction import Transaction


def test_transaction_representation():
    """
    Tests that the Transaction representation
    correctly recreates the object.
    """
    dt = pd.Timestamp('2015-05-06')
    asset = Equity('Apple, Inc.', 'AAPL')
    transaction = Transaction(
        asset, quantity=168, dt=dt, price=56.18, order_id=153
    )
    exp_repr = (
        "Transaction(asset=Equity(name='Apple, Inc.', symbol='AAPL', tax_exempt=True), "
        "quantity=168, dt=2015-05-06 00:00:00, price=56.18, order_id=153)"
    )
    assert repr(transaction) == exp_repr


@pytest.mark.parametrize(
    'quantity,price,commission,expected_without,expected_with',
    [
        (100, 10.0, 0.0, 1000.0, 1000.0),      # a purchase with no commission
        (100, 10.0, 5.0, 1000.0, 1005.0),      # commission increases the cost
        (-100, 10.0, 0.0, -1000.0, -1000.0),   # a sale is a negative cost
        (-100, 10.0, 5.0, -1000.0, -995.0),    # commission reduces the proceeds
    ]
)
def test_transaction_costs(
    quantity, price, commission, expected_without, expected_with
):
    """
    Checks the transaction cost properties across both directions and with
    and without commission.

    The final case is the one worth stating: the operator is '+' rather than
    '-' because the fee models return an absolute amount, via abs(), so the
    same addition increases the cost of a purchase and reduces the proceeds
    of a sale. A sale of 1000.0 with 5.0 of commission nets 995.0, which as a
    signed cost is -995.0.
    """
    transaction = Transaction(
        Equity('Apple, Inc.', 'AAPL'),
        quantity=quantity,
        dt=pd.Timestamp('2015-05-06'),
        price=price,
        order_id=153,
        commission=commission
    )

    assert transaction.cost_without_commission == pytest.approx(expected_without)
    assert transaction.cost_with_commission == pytest.approx(expected_with)
