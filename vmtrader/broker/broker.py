from abc import ABC, abstractmethod


class Broker(ABC):
    """
    This abstract class provides an interface to a
    generic broker entity. Both simulated and live brokers
    will be derived from this ABC. This ensures that trading
    algorithm specific logic is completely identical for both
    simulated and live environments.

    The Broker has an associated master denominated currency
    through which all subscriptions and withdrawals will occur.

    The Broker entity can support multiple sub-portfolios, each
    with their own separate handling of PnL. The individual PnLs
    from each sub-portfolio can be aggregated to generate an
    account-wide PnL.

    The Broker can execute orders. It contains a queue of
    open orders, needed for handling closed market situations.

    The Broker also supports individual history events for each
    sub-portfolio, which can be aggregated, along with the
    account history, to produce a full trading history for the
    account.
    """

    @abstractmethod
    def subscribe_funds_to_account(self, amount):
        """
        Subscribe an amount of cash in the base currency to the
        broker master cash account.

        Parameters
        ----------
        amount : `float`
            The amount of cash to subscribe to the master account.
        """
        raise NotImplementedError(
            "Should implement subscribe_funds_to_account()"
        )

    @abstractmethod
    def withdraw_funds_from_account(self, amount):
        """
        Withdraw an amount of cash in the base currency from the
        broker master cash account.

        Parameters
        ----------
        amount : `float`
            The amount of cash to withdraw from the master account.
        """
        raise NotImplementedError(
            "Should implement withdraw_funds_from_account()"
        )

    @abstractmethod
    def get_account_cash_balance(self, currency=None):
        """
        Retrieve the cash dictionary of the account, or, if a currency
        is provided, the cash value itself.

        Parameters
        ----------
        currency : `str`, optional
            The currency string to obtain the cash balance for.

        Returns
        -------
        `dict{str: float}` or `float`
            The full cash balance dictionary, or the balance for the
            single requested currency.
        """
        raise NotImplementedError(
            "Should implement get_account_cash_balance()"
        )

    @abstractmethod
    def get_account_total_equity(self):
        """
        Retrieve the total equity of the account, across each portfolio.

        Returns
        -------
        `dict{str: float}`
            The dictionary of each portfolio's total equity.
        """
        raise NotImplementedError(
            "Should implement get_account_total_equity()"
        )

    @abstractmethod
    def create_portfolio(self, portfolio_id, name):
        """
        Create a new sub-portfolio with ID 'portfolio_id' and an
        optional name given by 'name'.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID string.
        name : `str`, optional
            The optional name string of the portfolio.
        """
        raise NotImplementedError(
            "Should implement create_portfolio()"
        )

    @abstractmethod
    def list_all_portfolios(self):
        """
        List all of the sub-portfolios associated with this broker
        account.

        Returns
        -------
        `list[Portfolio]`
            The list of portfolios associated with the broker account.
        """
        raise NotImplementedError(
            "Should implement list_all_portfolios()"
        )

    @abstractmethod
    def subscribe_funds_to_portfolio(self, portfolio_id, amount):
        """
        Subscribe funds to a particular sub-portfolio.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID string.
        amount : `float`
            The amount of cash to subscribe to the portfolio.
        """
        raise NotImplementedError(
            "Should implement subscribe_funds_to_portfolio()"
        )

    @abstractmethod
    def withdraw_funds_from_portfolio(self, portfolio_id, amount):
        """
        Withdraw funds from a particular sub-portfolio.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID string.
        amount : `float`
            The amount of cash to withdraw from the portfolio.
        """
        raise NotImplementedError(
            "Should implement withdraw_funds_from_portfolio()"
        )

    @abstractmethod
    def get_portfolio_cash_balance(self, portfolio_id):
        """
        Retrieve the cash balance of a sub-portfolio.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID string.

        Returns
        -------
        `float`
            The cash balance of the portfolio.
        """
        raise NotImplementedError(
            "Should implement get_portfolio_cash_balance()"
        )

    @abstractmethod
    def get_portfolio_total_equity(self, portfolio_id):
        """
        Return the current total equity of a sub-portfolio.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID string.

        Returns
        -------
        `float`
            The total equity of the portfolio.
        """
        raise NotImplementedError(
            "Should implement get_portfolio_total_equity()"
        )

    @abstractmethod
    def get_portfolio_as_dict(self, portfolio_id):
        """
        Return a sub-portfolio as a dictionary with Asset symbol strings
        as keys, with various attributes as sub-dictionaries.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID string.

        Returns
        -------
        `dict{str: dict}`
            The portfolio representation of Assets as a dictionary.
        """
        raise NotImplementedError(
            "Should implement get_portfolio_as_dict()"
        )

    @abstractmethod
    def submit_order(self, portfolio_id, order):
        """
        Execute an Order instance against the sub-portfolio with ID
        'portfolio_id'.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID string.
        order : `Order`
            The Order instance to submit.
        """
        raise NotImplementedError(
            "Should implement submit_order()"
        )

    @abstractmethod
    def update(self, dt):
        """
        Advance the broker to the provided timestamp.

        Callers rely on this after submitting orders and on every event
        of the trading session, so a Broker that omits it fails at run
        time rather than at instantiation. What the method does is
        implementation specific: a simulated broker executes its queued
        orders, whereas a live broker polls for fills, marks positions
        to market and reconciles against the venue.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The timestamp to advance the broker to.
        """
        raise NotImplementedError(
            "Should implement update()"
        )
