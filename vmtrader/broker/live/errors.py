"""
Venue-neutral exceptions for the live plane.

These exist so that the engine can report a live failure without
naming a broker. Before they did, LiveDataHandler raised the KIS
parser's own exception for a price it could not obtain, which meant a
second venue's price failure would have been reported as a KIS error.

Vendor modules raise subclasses. A caller that wants to handle any
venue's parse failure catches VenueParseError; a caller that only
cares about KIS catches KisParseError.
"""


class VenueError(Exception):
    """
    Base class for every failure that originates at a trading venue.
    """


class VenueParseError(VenueError, ValueError):
    """
    A venue's response could not be understood.

    Subclassed per vendor, since the field names that failed to parse
    are the vendor's. Inherits ValueError because that is what the
    per-vendor errors were before this class existed, and callers
    outside the engine may still be catching it.
    """


class PriceUnavailable(VenueError, ValueError):
    """
    No usable price is available for an asset.

    Raised rather than returning zero or NaN, because a mark is the
    order sizer's divisor: a bad one must stop the trade for that
    asset instead of producing a nonsensical quantity.
    """
