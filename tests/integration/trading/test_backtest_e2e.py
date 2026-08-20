import os

import pandas as pd
import pytz
import pytest

from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.broker.fee_model.percent_fee_model import PercentFeeModel
from vmtrader.trading.backtest import BacktestTradingSession

from vmtrader import settings


def test_backtest_sixty_forty(etf_filepath):
    """
    Ensures that a full end-to-end weekly rebalanced backtested
    trading session with fixed proportion weights produces the
    correct rebalance orders as well as correctly calculated
    market values after a single month's worth of daily
    backtesting.
    """
    os.environ['VMTRADER_CSV_DATA_DIR'] = etf_filepath

    assets = ['EQ:ABC', 'EQ:DEF']
    universe = StaticUniverse(assets)
    signal_weights = {'EQ:ABC': 0.6, 'EQ:DEF': 0.4}
    alpha_model = FixedSignalsAlphaModel(signal_weights)

    start_dt = pd.Timestamp('2019-01-01 00:00:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2019-01-31 23:59:00', tz=pytz.UTC)

    backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        universe,
        alpha_model,
        portfolio_id='000001',
        rebalance='weekly',
        rebalance_weekday='WED',
        long_only=True,
        cash_buffer_percentage=0.05
    )
    backtest.run(results=False)

    portfolio = backtest.broker.portfolios['000001']

    portfolio_dict = portfolio.portfolio_to_dict()
    expected_dict = {
        'EQ:ABC': {
            'unrealised_pnl': -31121.26203538094,
            'realised_pnl': 0.0,
            'total_pnl': -31121.26203538094,
            'market_value': 561680.8382534103,
            'quantity': 4674
        },
        'EQ:DEF': {
            'unrealised_pnl': 18047.831359406424,
            'realised_pnl': 613.3956570402925,
            'total_pnl': 18661.227016446715,
            'market_value': 376203.80367208034,
            'quantity': 1431.0
        }
    }

    history_df = portfolio.history_to_df().reset_index()
    expected_df = pd.read_csv(os.path.join(etf_filepath, 'sixty_forty_history.dat'))

    pd.testing.assert_frame_equal(history_df, expected_df)

    # Necessary as test fixtures differ between
    # Pandas 1.1.5 and 1.2.0 very slightly
    for symbol in expected_dict.keys():
        for metric in expected_dict[symbol].keys():
            assert portfolio_dict[symbol][metric] == pytest.approx(expected_dict[symbol][metric])


def test_backtest_sixty_forty_with_fees(etf_filepath):
    """
    Ensures that transaction costs reach the portfolio, by running the same
    weekly rebalanced 60/40 session as above with a percentage fee model.

    Every other end-to-end test leaves the default ZeroFeeModel in place, so
    the cost path was never exercised end to end: mutating the commission
    calculation by a factor of one hundred left them all passing.
    """
    os.environ['VMTRADER_CSV_DATA_DIR'] = etf_filepath

    assets = ['EQ:ABC', 'EQ:DEF']
    universe = StaticUniverse(assets)
    alpha_model = FixedSignalsAlphaModel({'EQ:ABC': 0.6, 'EQ:DEF': 0.4})

    start_dt = pd.Timestamp('2019-01-01 00:00:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2019-01-31 23:59:00', tz=pytz.UTC)

    def run(**kwargs):
        backtest = BacktestTradingSession(
            start_dt,
            end_dt,
            universe,
            alpha_model,
            portfolio_id='000001',
            rebalance='weekly',
            rebalance_weekday='WED',
            long_only=True,
            cash_buffer_percentage=0.05,
            **kwargs
        )
        backtest.run(results=False)
        return backtest.broker.portfolios['000001']

    # 0.1% commission and 0.5% tax, so 0.6% of each consideration
    free = run()
    charged = run(fee_model=PercentFeeModel(commission_pct=0.001, tax_pct=0.005))

    # Charging for the trades must leave the account worse off
    assert charged.total_equity < free.total_equity

    # Every position carries the commission it was actually charged, and the
    # sale of EQ:DEF is charged on the way out as well as on the way in
    positions = charged.pos_handler.positions
    assert positions['EQ:ABC'].commission == pytest.approx(3535.536)
    assert positions['EQ:ABC'].sell_commission == pytest.approx(0.0)
    assert positions['EQ:DEF'].commission == pytest.approx(2398.878)
    assert positions['EQ:DEF'].sell_commission == pytest.approx(132.810)

    portfolio_dict = charged.portfolio_to_dict()
    expected_dict = {
        'EQ:ABC': {
            'unrealised_pnl': -34474.178555674844,
            'realised_pnl': 0.0,
            'total_pnl': -34474.178555674844,
            'market_value': 558316.0407628036,
            'quantity': 4646
        },
        'EQ:DEF': {
            'unrealised_pnl': 15810.013381434626,
            'realised_pnl': 348.65854781338334,
            'total_pnl': 16158.67192924801,
            'market_value': 374100.6377535782,
            'quantity': 1423.0
        }
    }
    for symbol in expected_dict.keys():
        for metric in expected_dict[symbol].keys():
            assert portfolio_dict[symbol][metric] == pytest.approx(expected_dict[symbol][metric])


def test_backtest_long_short_leveraged(etf_filepath):
    """
    Ensures that a full end-to-end daily rebalanced backtested
    trading session of a leveraged long short portfolio with
    fixed proportion weights produces the correct rebalance
    orders as well as correctly calculated market values after
    a single month's worth of daily backtesting.
    """
    os.environ['VMTRADER_CSV_DATA_DIR'] = etf_filepath

    assets = ['EQ:ABC', 'EQ:DEF']
    universe = StaticUniverse(assets)
    signal_weights = {'EQ:ABC': 1.0, 'EQ:DEF': -0.7}
    alpha_model = FixedSignalsAlphaModel(signal_weights)

    start_dt = pd.Timestamp('2019-01-01 00:00:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2019-01-31 23:59:00', tz=pytz.UTC)

    backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        universe,
        alpha_model,
        portfolio_id='000001',
        rebalance='daily',
        long_only=False,
        gross_leverage=2.0
    )
    backtest.run(results=False)

    portfolio = backtest.broker.portfolios['000001']

    portfolio_dict = portfolio.portfolio_to_dict()
    expected_dict = {
        'EQ:ABC': {
            'unrealised_pnl': -48302.832839363175,
            'realised_pnl': -3930.9847615026706,
            'total_pnl': -52233.81760086585,
            'market_value': 1055344.698660986,
            'quantity': 8782.0
        },
        'EQ:DEF': {
            'unrealised_pnl': -42274.737165376326,
            'realised_pnl': -9972.897320721153,
            'total_pnl': -52247.63448609748,
            'market_value': -742417.5692312752,
            'quantity': -2824.0
        }
    }

    history_df = portfolio.history_to_df().reset_index()
    expected_df = pd.read_csv(os.path.join(etf_filepath, 'long_short_history.dat'))

    pd.testing.assert_frame_equal(history_df, expected_df)
    assert portfolio_dict == expected_dict


def test_backtest_buy_and_hold(etf_filepath, capsys):
    """
    Ensures a backtest with a buy and hold rebalance calculates
    the correct dates for execution orders when the start date is not
    a business day.
    """
    settings.print_events = True
    os.environ['VMTRADER_CSV_DATA_DIR'] = etf_filepath
    assets = ['EQ:GHI']
    universe = StaticUniverse(assets)
    alpha_model = FixedSignalsAlphaModel({'EQ:GHI': 1.0})

    start_dt = pd.Timestamp('2015-11-07 14:30:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2015-11-10 14:30:00', tz=pytz.UTC)

    backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        universe,
        alpha_model,
        rebalance='buy_and_hold',
        long_only=True,
        cash_buffer_percentage=0.01,
    )
    backtest.run(results=False)

    expected_execution_text = "(2015-11-09 14:30:00+00:00) - executed order:"
    captured = capsys.readouterr()
    assert expected_execution_text in captured.out


def test_backtest_target_allocations(etf_filepath,):
    """
    """
    settings.print_events = True
    os.environ['VMTRADER_CSV_DATA_DIR'] = etf_filepath

    assets = ['EQ:ABC', 'EQ:DEF']
    universe = StaticUniverse(assets)
    signal_weights = {'EQ:ABC': 0.6, 'EQ:DEF': 0.4}
    alpha_model = FixedSignalsAlphaModel(signal_weights)

    start_dt = pd.Timestamp('2019-01-01 00:00:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2019-01-31 23:59:00', tz=pytz.UTC)
    burn_in_dt = pd.Timestamp('2019-01-07 14:30:00', tz=pytz.UTC)

    backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        universe,
        alpha_model,
        portfolio_id='000001',
        rebalance='weekly',
        rebalance_weekday='WED',
        long_only=True,
        cash_buffer_percentage=0.05,
        burn_in_dt=burn_in_dt
    )
    backtest.run(results=False)

    target_allocations = backtest.get_target_allocations()
    expected_ta = pd.DataFrame(data={'EQ:ABC': 0.6, 'EQ:DEF': 0.4}, index=pd.date_range("20190125", periods=5, freq='B'))
    actual_ta = target_allocations.tail()
    assert expected_ta.equals(actual_ta)


def test_backtest_accepts_a_non_default_base_currency(capsys):
    """
    Tests that a backtest can be denominated in another currency.

    KRW is supported by the broker, but the session had no way to ask
    for it, so a backtest of Korean names reported won figures under a
    dollar label.
    """
    settings.set_print_events(False)
    try:
        start_dt = pd.Timestamp('2015-11-06 14:30:00', tz=pytz.UTC)
        end_dt = pd.Timestamp('2015-11-10 14:30:00', tz=pytz.UTC)

        assets = ['EQ:GHI']
        universe = StaticUniverse(assets)
        alpha_model = FixedSignalsAlphaModel({'EQ:GHI': 1.0})

        backtest = BacktestTradingSession(
            start_dt,
            end_dt,
            universe,
            alpha_model,
            rebalance='buy_and_hold',
            long_only=True,
            base_currency='KRW',
            cash_buffer_percentage=0.01,
        )
        backtest.run(results=False)

        assert backtest.broker.base_currency == 'KRW'
        assert 'KRW' in backtest.broker.get_account_cash_balance()
    finally:
        settings.set_print_events(True)
