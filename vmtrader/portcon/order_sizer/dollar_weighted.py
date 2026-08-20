import numpy as np

from vmtrader.portcon.order_sizer.order_sizer import OrderSizer


class DollarWeightedCashBufferedOrderSizer(OrderSizer):
    """
    Creates a target portfolio of quantities for each Asset
    using its provided weight and total equity available in the
    Broker portfolio.

    Includes an optional cash buffer due to the non-fractional amount
    of share/unit sizes. The cash buffer defaults to 5% of the total
    equity, but can be modified.

    Parameters
    ----------
    broker : `Broker`
        The derived Broker instance to obtain portfolio equity from.
    broker_portfolio_id : `str`
        The specific portfolio at the Broker to obtain equity from.
    data_handler : `DataHandler`
        To obtain latest asset prices from.
    cash_buffer_percentage : `float`, optional
        The percentage of the portfolio equity to retain in
        cash to avoid generating Orders that exceed account
        equity (assuming no margin available).
    """

    def __init__(
        self,
        broker,
        broker_portfolio_id,
        data_handler,
        cash_buffer_percentage=0.05
    ):
        self.broker = broker
        self.broker_portfolio_id = broker_portfolio_id
        self.data_handler = data_handler
        self.cash_buffer_percentage = self._check_set_cash_buffer(
            cash_buffer_percentage
        )

    def _check_set_cash_buffer(self, cash_buffer_percentage):
        """
        Checks and sets the cash buffer percentage value.

        Parameters
        ----------
        cash_buffer_percentage : `float`
            The percentage of the portfolio equity to retain in
            cash to avoid generating Orders that exceed account
            equity (assuming no margin available).

        Returns
        -------
        `float`
            The cash buffer percentage value.
        """
        if (
            cash_buffer_percentage < 0.0 or cash_buffer_percentage > 1.0
        ):
            raise ValueError(
                'Cash buffer percentage "%s" provided to dollar-weighted '
                'execution algorithm is negative or '
                'exceeds 100%%.' % cash_buffer_percentage
            )
        else:
            return cash_buffer_percentage

    def _obtain_broker_portfolio_total_equity(self):
        """
        Obtain the Broker portfolio total equity.

        Returns
        -------
        `float`
            The Broker portfolio total equity.
        """
        return self.broker.get_portfolio_total_equity(self.broker_portfolio_id)

    def _normalise_weights(self, weights):
        """
        Rescale provided weight values to ensure
        weight vector sums to unity.

        Parameters
        ----------
        weights : `dict{Asset: float}`
            The un-normalised weight vector.

        Returns
        -------
        `dict{Asset: float}`
            The unit sum weight vector.
        """
        if any([weight < 0.0 for weight in weights.values()]):
            raise ValueError(
                'Dollar-weighted cash-buffered order sizing does not support '
                'negative weights. All positions must be long-only.'
            )

        weight_sum = sum(weight for weight in weights.values())

        # If the weights are very close or equal to zero then rescaling
        # is not possible, so simply return weights unscaled
        if np.isclose(weight_sum, 0.0):
            return weights

        return {
            asset: (weight / weight_sum)
            for asset, weight in weights.items()
        }

    def _obtain_current_portfolio(self):
        """
        Query the broker for the current portfolio holdings.

        Returns
        -------
        `dict{str: dict}`
            The current broker portfolio holdings, keyed by asset symbol.
        """
        return self.broker.get_portfolio_as_dict(self.broker_portfolio_id)

    def _estimate_trade_costs(
        self, asset, target_dollars, current_quantity, asset_price
    ):
        """
        Estimate the broker costs of moving an asset to its target position.

        The estimate is taken on the size of the trade, not on the whole
        target position. A rebalance usually trades only the increment, so
        pricing the entire position reserves cash for a trade that will not
        happen and leaves the portfolio permanently under-invested by
        approximately the fee rate.

        Quantity and consideration are passed signed -- negative for a
        sell -- matching how the broker charges the fee on execution. A
        fee model that treats the two sides differently, such as a
        sell-side-only transaction tax, needs the sign to do so.

        Parameters
        ----------
        asset : `str`
            The asset symbol string.
        target_dollars : `float`
            The desired dollar value of the position.
        current_quantity : `int`
            The quantity of the asset currently held.
        asset_price : `float`
            The current price of the asset.

        Returns
        -------
        `float`
            The estimated commission and tax for the trade.
        """
        trade_dollars = target_dollars - current_quantity * asset_price
        direction = 1 if trade_dollars >= 0.0 else -1
        trade_quantity = direction * int(
            np.floor(abs(trade_dollars) / asset_price)
        )
        return self.broker.fee_model.calc_total_cost(
            asset, trade_quantity, trade_dollars, broker=self.broker
        )

    def __call__(self, dt, weights):
        """
        Creates a dollar-weighted cash-buffered target portfolio from the
        provided target weights at a particular timestamp.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The current date-time timestamp.
        weights : `dict{Asset: float}`
            The (potentially unnormalised) target weights.

        Returns
        -------
        `dict{Asset: dict}`
            The cash-buffered target portfolio dictionary with quantities.
        """
        total_equity = self._obtain_broker_portfolio_total_equity()
        cash_buffered_total_equity = total_equity * (
            1.0 - self.cash_buffer_percentage
        )

        # Pre-cost dollar weight
        N = len(weights)
        if N == 0:
            # No forecasts so portfolio remains in cash
            # or is fully liquidated
            return {}

        # Ensure weight vector sums to unity
        normalised_weights = self._normalise_weights(weights)

        current_portfolio = self._obtain_current_portfolio()

        target_portfolio = {}
        for asset, weight in sorted(normalised_weights.items()):
            pre_cost_dollar_weight = cash_buffered_total_equity * weight

            asset_price = self.data_handler.get_asset_latest_ask_price(
                dt, asset
            )

            if np.isnan(asset_price):
                raise ValueError(
                    'Asset price for "%s" at timestamp "%s" is Not-a-Number (NaN). '
                    'This can occur if the chosen backtest start date is earlier '
                    'than the first available price for a particular asset. Try '
                    'modifying the backtest start date and re-running.' % (asset, dt)
                )

            # Estimate broker fees on the trade required to reach the target
            est_costs = self._estimate_trade_costs(
                asset, pre_cost_dollar_weight,
                current_portfolio.get(asset, {}).get('quantity', 0),
                asset_price
            )

            # Calculate integral target asset quantity assuming broker costs
            after_cost_dollar_weight = pre_cost_dollar_weight - est_costs

            # TODO: Long only for the time being.
            asset_quantity = int(
                np.floor(after_cost_dollar_weight / asset_price)
            )

            # Add to the target portfolio
            target_portfolio[asset] = {"quantity": asset_quantity}

        return target_portfolio
