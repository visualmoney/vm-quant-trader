import numpy as np
import pandas as pd
import pytest

from qstrader.statistics.performance import (
    aggregate_returns,
    create_cagr,
    create_drawdowns,
    create_sharpe_ratio,
    create_sortino_ratio
)


# A five-period return series used across the ratio tests. Every expected
# value below is derived from it by hand:
#
#   mean                     = (0.01 + 0.02 - 0.01 + 0.03 - 0.02) / 5 = 0.006
#   population variance      = 0.00172 / 5 = 0.000344
#   population std (ddof=0)  = 0.01854723699099141
#   downside std (ddof=0)    = std([-0.01, -0.02]) = 0.005
#
# The population standard deviation is what these functions use: np.std() on a
# Pandas Series defaults to ddof=0, not the ddof=1 that Series.std() would
# apply. Pinning the values below therefore also pins that choice.
RETURNS = [0.01, 0.02, -0.01, 0.03, -0.02]


def _returns_series(values, start='2020-01-01'):
    """
    Build a business-day indexed return Series from a list of values.

    Parameters
    ----------
    values : `list[float]`
        The period returns.
    start : `str`, optional
        The first date of the index.

    Returns
    -------
    `pd.Series`
        The date-indexed return series.
    """
    return pd.Series(
        values, index=pd.date_range(start, periods=len(values), freq='B')
    )


@pytest.mark.parametrize(
    'convert_to,expected_index,expected_values',
    [
        (
            'monthly',
            [(2020, 1), (2020, 2), (2021, 3)],
            [0.21, 0.20, 0.50]
        ),
        (
            'yearly',
            [2020, 2021],
            [0.452, 0.50]
        ),
        (
            'weekly',
            [(2020, 1, 3), (2020, 2, 7), (2021, 3, 9)],
            [0.21, 0.20, 0.50]
        ),
    ]
)
def test_aggregate_returns(convert_to, expected_index, expected_values):
    """
    Checks that returns are compounded, not summed, within each
    aggregation bucket.

    The two January returns of 10% compound to 1.1 * 1.1 - 1 = 0.21, and the
    2020 yearly figure additionally includes February's 20%, giving
    1.1 * 1.1 * 1.2 - 1 = 0.452. Summing would produce 0.20 and 0.40.
    """
    returns = pd.Series(
        [0.1, 0.1, 0.2, 0.5],
        index=pd.to_datetime(
            ['2020-01-15', '2020-01-16', '2020-02-10', '2021-03-01']
        )
    )

    result = aggregate_returns(returns, convert_to)

    assert list(result.index) == expected_index
    assert list(result.values) == pytest.approx(expected_values)


def test_aggregate_returns_with_unknown_period_raises():
    """
    Checks that an unrecognised 'convert_to' value is reported, and that the
    message names the value that was actually supplied.

    Until 0.3.13 the final branch constructed a ValueError without raising it,
    so a typo returned None and surfaced much later, if at all.
    """
    returns = _returns_series(RETURNS)

    with pytest.raises(ValueError) as excinfo:
        aggregate_returns(returns, 'daily')

    assert 'daily' in str(excinfo.value)


@pytest.mark.parametrize(
    'final_equity,length,periods,expected',
    [
        (2.0, 252, 252, 1.0),      # doubled over one year
        (4.0, 504, 252, 1.0),      # quadrupled over two years -> still 100%
        (1.0, 252, 252, 0.0),      # flat
        (0.5, 252, 252, -0.5),     # halved over one year
        (1.5, 12, 12, 0.5),        # monthly periods override
    ]
)
def test_create_cagr(final_equity, length, periods, expected):
    """
    Checks the compound annual growth rate over a whole number of years.

    Note the contract: 'equity' must be a cumulative return curve normalised
    to 1.0 at the start, not an account equity in currency units. The
    calculation raises the final value to the power of 1/years, so passing a
    balance such as 1e6 would produce a meaningless figure.
    """
    equity = pd.Series(np.linspace(1.0, final_equity, length))

    assert create_cagr(equity, periods=periods) == pytest.approx(expected)


def test_create_sharpe_ratio():
    """
    Checks the annualised Sharpe ratio against a hand-calculated value.

    sqrt(252) * 0.006 / 0.01854723699099141 = 5.135376619417101
    """
    returns = _returns_series(RETURNS)

    assert create_sharpe_ratio(returns) == pytest.approx(5.135376619417101)


def test_create_sharpe_ratio_scales_with_the_square_root_of_periods():
    """
    Checks that only the annualisation factor depends on 'periods'.

    The ratio of the daily and quarterly figures must be exactly
    sqrt(4 / 252), since the mean and standard deviation are unchanged.
    """
    returns = _returns_series(RETURNS)

    quarterly = create_sharpe_ratio(returns, periods=4)
    daily = create_sharpe_ratio(returns, periods=252)

    assert quarterly == pytest.approx(daily * np.sqrt(4.0 / 252.0))


def test_create_sharpe_ratio_with_zero_mean_return_is_zero():
    """
    Checks that a return series averaging zero produces a zero ratio,
    whatever its volatility.
    """
    returns = _returns_series([0.05, -0.05, 0.05, -0.05])

    assert create_sharpe_ratio(returns) == pytest.approx(0.0)


def test_create_sharpe_ratio_with_constant_returns_is_infinite():
    """
    Pins the degenerate case of a zero standard deviation.

    A constant return series has no dispersion, so the ratio divides by zero
    and yields infinity rather than raising. Callers plotting this value need
    to handle it.
    """
    returns = _returns_series([0.01] * 5)

    with np.errstate(divide='ignore'):
        assert np.isinf(create_sharpe_ratio(returns))


def test_create_sortino_ratio():
    """
    Checks the annualised Sortino ratio against a hand-calculated value.

    The numerator is the mean of *all* returns while the denominator is the
    standard deviation of the negative ones only:

        sqrt(252) * 0.006 / 0.005 = 19.04940943966505
    """
    returns = _returns_series(RETURNS)

    assert create_sortino_ratio(returns) == pytest.approx(19.04940943966505)


def test_create_sortino_ratio_exceeds_sharpe_when_downside_volatility_is_lower():
    """
    Checks the defining relationship between the two ratios.

    For this series the downside deviation (0.005) is smaller than the total
    deviation (0.0185), so penalising only downside movement must produce the
    larger ratio.
    """
    returns = _returns_series(RETURNS)

    assert create_sortino_ratio(returns) > create_sharpe_ratio(returns)


def test_create_sortino_ratio_without_losses_is_nan():
    """
    Pins the degenerate case of a return series with no negative periods.

    The downside selection is then empty and its standard deviation is NaN,
    which propagates to the ratio. This is a plausible outcome for a short
    burn-in window, so it is a real case rather than a theoretical one.
    """
    returns = _returns_series([0.01, 0.02, 0.03])

    assert np.isnan(create_sortino_ratio(returns))


def test_create_drawdowns():
    """
    Checks the drawdown series, its maximum and its duration.

    For the curve [1.0, 1.5, 0.75, 1.2, 1.0, 2.0] the high water mark runs
    [0, 1.5, 1.5, 1.5, 1.5, 2.0], giving drawdowns of 50%, 20% and 33.3%
    across three consecutive periods before a new peak is set.
    """
    equity = _returns_series([1.0, 1.5, 0.75, 1.2, 1.0, 2.0])

    drawdown, max_drawdown, duration = create_drawdowns(equity)

    assert list(drawdown.values) == pytest.approx(
        [0.0, 0.0, 0.5, 0.2, 1.0 / 3.0, 0.0]
    )
    assert max_drawdown == pytest.approx(0.5)
    assert duration == 3


def test_create_drawdowns_on_a_monotonically_rising_curve():
    """
    Checks that a curve which never falls reports no drawdown and a
    duration of zero, rather than a duration of one for the whole period.
    """
    equity = _returns_series([1.0, 1.1, 1.2, 1.3])

    drawdown, max_drawdown, duration = create_drawdowns(equity)

    assert list(drawdown.values) == pytest.approx([0.0, 0.0, 0.0, 0.0])
    assert max_drawdown == pytest.approx(0.0)
    assert duration == 0


def test_create_drawdowns_on_a_monotonically_falling_curve():
    """
    Checks a curve that only ever falls, where every point after the first
    is in drawdown and the peak is the opening value.

    Until 0.3.13 this reported 22.2% over 2 periods, measuring from the
    second point rather than the first.
    """
    equity = _returns_series([1.0, 0.9, 0.8, 0.7])

    drawdown, max_drawdown, duration = create_drawdowns(equity)

    assert list(drawdown.values) == pytest.approx([0.0, 0.1, 0.2, 0.3])
    assert max_drawdown == pytest.approx(0.3)
    assert duration == 3


def test_create_drawdowns_treats_the_opening_value_as_a_peak():
    """
    Checks that a curve which peaks at its very first point has its drawdown
    measured from that peak.

    Until 0.3.13 the high water mark array was initialised to zero and the
    loop started at index 1, so the opening value could never become a peak.
    This curve halves immediately and never recovers, and was reported as a
    0.0 maximum drawdown lasting 0 periods.
    """
    equity = _returns_series([2.0, 1.0, 1.0])

    drawdown, max_drawdown, duration = create_drawdowns(equity)

    assert list(drawdown.values) == pytest.approx([0.0, 0.5, 0.5])
    assert max_drawdown == pytest.approx(0.5)
    assert duration == 2
