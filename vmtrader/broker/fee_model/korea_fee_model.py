from vmtrader.broker.fee_model.fee_model import FeeModel


class KoreaStockFeeModel(FeeModel):
    """
    A FeeModel subclass for Korean cash equities.

    Brokerage commission is charged on both sides of a trade, but the
    securities transaction tax is charged on sales only. The side is
    taken from the sign of 'quantity': negative is a sale.

    Both the sizer and the broker pass the quantity signed, so the
    estimate a rebalance reserves cash against matches what execution
    actually charges.

    Parameters
    ----------
    commission_pct : `float`, optional
        The percentage commission applied to the consideration, on both
        buys and sells. 0-100% is in the range [0.0, 1.0]. Hence, e.g.
        0.015% is 0.00015.
    tax_pct : `float`, optional
        The percentage securities transaction tax applied to the
        consideration of a sale. Buys are never taxed. 0-100% is in the
        range [0.0, 1.0]. Hence, e.g. 0.15% is 0.0015.
    """

    def __init__(self, commission_pct=0.0, tax_pct=0.0):
        super().__init__()
        self.commission_pct = commission_pct
        self.tax_pct = tax_pct

    def _calc_commission(self, asset, quantity, consideration, broker=None):
        """
        Return the percentage commission on the consideration. Charged
        on both buys and sells.

        Parameters
        ----------
        asset : `str`
            The asset symbol string.
        quantity : `int`
            The signed quantity of assets, negative for a sale.
        consideration : `float`
            Price times quantity of the order.
        broker : `Broker`, optional
            An optional Broker reference.

        Returns
        -------
        `float`
            The percentage commission.
        """
        return self.commission_pct * abs(consideration)

    def _calc_tax(self, asset, quantity, consideration, broker=None):
        """
        Return the securities transaction tax on the consideration,
        which Korea charges on sales only.

        A zero quantity is treated as a non-trade and taxed nothing.

        Parameters
        ----------
        asset : `str`
            The asset symbol string.
        quantity : `int`
            The signed quantity of assets, negative for a sale.
        consideration : `float`
            Price times quantity of the order.
        broker : `Broker`, optional
            An optional Broker reference.

        Returns
        -------
        `float`
            The transaction tax, or zero on a buy.
        """
        if quantity >= 0:
            return 0.0
        return self.tax_pct * abs(consideration)

    def calc_total_cost(self, asset, quantity, consideration, broker=None):
        """
        Calculate the total of commission and tax for the trade of size
        'consideration'.

        Parameters
        ----------
        asset : `str`
            The asset symbol string.
        quantity : `int`
            The signed quantity of assets, negative for a sale.
        consideration : `float`
            Price times quantity of the order.
        broker : `Broker`, optional
            An optional Broker reference.

        Returns
        -------
        `float`
            The total commission and tax.
        """
        commission = self._calc_commission(
            asset, quantity, consideration, broker
        )
        tax = self._calc_tax(asset, quantity, consideration, broker)
        return commission + tax
