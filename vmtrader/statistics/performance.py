from itertools import groupby

import numpy as np
import pandas as pd


def aggregate_returns(returns, convert_to):
    """
    Aggregates returns by day, week, month, or year.
    """
    def cumulate_returns(x):
        return np.exp(np.log(1 + x).cumsum()).iloc[-1] - 1

    if convert_to == 'weekly':
        return returns.groupby(
            [lambda x: x.year,
             lambda x: x.month,
             lambda x: x.isocalendar()[1]]).apply(cumulate_returns)
    elif convert_to == 'monthly':
        return returns.groupby(
            [lambda x: x.year, lambda x: x.month]).apply(cumulate_returns)
    elif convert_to == 'yearly':
        return returns.groupby(
            [lambda x: x.year]).apply(cumulate_returns)
    else:
        raise ValueError(
            "'convert_to' must be 'weekly', 'monthly' or 'yearly', "
            "not '%s'." % convert_to
        )


def create_cagr(equity, periods=252):
    """
    Calculates the Compound Annual Growth Rate (CAGR)
    for the portfolio, by determining the number of years
    and then creating a compound annualised rate based
    on the total return.

    Parameters:
    equity - A pandas Series representing the equity curve.
    periods - Daily (252), Hourly (252*6.5), Minutely(252*6.5*60) etc.
    """
    years = len(equity) / float(periods)
    return (equity.iloc[-1] ** (1.0 / years)) - 1.0


def create_sharpe_ratio(returns, periods=252):
    """
    Create the Sharpe ratio for the strategy, based on a
    benchmark of zero (i.e. no risk-free rate information).

    Parameters:
    returns - A pandas Series representing period percentage returns.
    periods - Daily (252), Hourly (252*6.5), Minutely(252*6.5*60) etc.
    """
    return np.sqrt(periods) * (np.mean(returns)) / np.std(returns)


def create_sortino_ratio(returns, periods=252):
    """
    Create the Sortino ratio for the strategy, based on a
    benchmark of zero (i.e. no risk-free rate information).

    Parameters:
    returns - A pandas Series representing period percentage returns.
    periods - Daily (252), Hourly (252*6.5), Minutely(252*6.5*60) etc.
    """
    return np.sqrt(periods) * (np.mean(returns)) / np.std(returns[returns < 0])


def create_drawdowns(equity):
    """
    Calculate the largest peak-to-trough drawdown of the equity curve
    as well as the duration of the drawdown.

    Parameters:
    equity - A pandas Series representing a cumulative return curve,
             normalised to 1.0 at the start. Not period returns.

    Returns:
    drawdown, drawdown_max, duration
    """
    # Set up the High Water Mark, seeded with the opening value so that
    # a curve which peaks at its first point is measured from that peak
    idx = equity.index
    hwm = np.zeros(len(idx))
    hwm[0] = equity.iloc[0]

    # Create the high water mark
    for t in range(1, len(idx)):
        hwm[t] = max(hwm[t - 1], equity.iloc[t])

    # Calculate the drawdown and duration statistics
    perf = pd.DataFrame(index=idx)
    perf["Drawdown"] = (hwm - equity) / hwm
    perf["DurationCheck"] = np.where(perf["Drawdown"] == 0, 0, 1)
    duration = max(
        sum(1 for i in g if i == 1)
        for k, g in groupby(perf["DurationCheck"])
    )
    return perf["Drawdown"], np.max(perf["Drawdown"]), duration
