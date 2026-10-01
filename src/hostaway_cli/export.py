"""Pushing a saved listing out to a channel.

A Hostaway PUT saves a listing edit but does not send it to Airbnb — only
booking settings reach a channel on their own. Any write that changes content or
amenities has to be followed by an export, or the change is invisible to guests.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


class Channel(StrEnum):
    """A channel a listing can be exported to.

    Hostaway exposes one export endpoint per channel, and this client carries
    Airbnb's. The enum is the whole of what an operator may name, so a channel
    added here needs a session method behind it before it can be offered.
    """

    AIRBNB = "airbnb"


class SupportsAirbnbExport(Protocol):
    """The one thing this helper needs from a session."""

    async def export_to_airbnb(self, listing_id: int) -> dict[str, object]: ...


async def export_listing_to_airbnb(session: SupportsAirbnbExport, listing_id: int) -> bool:
    """Export a listing, reporting rather than raising if the export fails.

    Returns ``True`` when the export was accepted and ``False`` when it raised.
    The exception is swallowed either way: the write it follows has already
    landed, and a flaky export must not fail the caller on top of it. A caller
    that needs the signal branches on the returned bool.
    """
    try:
        await session.export_to_airbnb(listing_id)
    except Exception as exc:
        logger.warning("Airbnb export failed for listing %d: %s", listing_id, exc)
        return False
    logger.info("Triggered Airbnb export for listing %d", listing_id)
    return True
