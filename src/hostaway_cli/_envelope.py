"""Readers for the parts of a Hostaway envelope more than one resource shares.

Package-private.  Hostaway wraps a page as ``{"status", "result", "count"}``,
and how much of that a seam is willing to guess at is a decision, not a detail:
everything here is the permissive half, for a page a caller only wants to look
at.  A seam that has to *prove* a scan refuses instead — see
``HostawayListingPage`` in ``models.py``.
"""

from __future__ import annotations


def readable_count(value: object) -> int:
    """The total an envelope carries, or zero when it carries none readable.

    A count is an integer or it is not.  Absent, null, a string, a bool or a
    negative all become zero: parsing a numeric string here would be the
    half-guard that lets a malformed body pass as a page, and raising would hand
    a caller who only wanted the page an error about a field it never read.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
