"""
Durable record of what the engine intended, sent and received.

Written ahead of the venue call, so that a process which dies between
deciding to trade and hearing back leaves evidence of the order it may
have placed. Recovery reads this, not memory.

Fills are recorded against a key derived from the order number and the
cumulative filled quantity. The venue reports cumulative totals with no
fill identifier, so the same fill is seen on every poll; the key makes
booking it twice impossible rather than merely unlikely.

A ledger also carries the identity of the deployment that wrote it:
which venue, which account, and whether the money was real. Without
that, nothing could tell a paper ledger from a real one, and the
promotion check read whichever file it was pointed at and trusted
the operator that it was the paper one.
"""

import sqlite3


INTENT = 'INTENT'
SUBMITTED = 'SUBMITTED'
FILLED = 'FILLED'
REJECTED = 'REJECTED'
STALE = 'STALE'

TERMINAL_STATES = (FILLED, REJECTED, STALE)

PAPER = 'paper'
REAL = 'real'
UNKNOWN = 'unknown'


class LedgerIdentityConflict(Exception):
    """
    Raised when a ledger is opened by a deployment it does not belong to.

    Mixing a paper run and a real run in one file corrupts the only
    evidence the promotion check has, and it corrupts it silently:
    both runs write valid rows. Refusing at the point of the second
    stamp is the only place the mistake is still cheap.
    """


class OrderLedger:
    """
    An append-only SQLite ledger of order state and fills.

    One connection belongs to one thread. The fill worker and the main
    thread each open their own through the same path, which is why the
    constructor takes a path rather than a connection.

    Parameters
    ----------
    path : `str`
        Path to the SQLite database. ':memory:' is accepted for tests,
        but a memory database is not shared between connections.
    """

    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self):
        """
        Create the tables and constraints if they are not present.
        """
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                state TEXT NOT NULL,
                order_no TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                note TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                fill_key TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                order_no TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                fees REAL NOT NULL,
                venue_time TEXT,
                engine_time TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS equity_curve (
                recorded_at TEXT PRIMARY KEY,
                total_equity REAL NOT NULL,
                mode TEXT NOT NULL DEFAULT 'unknown'
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._add_missing_columns()
        self.conn.commit()

    def _add_missing_columns(self):
        """
        Bring a ledger written by an earlier version up to date.

        'CREATE TABLE IF NOT EXISTS' does nothing to a table that
        already exists, so a ledger from before the mode column was
        added would keep its old shape and every insert naming the
        column would fail. Existing rows take 'unknown', which is
        honest: nothing recorded what they were.
        """
        columns = {
            row['name']
            for row in self.conn.execute('PRAGMA table_info(equity_curve)')
        }
        if 'mode' not in columns:
            self.conn.execute(
                "ALTER TABLE equity_curve ADD COLUMN mode TEXT NOT NULL "
                "DEFAULT '%s'" % UNKNOWN
            )

    def close(self):
        """
        Close this thread's connection.
        """
        self.conn.close()

    def stamp_identity(self, venue, mode, account_id):
        """
        Record which deployment owns this ledger, or verify it matches.

        Called once when a broker opens the ledger. The first call
        writes the identity; every later call checks it and raises on a
        disagreement, so a real-money session cannot append to a paper
        ledger, nor the reverse. That is the whole point: the mistake
        is silent otherwise, because both runs write valid rows.

        Parameters
        ----------
        venue : `str`
            The venue name, e.g. 'kis'.
        mode : `str`
            'paper' or 'real'.
        account_id : `str`
            The account the deployment trades.

        Raises
        ------
        LedgerIdentityConflict
            If the ledger already belongs to a different deployment.
        """
        identity = {'venue': venue, 'mode': mode, 'account_id': account_id}
        existing = self.get_identity()

        if existing is not None:
            if existing != identity:
                raise LedgerIdentityConflict(
                    "Ledger '%s' belongs to venue=%s mode=%s account=%s, but "
                    "was opened as venue=%s mode=%s account=%s. Use a "
                    "separate ledger file per deployment; mixing them "
                    "destroys the evidence the promotion check reads."
                    % (
                        self.path, existing['venue'], existing['mode'],
                        existing['account_id'], venue, mode, account_id
                    )
                )
            return

        self.conn.executemany(
            'INSERT INTO meta (key, value) VALUES (?, ?)',
            sorted(identity.items())
        )
        self.conn.commit()

    def get_identity(self):
        """
        Return the deployment identity recorded in this ledger.

        Returns
        -------
        `dict{str: str}` or `None`
            The identity, or None for a ledger written before
            identities were recorded.
        """
        rows = self.conn.execute(
            "SELECT key, value FROM meta WHERE key IN "
            "('venue', 'mode', 'account_id')"
        ).fetchall()
        if len(rows) < 3:
            return None
        return {row['key']: row['value'] for row in rows}

    def record_intent(self, order_id, symbol, quantity, dt):
        """
        Record an order the engine is about to place.

        Written before the venue is called. An intent left behind with
        no order number is the trace of a process that died mid-call,
        and recovery treats it as possibly live.

        Parameters
        ----------
        order_id : `str`
            The engine's order ID.
        symbol : `str`
            The engine symbol.
        quantity : `int`
            The signed quantity.
        dt : `pd.Timestamp`
            The engine timestamp of the intent.
        """
        stamp = str(dt)
        self.conn.execute(
            'INSERT OR IGNORE INTO orders '
            '(order_id, symbol, quantity, state, order_no, created_at, '
            'updated_at, note) VALUES (?, ?, ?, ?, NULL, ?, ?, NULL)',
            (order_id, symbol, quantity, INTENT, stamp, stamp)
        )
        self.conn.commit()

    def record_submitted(self, order_id, order_no, dt):
        """
        Record that the venue accepted the order and issued a number.

        Parameters
        ----------
        order_id : `str`
            The engine's order ID.
        order_no : `str`
            The venue's order number.
        dt : `pd.Timestamp`
            The engine timestamp of acceptance.
        """
        self.conn.execute(
            'UPDATE orders SET state = ?, order_no = ?, updated_at = ? '
            'WHERE order_id = ?',
            (SUBMITTED, order_no, str(dt), order_id)
        )
        self.conn.commit()

    def record_state(self, order_id, state, dt, note=None):
        """
        Move an order to a terminal state.

        Parameters
        ----------
        order_id : `str`
            The engine's order ID.
        state : `str`
            One of FILLED, REJECTED or STALE.
        dt : `pd.Timestamp`
            The engine timestamp of the transition.
        note : `str`, optional
            A human-readable reason, kept for the audit trail.
        """
        self.conn.execute(
            'UPDATE orders SET state = ?, updated_at = ?, note = ? '
            'WHERE order_id = ?',
            (state, str(dt), note, order_id)
        )
        self.conn.commit()

    def record_fill(
        self, order_id, order_no, cumulative_filled, quantity, price,
        fees, engine_dt, venue_time=None
    ):
        """
        Record a fill increment, at most once.

        The key is the order number and the cumulative filled quantity
        it was observed at, so re-reading the same venue snapshot after
        a restart cannot book the increment a second time.

        Parameters
        ----------
        order_id : `str`
            The engine's order ID.
        order_no : `str`
            The venue's order number.
        cumulative_filled : `int`
            Total filled quantity the venue reported, which forms the
            idempotency key together with the order number.
        quantity : `int`
            The signed increment to book.
        price : `float`
            The fill price.
        fees : `float`
            The fees attributed to the increment.
        engine_dt : `pd.Timestamp`
            The engine timestamp the increment is booked at.
        venue_time : `str`, optional
            The venue's own timestamp, kept for audit only.

        Returns
        -------
        `Boolean`
            Whether this call inserted the fill. False means it was
            already recorded and must not be booked again.
        """
        fill_key = '%s:%s' % (order_no, cumulative_filled)
        cursor = self.conn.execute(
            'INSERT OR IGNORE INTO fills '
            '(fill_key, order_id, order_no, quantity, price, fees, '
            'venue_time, engine_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                fill_key, order_id, order_no, quantity, price, fees,
                venue_time, str(engine_dt)
            )
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def record_equity(self, dt, total_equity, mode=UNKNOWN):
        """
        Append a point to the equity curve.

        The live process dies between sessions, so unlike a backtest
        the curve cannot live in memory.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The timestamp of the valuation.
        total_equity : `float`
            The account's total equity.
        mode : `str`, optional
            'paper' or 'real'. Stored per row as well as in the
            meta table, so that a curve can be audited even if it
            predates identity stamping or was assembled by hand.
        """
        self.conn.execute(
            'INSERT OR REPLACE INTO equity_curve '
            '(recorded_at, total_equity, mode) VALUES (?, ?, ?)',
            (str(dt), total_equity, mode)
        )
        self.conn.commit()

    def get_order(self, order_id):
        """
        Return a single order row.

        Parameters
        ----------
        order_id : `str`
            The engine's order ID.

        Returns
        -------
        `sqlite3.Row` or `None`
            The order row, or None if unknown.
        """
        cursor = self.conn.execute(
            'SELECT * FROM orders WHERE order_id = ?', (order_id,)
        )
        return cursor.fetchone()

    def get_open_orders(self):
        """
        Return orders that have not reached a terminal state.

        These are what recovery must ask the venue about.

        Returns
        -------
        `list[sqlite3.Row]`
            The open order rows, oldest first.
        """
        placeholders = ', '.join('?' * len(TERMINAL_STATES))
        cursor = self.conn.execute(
            'SELECT * FROM orders WHERE state NOT IN (%s) '
            'ORDER BY created_at' % placeholders,
            TERMINAL_STATES
        )
        return cursor.fetchall()

    def get_fills(self, order_id=None):
        """
        Return recorded fills, optionally for one order.

        Parameters
        ----------
        order_id : `str`, optional
            Restrict to a single order.

        Returns
        -------
        `list[sqlite3.Row]`
            The fill rows.
        """
        if order_id is None:
            return self.conn.execute(
                'SELECT * FROM fills ORDER BY engine_time'
            ).fetchall()
        return self.conn.execute(
            'SELECT * FROM fills WHERE order_id = ? ORDER BY engine_time',
            (order_id,)
        ).fetchall()

    def get_equity_curve(self):
        """
        Return the recorded equity curve, oldest first.

        Returns
        -------
        `list[sqlite3.Row]`
            The equity rows.
        """
        return self.conn.execute(
            'SELECT * FROM equity_curve ORDER BY recorded_at'
        ).fetchall()
