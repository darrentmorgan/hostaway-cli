"""Where a session is pointed, judged from its base URL alone.

Only Hostaway's own host is LIVE; every other base URL — a demo server, a
record-and-replay proxy, a staging stand-in — is SANDBOX.  A flag could be set
wrongly in either direction and reading "LIVE" over a fake server is the same
mistake as reading "SANDBOX" over the real one, so the URL, which cannot be
mislabelled, is the only input (docs/adr/0004).
"""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlsplit

LIVE_HOST = "api.hostaway.com"

__all__ = ["LIVE_HOST", "Surface", "surface_of"]


class Surface(StrEnum):
    """What a session is talking to, as the banner names it."""

    LIVE = "LIVE"
    SANDBOX = "SANDBOX"


def surface_of(base_url: str) -> Surface:
    """LIVE only when the base URL's host is Hostaway's own; SANDBOX otherwise.

    The host is compared whole, so a look-alike domain that merely starts with
    or contains Hostaway's host is SANDBOX, and a base URL with no host at all —
    which cannot reach Hostaway — is SANDBOX rather than a guess.
    """
    return Surface.LIVE if urlsplit(base_url).hostname == LIVE_HOST else Surface.SANDBOX
