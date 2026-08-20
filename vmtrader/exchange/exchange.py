from abc import ABC, abstractmethod


class Exchange(ABC):
    """
    Interface to a trading exchange such as the NYSE or LSE.
    This class family is only required for simulations, rather than
    live or paper trading.

    It exposes methods for obtaining calendar capability
    for trading opening times and market events.
    """

    @abstractmethod
    def is_open_at_datetime(self, dt):
        """
        Check whether the exchange is open at the provided timestamp.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The timestamp to check for open market hours.

        Returns
        -------
        `Boolean`
            Whether the exchange is open at this timestamp.
        """
        raise NotImplementedError(
            "Should implement is_open_at_datetime()"
        )
