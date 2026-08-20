from unittest.mock import Mock

import pandas as pd
import pytest
import pytz


from vmtrader.portcon.order_sizer.long_short import (
    LongShortLeveragedOrderSizer
)


@pytest.mark.parametrize(
    "gross_leverage,expected",
    [
        (-1.0, None),
        (0.0, None),
        (0.01, 0.01),
        (0.99, 0.99),
        (1.0, 1.0),
        (2.0, 2.0),
        (5.0, 5.0),
    ]
)
def test_check_set_gross_leverage(gross_leverage, expected):
    """
    Checks that the gross leverage falls into the appropriate
    range and raises otherwise.
    """
    broker = Mock()
    broker_portfolio_id = "1234"
    data_handler = Mock()

    if expected is None:
        with pytest.raises(ValueError):
            order_sizer = LongShortLeveragedOrderSizer(
                broker, broker_portfolio_id, data_handler, gross_leverage
            )
    else:
        order_sizer = LongShortLeveragedOrderSizer(
            broker, broker_portfolio_id, data_handler, gross_leverage
        )
        assert order_sizer.gross_leverage == expected


@pytest.mark.parametrize(
    "weights,gross_leverage,expected",
    [
        (
            {'EQ:ABC': 0.2, 'EQ:DEF': 0.6},
            1.0,
            {'EQ:ABC': 0.25, 'EQ:DEF': 0.75}
        ),
        (
            {'EQ:ABC': 0.5, 'EQ:DEF': 0.5},
            1.0,
            {'EQ:ABC': 0.5, 'EQ:DEF': 0.5}
        ),
        (
            {'EQ:ABC': 0.01, 'EQ:DEF': 0.01},
            1.0,
            {'EQ:ABC': 0.5, 'EQ:DEF': 0.5}
        ),
        (
            {'EQ:ABC': 0.2, 'EQ:DEF': 0.6},
            2.0,
            {'EQ:ABC': 0.5, 'EQ:DEF': 1.5}
        ),
        (
            {'EQ:ABC': 0.2, 'EQ:DEF': 0.6},
            0.5,
            {'EQ:ABC': 0.125, 'EQ:DEF': 0.375}
        ),
        (
            {'EQ:ABC': 0.1, 'EQ:DEF': 0.3, 'EQ:GHI': 0.02, 'EQ:JKL': 0.8},
            1.0,
            {'EQ:ABC': 0.1 / 1.22, 'EQ:DEF': 0.3 / 1.22, 'EQ:GHI': 0.02 / 1.22, 'EQ:JKL': 0.8 / 1.22}
        ),
        (
            {'EQ:ABC': 0.1, 'EQ:DEF': 0.3, 'EQ:GHI': 0.02, 'EQ:JKL': 0.8},
            3.0,
            {'EQ:ABC': 0.3 / 1.22, 'EQ:DEF': 0.9 / 1.22, 'EQ:GHI': 0.06 / 1.22, 'EQ:JKL': 2.4 / 1.22}
        ),
        (
            {'EQ:ABC': 0.0, 'EQ:DEF': 0.0},
            1.0,
            {'EQ:ABC': 0.0, 'EQ:DEF': 0.0}
        ),
        (
            {'EQ:ABC': -0.2, 'EQ:DEF': 0.6},
            1.0,
            {'EQ:ABC': -0.25, 'EQ:DEF': 0.75}
        ),
        (
            {'EQ:ABC': -0.2, 'EQ:DEF': 0.6},
            2.0,
            {'EQ:ABC': -0.5, 'EQ:DEF': 1.5}
        ),
        (
            {'EQ:ABC': -0.1, 'EQ:DEF': 0.3, 'EQ:GHI': 0.02, 'EQ:JKL': -0.8},
            3.0,
            {'EQ:ABC': -0.3 / 1.22, 'EQ:DEF': 0.9 / 1.22, 'EQ:GHI': 0.06 / 1.22, 'EQ:JKL': -2.4 / 1.22}
        )
    ]
)
def test_normalise_weights(weights, gross_leverage, expected):
    """
    Checks that the _normalise_weights method rescales the weights
    for the correct gross exposure and leverage.
    """
    broker = Mock()
    broker_portfolio_id = "1234"
    data_handler = Mock()

    order_sizer = LongShortLeveragedOrderSizer(
        broker, broker_portfolio_id, data_handler, gross_leverage
    )
    if expected is None:
        with pytest.raises(ValueError):
            result = order_sizer._normalise_weights(weights)
    else:
        result = order_sizer._normalise_weights(weights)
        assert result == pytest.approx(expected)


@pytest.mark.parametrize(
    "total_equity,gross_leverage,weights,asset_prices,expected",
    [
        (
            1e6,
            1.0,
            {'EQ:SPY': 0.5, 'EQ:AGG': 0.5},
            {'EQ:SPY': 250.0, 'EQ:AGG': 150.0},
            {'EQ:SPY': {'quantity': 2000}, 'EQ:AGG': {'quantity': 3333}}
        ),
        (
            325000.0,
            1.5,
            {'EQ:SPY': 0.6, 'EQ:AGG': 0.4},
            {'EQ:SPY': 352.0, 'EQ:AGG': 178.0},
            {'EQ:SPY': {'quantity': 830}, 'EQ:AGG': {'quantity': 1095}}
        ),
        (
            687523.0,
            2.0,
            {'EQ:SPY': 0.05, 'EQ:AGG': 0.328, 'EQ:TLT': 0.842, 'EQ:GLD': 0.9113},
            {'EQ:SPY': 1036.23, 'EQ:AGG': 456.55, 'EQ:TLT': 987.63, 'EQ:GLD': 14.76},
            {
                'EQ:SPY': {'quantity': 31},
                'EQ:AGG': {'quantity': 463},
                'EQ:TLT': {'quantity': 550},
                'EQ:GLD': {'quantity': 39833},
            }
        ),
        (
            687523.0,
            2.0,
            {'EQ:SPY': 0.05, 'EQ:AGG': -0.328, 'EQ:TLT': -0.842, 'EQ:GLD': 0.9113},
            {'EQ:SPY': 1036.23, 'EQ:AGG': 456.55, 'EQ:TLT': 987.63, 'EQ:GLD': 14.76},
            {
                'EQ:SPY': {'quantity': 31},
                'EQ:AGG': {'quantity': -463},
                'EQ:TLT': {'quantity': -550},
                'EQ:GLD': {'quantity': 39833},
            }
        )
    ]
)
def test_call(total_equity, gross_leverage, weights, asset_prices, expected):
    """
    Checks that the __call__ method correctly outputs the target
    portfolio from a given set of weights and a timestamp.
    """
    dt = pd.Timestamp('2019-01-01 15:00:00', tz=pytz.utc)
    broker_portfolio_id = "1234"

    broker = Mock()
    broker.get_portfolio_total_equity.return_value = total_equity
    broker.fee_model.calc_total_cost.return_value = 0.0
    # An empty portfolio: every target is reached from a standing start
    broker.get_portfolio_as_dict.return_value = {}

    data_handler = Mock()
    data_handler.get_asset_latest_ask_price.side_effect = lambda self, x: asset_prices[x]

    order_sizer = LongShortLeveragedOrderSizer(
        broker, broker_portfolio_id, data_handler, gross_leverage
    )

    result = order_sizer(dt, weights)
    assert result == expected


def test_fees_are_estimated_on_the_trade_not_the_whole_position():
    """
    Checks that the fee estimate is taken on the trade rather than the whole
    target position, including when the existing holding is a short that has
    to be reversed.
    """
    dt = pd.Timestamp('2019-01-01 15:00:00', tz=pytz.utc)

    broker = Mock()
    broker.get_portfolio_total_equity.return_value = 1000000.0
    broker.fee_model.calc_total_cost.return_value = 0.0
    # Short 100 units at 1000.0 against a long target of 1,000,000, so the
    # trade is the full 1,100,000 needed to reverse the position
    broker.get_portfolio_as_dict.return_value = {'EQ:ABC': {'quantity': -100}}

    data_handler = Mock()
    data_handler.get_asset_latest_ask_price.side_effect = lambda self, x: 1000.0

    order_sizer = LongShortLeveragedOrderSizer(
        broker, "1234", data_handler, 1.0
    )
    order_sizer(dt, {'EQ:ABC': 1.0})

    asset, quantity, consideration = broker.fee_model.calc_total_cost.call_args[0]
    assert asset == 'EQ:ABC'
    assert consideration == pytest.approx(1100000.0)
    assert quantity == 1100
