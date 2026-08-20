from abc import ABC, abstractmethod


class ExecutionAlgorithm(ABC):
    """
    Callable which takes in a list of desired rebalance Orders
    and outputs a new Order list with a particular execution
    algorithm strategy.
    """

    @abstractmethod
    def __call__(self, dt, initial_orders):
        """
        Produce the final list of Orders to send to the Broker, derived
        from the provided list of rebalance Orders.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The current time used to populate the Order instances.
        initial_orders : `list[Order]`
            The list of rebalance orders to execute.

        Returns
        -------
        `list[Order]`
            The final list of orders to send to the Broker to be executed.
        """
        raise NotImplementedError(
            "Should implement __call__()"
        )
