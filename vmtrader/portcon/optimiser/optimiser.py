from abc import ABC, abstractmethod


class PortfolioOptimiser(ABC):
    """
    Abstract interface for a PortfolioOptimiser callable.

    A derived-class instance of PortfolioOptimisertakes in
    a list of Assets (not an Asset Universe) and an optional
    DataHandler instance in order to generate target weights
    for Assets.

    These are then potentially modified by the PortfolioConstructionModel,
    which generates a list of rebalance Orders.

    Implementing __call__ produces a dictionary keyed by
    Asset and with a scalar value as the weight.
    """

    @abstractmethod
    def __call__(self, dt, initial_weights):
        """
        Produce the dictionary of target weight values for each of the
        Asset instances provided.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The time 'now' used to obtain appropriate data for the
            target weights.
        initial_weights : `dict{str: float}`
            The initial weights prior to optimisation.

        Returns
        -------
        `dict{str: float}`
            The Asset symbol keyed scalar-valued target weights.
        """
        raise NotImplementedError(
            "Should implement __call__()"
        )
