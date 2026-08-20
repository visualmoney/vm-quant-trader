from abc import ABC, abstractmethod


class TradingSession(ABC):
    """
    Interface to a live or backtested trading session.
    """

    @abstractmethod
    def run(self):
        """
        Execute the trading session, rebalancing the quant trading
        system across the full set of simulation events.
        """
        raise NotImplementedError(
            "Should implement run()"
        )
