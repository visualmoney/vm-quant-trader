from abc import ABC, abstractmethod


class Universe(ABC):
    """
    Interface specification for an Asset Universe.
    """

    @abstractmethod
    def get_assets(self, dt):
        """
        Obtain the list of assets in the Universe at a particular
        point in time.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The timestamp at which to retrieve the Asset list.

        Returns
        -------
        `list[str]`
            The list of Asset symbols in the Universe.
        """
        raise NotImplementedError(
            "Should implement get_assets()"
        )
