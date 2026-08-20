"""
Pre-trade safety limits for live trading.

These are deliberately dumb. They know nothing about strategy, only
about magnitudes and a stop signal, so that a bug in the interesting
parts of the engine still runs into a wall before it can place a
hundred orders or one enormous one.
"""

import os


class KillSwitchEngaged(Exception):
    """
    Raised when the kill switch is engaged and an order is attempted.
    """


class OrderLimitExceeded(Exception):
    """
    Raised when an order breaches a configured limit.
    """


class SafetyGuard:
    """
    Enforces the per-order and per-session limits, and the kill switch.

    The kill switch is a file: if it exists, trading stops. A file is
    used rather than a signal or a socket because the process that
    trades is not always running, and whoever flips the switch -- an
    operator at a shell, or the Telegram gateway -- must be able to do
    so between sessions as well as during one. The engine checks it at
    launch, before every submission and on every poll, so the longest
    it can be ignored is one venue round trip.

    Parameters
    ----------
    kill_switch_path : `str`, optional
        Path whose existence halts trading. Without one, the kill
        switch is disabled, which suits tests but not live use.
    max_order_value : `float`, optional
        The largest consideration a single order may carry, in account
        currency. Without one, order value is unlimited.
    max_orders_per_session : `int`, optional
        The most orders that may be submitted in one session. Without
        one, the count is unlimited.
    """

    def __init__(
        self,
        kill_switch_path=None,
        max_order_value=None,
        max_orders_per_session=None
    ):
        self.kill_switch_path = kill_switch_path
        self.max_order_value = max_order_value
        self.max_orders_per_session = max_orders_per_session
        self.orders_submitted = 0

    def is_kill_switch_engaged(self):
        """
        Return whether the kill switch file is present.

        Returns
        -------
        `Boolean`
            Whether trading is halted.
        """
        if self.kill_switch_path is None:
            return False
        return os.path.exists(self.kill_switch_path)

    def check_can_trade(self):
        """
        Raise if trading is halted, without reference to any order.

        Called on entry to a cycle and on every poll, so that a switch
        thrown mid-session takes effect at the next opportunity rather
        than at the next session.
        """
        if self.is_kill_switch_engaged():
            raise KillSwitchEngaged(
                "Kill switch file '%s' is present. Trading is halted."
                % self.kill_switch_path
            )

    def check_order(self, symbol, quantity, price):
        """
        Raise if the order breaches a limit or trading is halted.

        Parameters
        ----------
        symbol : `str`
            The engine symbol, used in the exception message.
        quantity : `int`
            The signed quantity of the order.
        price : `float`
            The price used to value the order.
        """
        self.check_can_trade()

        value = abs(quantity) * price
        if self.max_order_value is not None and value > self.max_order_value:
            raise OrderLimitExceeded(
                "Order for %s of %s at %s is worth %.2f, above the "
                "per-order limit of %.2f."
                % (symbol, quantity, price, value, self.max_order_value)
            )

        if (
            self.max_orders_per_session is not None
            and self.orders_submitted >= self.max_orders_per_session
        ):
            raise OrderLimitExceeded(
                "Session order limit of %s reached; refusing to submit "
                "an order for %s." % (self.max_orders_per_session, symbol)
            )

    def record_submission(self):
        """
        Count an order that reached the venue.

        Counted on submission rather than on the check, so that an
        order rejected by a limit does not consume the session budget.
        """
        self.orders_submitted += 1
