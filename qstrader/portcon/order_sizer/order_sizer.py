from abc import ABC, abstractmethod


class OrderSizer(ABC):
    """
    Creates a target portfolio of quantities for each Asset
    using its provided weight and total equity available in the Broker portfolio.
    """

    @abstractmethod
    def __call__(self, dt, weights):
        """
        Create a target portfolio of quantities from the provided
        target weights at a particular timestamp.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The current date-time timestamp.
        weights : `dict{str: float}`
            The (potentially unnormalised) target weights.

        Returns
        -------
        `dict{str: dict}`
            The target portfolio dictionary with quantities.
        """
        raise NotImplementedError(
            "Should implement call()"
        )
