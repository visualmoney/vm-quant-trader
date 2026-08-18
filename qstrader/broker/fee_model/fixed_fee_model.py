from qstrader.broker.fee_model.fee_model import FeeModel


class FixedFeeModel(FeeModel):
    """
    A FeeModel subclass that charges a flat commission and tax on each
    transaction, independent of its size.

    This is the counterpart to PercentFeeModel. A purely proportional model
    cannot tell one order apart from five smaller ones covering the same
    value, so it cannot penalise splitting an order or over-trading. A flat
    component can, which makes it the model to reach for when the number of
    transactions is what a strategy should be charged for.

    A transaction of zero consideration is not charged, so that an asset
    already at its target weight does not reserve a fee for a trade that
    will not happen.

    Parameters
    ----------
    commission : `float`, optional
        The flat commission charged on each transaction.
    tax : `float`, optional
        The flat tax charged on each transaction.
    """

    def __init__(self, commission=0.0, tax=0.0):
        super().__init__()
        self.commission = commission
        self.tax = tax

    def _calc_commission(self, asset, quantity, consideration, broker=None):
        """
        Returns the flat commission for the transaction.

        Parameters
        ----------
        asset : `str`
            The asset symbol string.
        quantity : `int`
            The quantity of assets (needed for InteractiveBrokers
            style calculations).
        consideration : `float`
            Price times quantity of the order.
        broker : `Broker`, optional
            An optional Broker reference.

        Returns
        -------
        `float`
            The flat commission, or zero for an empty transaction.
        """
        if consideration == 0.0:
            return 0.0
        return self.commission

    def _calc_tax(self, asset, quantity, consideration, broker=None):
        """
        Returns the flat tax for the transaction.

        Parameters
        ----------
        asset : `str`
            The asset symbol string.
        quantity : `int`
            The quantity of assets (needed for InteractiveBrokers
            style calculations).
        consideration : `float`
            Price times quantity of the order.
        broker : `Broker`, optional
            An optional Broker reference.

        Returns
        -------
        `float`
            The flat tax, or zero for an empty transaction.
        """
        if consideration == 0.0:
            return 0.0
        return self.tax

    def calc_total_cost(self, asset, quantity, consideration, broker=None):
        """
        Calculate the total of any commission and/or tax
        for the trade of size 'consideration'.

        Parameters
        ----------
        asset : `str`
            The asset symbol string.
        quantity : `int`
            The quantity of assets (needed for InteractiveBrokers
            style calculations).
        consideration : `float`
            Price times quantity of the order.
        broker : `Broker`, optional
            An optional Broker reference.

        Returns
        -------
        `float`
            The total commission and tax.
        """
        commission = self._calc_commission(asset, quantity, consideration, broker)
        tax = self._calc_tax(asset, quantity, consideration, broker)
        return commission + tax
