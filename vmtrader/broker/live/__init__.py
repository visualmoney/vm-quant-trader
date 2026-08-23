"""
Venue-neutral infrastructure for live trading.

Everything here is required to trade against a real venue and specific
to none. The 'BrokerClient' Protocol states what a venue must offer,
the ledger records what was intended and what happened, the guard
holds the order limits and the kill switch, the worker collects fills
off the accounting thread, and reconciliation brings the engine's view
back in line with the account.

What belongs to one broker lives beside it instead: KIS response
parsing is in 'vmtrader/broker/kis/', and the SDK itself is imported
only by a gateway script outside the package.
"""
