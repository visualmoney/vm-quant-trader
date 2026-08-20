import pandas as pd
import pytest

from vmtrader import settings
from vmtrader.broker.kis import ledger as ledger_states
from vmtrader.broker.kis.client import AccountBalance, Holding, OrderReport
from vmtrader.broker.kis.ledger import OrderLedger
from vmtrader.broker.kis.reconcile import reconcile
from vmtrader.broker.kis_broker import KisBroker
from vmtrader.data.live_data_handler import LiveDataHandler
from vmtrader.exchange.krx_exchange import KrxExchange


@pytest.fixture(autouse=True)
def _quiet_events():
    """
    Silence event printing for these tests only.
    """
    previous = settings.PRINT_EVENTS
    settings.set_print_events(False)
    yield
    settings.set_print_events(previous)


class StubVenue:
    """
    A venue with a fixed balance and fixed order reports.
    """

    def __init__(self, holdings=(), cash=1000000.0, reports=None):
        self.holdings = holdings
        self.cash = cash
        self.reports = reports or {}

    def place_market_order(self, symbol, quantity):
        raise AssertionError('reconciliation must not place orders')

    def get_order_report(self, order_no):
        return self.reports.get(
            order_no, OrderReport(order_no, 0, 0.0, 0, 0, 0.0, False)
        )

    def get_balance(self):
        return AccountBalance(
            cash=self.cash,
            settled_cash=self.cash,
            total_equity=self.cash,
            holdings=self.holdings
        )

    def get_price(self, symbol):
        return 10000.0

    def get_trading_day(self, date_str):
        return True


def _broker(venue, tmp_path):
    """
    Build a broker against the stub venue.
    """
    return KisBroker(
        start_dt=pd.Timestamp('2026-08-20 09:30:00'),
        exchange=KrxExchange(),
        data_handler=LiveDataHandler(venue),
        client=venue,
        ledger=OrderLedger(str(tmp_path / 'ledger.db')),
        clock=lambda: pd.Timestamp('2026-08-20 09:30:00')
    )


def test_a_clean_account_reconciles_quietly(tmp_path):
    """
    Tests that agreement produces no findings and no halt.
    """
    venue = StubVenue(holdings=(Holding('EQ:005930', 10, 70000.0),))
    broker = _broker(venue, tmp_path)
    broker.seed_from_venue()

    result = reconcile(broker)

    assert result.overstated == {}
    assert result.untracked == {}
    assert result.halt_trading is False
    assert broker.trading_halted is False


def test_an_open_order_is_settled_against_the_venue(tmp_path):
    """
    Tests that a fill which happened while the process was dead is
    booked at the next launch.
    """
    venue = StubVenue(
        holdings=(Holding('EQ:005930', 10, 70000.0),),
        reports={'0001': OrderReport('0001', 10, 70000.0, 0, 0, 0.0, True)}
    )
    broker = _broker(venue, tmp_path)
    dt = broker.current_dt
    broker.ledger.record_intent('o1', 'EQ:005930', 10, dt)
    broker.ledger.record_submitted('o1', '0001', dt)

    result = reconcile(broker)

    assert result.resolved_orders == ['0001']
    assert broker.ledger.get_order('o1')['state'] == ledger_states.FILLED
    assert len(broker.ledger.get_fills('o1')) == 1


def test_a_fill_already_booked_is_not_booked_again(tmp_path):
    """
    Tests that recovery is idempotent across restarts.

    The venue reports cumulative totals, so a recovery that ignored
    what the ledger already holds would book the whole fill a second
    time.
    """
    venue = StubVenue(
        holdings=(Holding('EQ:005930', 10, 70000.0),),
        reports={'0001': OrderReport('0001', 10, 70000.0, 0, 0, 0.0, True)}
    )
    broker = _broker(venue, tmp_path)
    dt = broker.current_dt
    broker.ledger.record_intent('o1', 'EQ:005930', 10, dt)
    broker.ledger.record_submitted('o1', '0001', dt)
    broker.ledger.record_fill('o1', '0001', 10, 10, 70000.0, 0.0, dt)

    reconcile(broker)

    assert len(broker.ledger.get_fills('o1')) == 1


def test_an_intent_with_no_order_number_is_flagged_and_halts(tmp_path):
    """
    Tests the case where a process died mid-submission.

    The order may or may not exist at the venue, and no amount of
    querying settles it, so it is reported and trading stops for a
    human to check.
    """
    venue = StubVenue()
    broker = _broker(venue, tmp_path)
    broker.ledger.record_intent('o1', 'EQ:005930', 10, broker.current_dt)

    result = reconcile(broker)

    assert result.orphan_intents == ['o1']
    assert result.halt_trading is True
    assert broker.trading_halted is True


def test_local_overstatement_halts_trading(tmp_path):
    """
    Tests the asymmetry that matters.

    Believing we hold shares we do not have leads to selling them,
    which the venue refuses and which means the engine's picture is
    wrong somewhere it cannot see.
    """
    venue = StubVenue(holdings=(Holding('EQ:005930', 4, 70000.0),))
    broker = _broker(venue, tmp_path)
    broker.seed_from_venue()
    # The venue then reports fewer shares than the engine believes.
    venue.holdings = (Holding('EQ:005930', 1, 70000.0),)

    result = reconcile(broker)

    assert result.overstated == {'EQ:005930': (4, 1)}
    assert broker.trading_halted is True


def test_untracked_holdings_are_reported_without_halting(tmp_path):
    """
    Tests the other side of the asymmetry.

    A position the engine did not buy is most likely somebody trading
    the same account by hand, which is not ours to unwind.
    """
    venue = StubVenue(holdings=(Holding('EQ:000660', 5, 150000.0),))
    broker = _broker(venue, tmp_path)

    result = reconcile(broker)

    assert result.untracked == {'EQ:000660': 5}
    assert result.halt_trading is False
    assert broker.trading_halted is False


def test_halting_stops_the_next_order(tmp_path):
    """
    Tests that the halt is not merely advisory.
    """
    from vmtrader.execution.order import Order

    venue = StubVenue(holdings=(Holding('EQ:005930', 4, 70000.0),))
    broker = _broker(venue, tmp_path)
    broker.seed_from_venue()
    venue.holdings = ()

    reconcile(broker)
    broker.submit_order(
        broker.account_id, Order(broker.current_dt, 'EQ:005930', -1)
    )
    assert broker.trading_halted is True


def test_inspection_mode_reports_without_halting(tmp_path):
    """
    Tests that a caller can look without stopping trading, which is
    what an operator's status command needs.
    """
    venue = StubVenue(holdings=(Holding('EQ:005930', 4, 70000.0),))
    broker = _broker(venue, tmp_path)
    broker.seed_from_venue()
    venue.holdings = ()

    result = reconcile(broker, halt_on_mismatch=False)

    assert result.overstated != {}
    assert broker.trading_halted is False
