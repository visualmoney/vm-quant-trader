"""
Exception families that cross a package boundary.

Only what more than one package must name. A failure local to the
broker belongs in 'broker/live/errors.py'; this is for the ones a
strategy actor and a broker actor both have to agree about, and which
would otherwise force one of them to import the other.

That import is not hypothetical. The strategy executor's module is
checked by AST for any route to the broker or execution packages,
because the daemon flag on its thread is only safe while that thread
cannot book anything. Naming a stop signal must not be the thing that
opens the route.

This module imports nothing.
"""


class StopRequested(Exception):
    """
    Base for every signal that says stop trading.

    One base so that a consumer loop can name the whole family in a
    single 'except' and re-raise it. The loops absorb handler failures
    on purpose -- a single consumer that dies takes everything behind
    it down -- but a stop is not a handler failure, and a stop the
    loop is obliged to swallow is not a stop at all (report
    20260826-02, S3).

    Everything 'SafetyGuard.check_can_trade' raises is one of these,
    and nothing else is. That is what makes the family checkable: the
    gate and the exception base are two views of one rule.
    """
