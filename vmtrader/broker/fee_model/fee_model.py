from abc import ABC, abstractmethod


class FeeModel(ABC):
    """
    Abstract class to handle the calculation of brokerage
    commission, fees and taxes.
    """

    @abstractmethod
    def _calc_commission(self, asset, quantity, consideration, broker=None):
        """
        Return the commission charged on the provided consideration.

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
            The calculated commission.
        """
        raise NotImplementedError(
            "Should implement _calc_commission()"
        )

    @abstractmethod
    def _calc_tax(self, asset, quantity, consideration, broker=None):
        """
        Return the tax charged on the provided consideration.

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
            The calculated tax.
        """
        raise NotImplementedError(
            "Should implement _calc_tax()"
        )

    @abstractmethod
    def calc_total_cost(self, asset, quantity, consideration, broker=None):
        """
        Calculate the total of any commission and/or tax for the trade
        of size 'consideration'.

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
        raise NotImplementedError(
            "Should implement calc_total_cost()"
        )
