from abc import ABC, abstractmethod


class Rebalance(ABC):
    """
    Interface to a generic list of system logic and
    trade order rebalance timestamps.

    Subclasses are expected to populate a 'rebalances' attribute in
    their constructor, which is the list that BacktestTradingSession
    reads, by calling _generate_rebalances().
    """

    @abstractmethod
    def _generate_rebalances(self):
        """
        Produce the list of rebalance timestamps for the session.

        Returns
        -------
        `list[pd.Timestamp]`
            The list of rebalance timestamps.
        """
        raise NotImplementedError(
            "Should implement _generate_rebalances()"
        )
