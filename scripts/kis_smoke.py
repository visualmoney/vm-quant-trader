"""
Exercise the live path against a real paper account.

This is the one part of the acceptance criteria that fakes cannot
cover. Everything up to here has been verified against a stub venue;
what remains is whether KIS actually behaves the way the parser
assumes. Criteria A-3, A-4 and A-5 are what this checks.

It places real orders. On a paper account that costs nothing, but the
script is built as though it did:

  * The real-money server is refused outright, not merely defaulted
    away from. There is no flag that reaches it.
  * Orders are placed only in the rebalance stage, and only when
    --place-orders is passed. Every other stage is read-only.
  * Exposure is capped twice -- by a budget that scales the target
    weights, and by a per-order limit in the guard.
  * The ledger is written somewhere separate, so a smoke run never
    mixes with a real deployment's history.

Usage:
    python scripts/kis_smoke.py --stage connect
    python scripts/kis_smoke.py --stage rebalance --place-orders
    python scripts/kis_smoke.py --stage restart
    python scripts/kis_smoke.py --stage safety
"""

import argparse
import os
import sys

import pandas as pd


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))

from kis_gateway import KisGateway  # noqa: E402

from vmtrader import settings  # noqa: E402
from vmtrader.alpha_model.fixed_signals import FixedSignalsAlphaModel  # noqa: E402
from vmtrader.asset.universe.static import StaticUniverse  # noqa: E402
from vmtrader.broker.fee_model.korea_fee_model import KoreaStockFeeModel  # noqa: E402
from vmtrader.broker.kis import ledger as ledger_states  # noqa: E402
from vmtrader.broker.kis.guards import KillSwitchEngaged, SafetyGuard  # noqa: E402
from vmtrader.broker.kis.ledger import OrderLedger  # noqa: E402
from vmtrader.broker.kis.reconcile import reconcile  # noqa: E402
from vmtrader.broker.kis_broker import KisBroker  # noqa: E402
from vmtrader.data.live_data_handler import LiveDataHandler  # noqa: E402
from vmtrader.exchange.krx_exchange import KrxExchange  # noqa: E402
from vmtrader.execution.execution_algo.market_order import (  # noqa: E402
    MarketOrderExecutionAlgorithm
)
from vmtrader.execution.execution_handler import ExecutionHandler  # noqa: E402
from vmtrader.execution.order import Order  # noqa: E402
from vmtrader.portcon.optimiser.fixed_weight import (  # noqa: E402
    FixedWeightPortfolioOptimiser
)
from vmtrader.portcon.order_sizer.dollar_weighted import (  # noqa: E402
    DollarWeightedCashBufferedOrderSizer
)
from vmtrader.portcon.pcm import PortfolioConstructionModel  # noqa: E402


# Two liquid large caps. Liquidity matters here: a market order in a
# thin name would fill at a price that tells us nothing about whether
# the plumbing works.
DEFAULT_UNIVERSE = ['EQ:005930', 'EQ:000660']

DEFAULT_BUDGET = 1000000.0
DEFAULT_MAX_ORDER_VALUE = 600000.0
DEFAULT_LEDGER = os.path.join(REPO_ROOT, 'out', 'smoke-ledger.db')
DEFAULT_KILL_SWITCH = os.path.join(REPO_ROOT, 'out', 'smoke.HALT')


class SmokeError(RuntimeError):
    """
    Raised when a smoke criterion fails.
    """


def scaled_weights(symbols, budget, total_equity):
    """
    Spread a budget evenly across the universe, as portfolio weights.

    The sizers work in fractions of total equity, so a fixed cash
    budget has to be expressed as a fraction. Capping it at one means
    a budget larger than the account simply means 'all of it'.

    Parameters
    ----------
    symbols : `list[str]`
        The universe.
    budget : `float`
        Cash to deploy, in account currency.
    total_equity : `float`
        The account's total equity.

    Returns
    -------
    `dict{str: float}`
        Target weights summing to at most one.
    """
    if total_equity <= 0.0:
        raise SmokeError(
            'The account reports no equity, so nothing can be sized.'
        )
    exposure = min(budget / total_equity, 1.0)
    per_name = exposure / len(symbols)
    return dict((symbol, per_name) for symbol in symbols)


def build_stack(args, guard=None):
    """
    Authenticate and assemble the live stack against the paper server.

    Parameters
    ----------
    args : `argparse.Namespace`
        Parsed command line.
    guard : `SafetyGuard`, optional
        Overrides the default guard, used by the safety stage.

    Returns
    -------
    `tuple`
        The gateway, broker and data handler.
    """
    if args.server != 'vps':
        # Not a default that can be overridden: a smoke test has no
        # business anywhere near real money.
        raise SmokeError(
            "This script only runs against the paper server. Promotion to "
            "a real account follows ADR-0013, not a smoke flag."
        )

    gateway = KisGateway.connect(svr=args.server, ota_home=args.ota_home)
    data_handler = LiveDataHandler(gateway)
    os.makedirs(os.path.dirname(args.ledger), exist_ok=True)

    broker = KisBroker(
        start_dt=pd.Timestamp.now(),
        exchange=KrxExchange(),
        data_handler=data_handler,
        client=gateway,
        ledger=OrderLedger(args.ledger),
        fee_model=KoreaStockFeeModel(
            commission_pct=0.00015, tax_pct=0.0018
        ),
        guard=guard if guard is not None else SafetyGuard(
            kill_switch_path=args.kill_switch,
            max_order_value=args.max_order_value,
            max_orders_per_session=len(args.universe) * 2
        )
    )
    return gateway, broker, data_handler


def stage_connect(args):
    """
    Read-only checks: authentication, balance, marks, calendar.

    Nothing here can move money. It exists so that a credential or
    parsing problem is found before any order is contemplated.

    Returns
    -------
    `dict`
        What was observed.
    """
    gateway, broker, data_handler = build_stack(args)

    balance = gateway.get_balance()
    print('  account cash (projected): %.0f' % balance.cash)
    print('  settled deposit (D+2, reference only): %.0f'
          % balance.settled_cash)
    print('  venue equity: %.0f' % balance.total_equity)
    print('  holdings: %d' % len(balance.holdings))
    for holding in balance.holdings:
        print('    %s x%d @ %.0f'
              % (holding.symbol, holding.quantity, holding.average_price))

    for symbol in args.universe:
        print('  mark %s = %.0f' % (symbol, data_handler.get_mark(symbol)))

    today = pd.Timestamp.now().strftime('%Y%m%d')
    print('  venue says %s is a trading day: %s'
          % (today, gateway.get_trading_day(today)))
    print('  local calendar says market open now: %s'
          % broker.exchange.is_open_at_datetime(pd.Timestamp.now()))

    # The one field the design depends on and fakes cannot confirm:
    # a chart response that the signal warm-up will consume.
    end = pd.Timestamp.now()
    start = end - pd.Timedelta(days=30)
    closes = data_handler.get_assets_historical_range_close_price(
        start, end, args.universe[:1]
    )
    print('  daily closes fetched for warm-up: %d row(s)' % len(closes))

    return {'balance': balance, 'closes': len(closes)}


def stage_rebalance(args):
    """
    A-3: run one real rebalance and confirm the venue agrees.

    Places orders. Requires --place-orders, which exists so that
    running the script without thinking cannot trade.

    Returns
    -------
    `dict`
        What was observed.
    """
    if not args.place_orders:
        raise SmokeError(
            'This stage places real orders. Re-run with --place-orders '
            'once you have read what it will do.'
        )

    gateway, broker, data_handler = build_stack(args)
    broker.seed_from_venue()

    equity = broker.get_portfolio_total_equity(broker.account_id)
    weights = scaled_weights(args.universe, args.budget, equity)
    print('  equity %.0f, budget %.0f, weights %s'
          % (equity, args.budget, weights))

    if not broker.exchange.is_open_at_datetime(pd.Timestamp.now()):
        raise SmokeError(
            'The market is closed, so no order can be accepted. Run this '
            'stage between 09:00 and 15:30 on a trading day.'
        )

    universe = StaticUniverse(args.universe)
    sizer = DollarWeightedCashBufferedOrderSizer(
        broker, broker.account_id, data_handler, cash_buffer_percentage=0.05
    )
    pcm = PortfolioConstructionModel(
        broker, broker.account_id, universe, sizer,
        FixedWeightPortfolioOptimiser(data_handler=data_handler),
        alpha_model=FixedSignalsAlphaModel(weights),
        data_handler=data_handler
    )
    execution = ExecutionHandler(
        broker, broker.account_id, universe,
        submit_orders=True,
        execution_algo=MarketOrderExecutionAlgorithm(),
        data_handler=data_handler
    )

    now = pd.Timestamp.now()
    orders = pcm(now)
    print('  sized %d order(s): %s'
          % (len(orders), [(o.asset, o.quantity) for o in orders]))
    if not orders:
        raise SmokeError(
            'Nothing was sized. The account may already hold the target, '
            'or the budget may be smaller than one share.'
        )

    execution(now, orders)
    accepted = list(broker.open_orders)
    print('  venue accepted order number(s): %s' % accepted)
    if not accepted:
        raise SmokeError(
            'No order number came back, so A-3(a) fails. Check the ledger '
            'for the rejection reason.'
        )

    deadline = pd.Timestamp.now() + pd.Timedelta(minutes=args.settle_minutes)
    print('  settling until %s' % deadline)
    booked = broker.settle(deadline, poll_interval=args.poll_seconds)
    print('  booked %d fill increment(s)' % booked)

    local = broker.get_portfolio_as_dict(broker.account_id)
    venue = dict(
        (holding.symbol, holding.quantity)
        for holding in gateway.get_balance().holdings
    )
    print('  local:  %s'
          % dict((s, p['quantity']) for s, p in local.items()))
    print('  venue:  %s' % venue)

    mismatched = [
        symbol for symbol, position in local.items()
        if venue.get(symbol, 0) != position['quantity']
    ]
    if mismatched:
        # Not necessarily a defect: the venue may not reflect a
        # same-day purchase in its holdings yet. That is exactly the
        # thing this smoke test exists to establish.
        print('  MISMATCH on %s — record whether the venue reflects '
              'same-day buys (spec §8).' % mismatched)

    broker.record_equity()
    return {
        'accepted': accepted, 'booked': booked,
        'mismatched': mismatched, 'local': local, 'venue': venue
    }


def stage_restart(args):
    """
    A-4: rebuild from the venue and confirm nothing is double booked.

    Simulates the restart the cron model performs twice a day, using
    the ledger the rebalance stage left behind.

    Returns
    -------
    `dict`
        What was observed.
    """
    _, broker, _ = build_stack(args)

    fills_before = len(broker.ledger.get_fills())
    result = reconcile(broker)
    fills_after = len(broker.ledger.get_fills())

    print('  %s' % result.summary())
    print('  fills before %d, after %d' % (fills_before, fills_after))
    print('  positions after recovery: %s'
          % dict(
              (s, p['quantity'])
              for s, p in broker.get_portfolio_as_dict(
                  broker.account_id
              ).items()
          ))

    if fills_after != fills_before:
        raise SmokeError(
            'Recovery booked %d additional fill(s). The idempotency key '
            'is not holding, so A-4 fails.'
            % (fills_after - fills_before)
        )
    if result.halt_trading:
        raise SmokeError(
            'Reconciliation halted trading: %s. Resolve before promoting.'
            % result.summary()
        )
    return {'fills': fills_after, 'reconcile': result}


def stage_safety(args):
    """
    A-5: demonstrate the refusals, without placing an order.

    Each check tries something that must not reach the venue, and the
    stage fails if anything does.

    Returns
    -------
    `dict`
        What was observed.
    """
    results = {}

    # (a) Outside market hours.
    _, broker, _ = build_stack(args)
    broker.seed_from_venue()
    closed = pd.Timestamp.now().normalize() + pd.Timedelta(hours=18)
    broker.clock = lambda: closed
    before = len(broker.ledger.get_open_orders())
    broker.submit_order(
        broker.account_id, Order(closed, args.universe[0], 1)
    )
    results['market_closed'] = (
        len(broker.ledger.get_open_orders()) == before
    )
    print('  refused outside market hours: %s' % results['market_closed'])

    # (b) Selling what is not held.
    _, broker, _ = build_stack(args)
    broker.seed_from_venue()
    held = broker.get_portfolio_as_dict(broker.account_id)
    absent = next(
        (s for s in args.universe if held.get(s, {}).get('quantity', 0) == 0),
        None
    )
    if absent is None:
        print('  every universe name is held; skipping the short check')
        results['short_refused'] = None
    else:
        before = len(broker.ledger.get_open_orders())
        broker.submit_order(broker.account_id, Order(
            pd.Timestamp.now(), absent, -1
        ))
        results['short_refused'] = (
            len(broker.ledger.get_open_orders()) == before
        )
        print('  refused a short in %s: %s'
              % (absent, results['short_refused']))

    # (c) Kill switch. Also leaves the ledger evidence that ADR-0013
    # requires before promotion.
    with open(args.kill_switch, 'w', encoding='utf-8') as handle:
        handle.write('engaged by kis_smoke.py\n')
    try:
        _, broker, _ = build_stack(args)
        broker.seed_from_venue()
        order = Order(pd.Timestamp.now(), args.universe[0], 1)
        try:
            broker.submit_order(broker.account_id, order)
            results['kill_switch'] = False
        except KillSwitchEngaged:
            row = broker.ledger.get_order(order.order_id)
            results['kill_switch'] = (
                row is not None and row['state'] == ledger_states.REJECTED
            )
    finally:
        os.remove(args.kill_switch)
    print('  kill switch refused and recorded: %s' % results['kill_switch'])

    failed = [name for name, ok in results.items() if ok is False]
    if failed:
        raise SmokeError('Safety checks failed: %s' % ', '.join(failed))
    return results


STAGES = {
    'connect': stage_connect,
    'rebalance': stage_rebalance,
    'restart': stage_restart,
    'safety': stage_safety,
}


def main(argv=None):
    """
    Run the requested stage.

    Returns
    -------
    `int`
        Zero on success.
    """
    parser = argparse.ArgumentParser(
        description='Exercise the live path against a KIS paper account.'
    )
    parser.add_argument(
        '--stage', choices=sorted(STAGES), required=True,
        help='Which check to run.'
    )
    parser.add_argument(
        '--place-orders', action='store_true',
        help='Required by the rebalance stage, which places real orders.'
    )
    parser.add_argument(
        '--server', default='vps',
        help='Kept only so that passing anything else fails loudly.'
    )
    parser.add_argument('--ota-home', default=None, help='KIS SDK clone.')
    parser.add_argument(
        '--universe', nargs='+', default=DEFAULT_UNIVERSE,
        help='Engine symbols to trade.'
    )
    parser.add_argument(
        '--budget', type=float, default=DEFAULT_BUDGET,
        help='Cash to deploy across the universe.'
    )
    parser.add_argument(
        '--max-order-value', type=float, default=DEFAULT_MAX_ORDER_VALUE,
        help='Per-order ceiling enforced by the guard.'
    )
    parser.add_argument(
        '--settle-minutes', type=int, default=5,
        help='How long to collect fills before giving up.'
    )
    parser.add_argument(
        '--poll-seconds', type=float, default=3.0,
        help='Delay between fill polls.'
    )
    parser.add_argument('--ledger', default=DEFAULT_LEDGER)
    parser.add_argument('--kill-switch', default=DEFAULT_KILL_SWITCH)
    args = parser.parse_args(argv)

    settings.set_print_events(True)
    print('== stage: %s ==' % args.stage)
    try:
        STAGES[args.stage](args)
    except SmokeError as err:
        print('\nFAILED: %s' % err)
        return 1
    print('\nStage "%s" completed.' % args.stage)
    return 0


if __name__ == '__main__':
    sys.exit(main())
