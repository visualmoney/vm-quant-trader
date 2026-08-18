from abc import ABC, abstractmethod


class AlphaModel(ABC):
    """
    Abstract interface for an AlphaModel callable.

    A derived-class instance of AlphaModel takes in an Asset
    Universe and an optional DataHandler instance in order
    to generate forecast signals on Assets.

    These signals are used by the PortfolioConstructionModel
    to generate target weights for the portfolio.

    Implementing __call__ produces a dictionary keyed by
    Asset and with a scalar value as the signal.
    """

    @abstractmethod
    def __call__(self, dt):
        """
        Produce the dictionary of signals for the Assets in the
        Universe at the provided timestamp.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The time 'now' used to obtain appropriate data and universe
            for the signals.

        Returns
        -------
        `dict{str: float}`
            The Asset symbol keyed scalar-valued signals.
        """
        raise NotImplementedError(
            "Should implement __call__()"
        )
