"""
The whole live path, with a fake venue and an injected clock.

This is acceptance criterion A-1: target weights become orders, orders
become fills, fills become positions and cash, and the equity curve is
written -- with no network, no vendor SDK and no real time spent.

The alpha model, the portfolio construction model and the order sizers
are the ones a backtest uses, unmodified. That reuse is the reason the
live broker was added to this engine rather than written beside it.
"""

import pandas as pd
import pytest

from vmtrader import settings
from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from vmtrader.asset.universe.static import StaticUniverse
from vmtrader.broker.fee_model.korea_fee_model import KoreaStockFeeModel
from vmtrader.broker.live import ledger as ledger_states
from vmtrader.broker.live.client import AccountBalance, Holding, OrderReport
from vmtrader.broker.live.guards import SafetyGuard
from vmtrader.broker.live.ledger import OrderLedger
from vmtrader.broker.live_broker import LiveBroker
from vmtrader.data.live_data_handler import LiveDataHandler
from vmtrader.exchange.krx_exchange import KrxExchange
from vmtrader.execution.execution_handler import ExecutionHandler
from vmtrader.execution.execution_algo.market_order import (
    MarketOrderExecutionAlgorithm
)
from vmtrader.portcon.optimiser.fixed_weight import (
    FixedWeightPortfolioOptimiser
)
from vmtrader.portcon.order_sizer.dollar_weighted import (
    DollarWeightedCashBufferedOrderSizer
)
from vmtrader.portcon.pcm import PortfolioConstructionModel


@pytest.fixture(autouse=True)
def _quiet_events():
    """
    Silence the engine's event printing for these tests only.

    'PRINT_EVENTS' is module-level global state, so setting it at
    import time leaks into every test that runs afterwards -- including
    one that asserts on printed output.
    """
    previous = settings.PRINT_EVENTS
    settings.set_print_events(False)
    yield
    settings.set_print_events(previous)


SAMSUNG = 'EQ:005930'
HYNIX = 'EQ:000660'
PRICES = {SAMSUNG: 70000.0, HYNIX: 150000.0}


class FakeVenue:
    """
    A venue that fills each order across two polls.

    Partial-then-complete is the ordinary case for a market order of
    any size, so the happy path exercises the increment arithmetic
    rather than avoiding it.
    """

    def __init__(self, cash=100000000.0, holdings=()):
        self.cash = cash
        self.holdings = holdings
        self.placed = []
        self._orders = {}
        self._polls = {}
        self._next_no = 0

    def place_market_order(self, symbol, quantity):
        self._next_no += 1
        order_no = '%04d' % self._next_no
        self._orders[order_no] = (symbol, quantity)
        self.placed.append((symbol, quantity, order_no))
        return order_no

    def get_order_report(self, order_no):
        symbol, quantity = self._orders[order_no]
        requested = abs(quantity)
        polls = self._polls.get(order_no, 0)
        self._polls[order_no] = polls + 1

        if polls == 0:
            half = requested // 2
            return OrderReport(
                order_no, half, PRICES[symbol], requested - half, 0, 0.0, False
            )
        return OrderReport(
            order_no, requested, PRICES[symbol], 0, 0, 0.0, True
        )

    def get_balance(self):
        return AccountBalance(
            cash=self.cash,
            settled_cash=self.cash,
            total_equity=self.cash,
            holdings=self.holdings
        )

    def get_price(self, symbol):
        return PRICES[symbol]

    def get_trading_day(self, date_str):
        return True


def _build(tmp_path, venue, now, max_order_value=100000000.0):
    """
    Assemble the live stack around a fake venue.

    Returns
    -------
    `tuple`
        The broker, the portfolio construction model and the execution
        handler.
    """
    data_handler = LiveDataHandler(venue)
    broker = LiveBroker(
        start_dt=now,
        exchange=KrxExchange(),
        data_handler=data_handler,
        client=venue,
        ledger=OrderLedger(str(tmp_path / 'live.db')),
        fee_model=KoreaStockFeeModel(commission_pct=0.00015, tax_pct=0.0018),
        guard=SafetyGuard(max_order_value=max_order_value),
        clock=lambda: now
    )
    broker.seed_from_venue()

    universe = StaticUniverse([SAMSUNG, HYNIX])
    sizer = DollarWeightedCashBufferedOrderSizer(
        broker, broker.account_id, data_handler, cash_buffer_percentage=0.05
    )
    pcm = PortfolioConstructionModel(
        broker, broker.account_id, universe, sizer,
        FixedWeightPortfolioOptimiser(data_handler=data_handler),
        alpha_model=FixedSignalsAlphaModel({SAMSUNG: 0.6, HYNIX: 0.4}),
        data_handler=data_handler
    )
    execution = ExecutionHandler(
        broker, broker.account_id, universe,
        submit_orders=True,
        execution_algo=MarketOrderExecutionAlgorithm(),
        data_handler=data_handler
    )
    return broker, pcm, execution


def test_live_rebalance_runs_end_to_end(tmp_path):
    """
    Tests the full path: weights, orders, fills, positions, equity.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    venue = FakeVenue()
    broker, pcm, execution = _build(tmp_path, venue, now)

    orders = pcm(now)
    assert len(orders) == 2

    execution(now, orders)
    # Submission returns before any fill is collected: nothing has
    # reached the portfolio yet, but everything has reached the venue.
    assert len(venue.placed) == 2
    assert broker.get_portfolio_as_dict(broker.account_id) == {}

    booked = broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))
    assert booked == 4  # two orders, two increments each

    holdings = broker.get_portfolio_as_dict(broker.account_id)
    assert set(holdings) == {SAMSUNG, HYNIX}
    for symbol, _, _ in venue.placed:
        assert holdings[symbol]['quantity'] > 0

    broker.update(pd.Timestamp('2026-08-20 15:30:00'))
    broker.record_equity()

    curve = broker.ledger.get_equity_curve()
    assert len(curve) == 1
    assert curve[0]['total_equity'] > 0.0

    # Weights land near their targets once costs and whole shares are
    # taken out; 60/40 of the invested value, within a share's worth.
    invested = sum(
        holdings[s]['market_value'] for s in (SAMSUNG, HYNIX)
    )
    assert holdings[SAMSUNG]['market_value'] / invested == pytest.approx(
        0.6, abs=0.01
    )


def test_every_order_reaches_the_venue_before_any_fill_is_collected(tmp_path):
    """
    Tests the ordering ADR-0006 exists for.

    The sizer produced both targets from one snapshot, so both orders
    must reach the market before the engine starts waiting on either.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    venue = FakeVenue()
    broker, pcm, execution = _build(tmp_path, venue, now)

    execution(now, pcm(now))

    ledger_states_seen = [
        broker.ledger.get_order(row['order_id'])['state']
        for row in broker.ledger.get_open_orders()
    ]
    assert ledger_states_seen == [ledger_states.SUBMITTED] * 2
    assert broker.ledger.get_fills() == []


def test_the_session_survives_a_venue_rejection(tmp_path):
    """
    Tests that one refused order does not stop the rebalance.

    The refused name is simply absent from the portfolio, and the next
    rebalance will size it again.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')

    class PickyVenue(FakeVenue):
        def place_market_order(self, symbol, quantity):
            if symbol == HYNIX:
                raise RuntimeError('trading halted in this name')
            return super().place_market_order(symbol, quantity)

    venue = PickyVenue()
    broker, pcm, execution = _build(tmp_path, venue, now)

    execution(now, pcm(now))
    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    holdings = broker.get_portfolio_as_dict(broker.account_id)
    assert SAMSUNG in holdings
    assert HYNIX not in holdings


def test_a_restart_does_not_book_the_same_fill_twice(tmp_path):
    """
    Tests that recovery is idempotent.

    A process that dies after a fill was recorded but before it was
    accounted for must not book the fill again when it comes back, so
    the ledger key is what the venue reported, not what the engine did.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    venue = FakeVenue()
    broker, pcm, execution = _build(tmp_path, venue, now)
    execution(now, pcm(now))
    broker.settle(deadline=pd.Timestamp('2026-08-20 11:00:00'))

    fills_before = len(broker.ledger.get_fills())
    order_no, (symbol, quantity) = list(venue._orders.items())[0]

    # A second process re-reads the same venue snapshot.
    replayed = broker.ledger.record_fill(
        'replayed', order_no, abs(quantity), quantity, PRICES[symbol],
        0.0, now
    )
    assert replayed is False
    assert len(broker.ledger.get_fills()) == fills_before


def test_seeding_from_existing_holdings_sizes_the_increment_only(tmp_path):
    """
    Tests that a session starting with positions trades the difference.

    A rebalance that re-bought its entire target every day would pay
    the spread and the tax for nothing.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    venue = FakeVenue(
        cash=50000000.0, holdings=(Holding(SAMSUNG, 400, 70000.0),)
    )
    broker, pcm, execution = _build(tmp_path, venue, now)

    assert broker.get_portfolio_as_dict(
        broker.account_id
    )[SAMSUNG]['quantity'] == 400

    execution(now, pcm(now))
    samsung_orders = [p for p in venue.placed if p[0] == SAMSUNG]
    if samsung_orders:
        # Whatever is traded, it is the increment, not the whole target.
        assert abs(samsung_orders[0][1]) < 400


def test_the_order_value_guard_refuses_an_oversized_order(tmp_path):
    """
    Tests that the per-order cap stops a large order before it reaches
    the venue, and records the refusal.

    The cap here is below the 60% target, so the larger of the two
    names is refused while the smaller goes through -- a bug in sizing
    cannot quietly place one enormous order.
    """
    now = pd.Timestamp('2026-08-20 10:00:00')
    venue = FakeVenue()
    broker, pcm, execution = _build(
        tmp_path, venue, now, max_order_value=50000000.0
    )

    execution(now, pcm(now))

    placed = [symbol for symbol, _, _ in venue.placed]
    assert SAMSUNG not in placed
    assert HYNIX in placed
