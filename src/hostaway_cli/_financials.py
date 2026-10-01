"""The finance reads of ``HostawaySession``.

Package-private mixin: it reaches the network through the session's transport
and pages reservations through :class:`._bookings._BookingsMixin`, which it
extends for that reason.

Two ways to read a period, and they are not interchangeable.  Hostaway's own
consolidated report answers the whole period in one request as CSV, and is what
a large period wants.  The per-booking collector walks ``/reservations`` and
hands back the rows, which is what a caller that has to total the money itself
— or explain a number — needs.  Neither computes revenue: this package reports
what Hostaway says, and leaves the accounting to the caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from hostaway_cli._bookings import _BookingsMixin

if TYPE_CHECKING:
    from hostaway_cli._transport import HostawayTransport

CONSOLIDATED_REPORT = "/finance/report/consolidated"

# Hostaway's page ceiling for a reservation search.
BOOKING_PAGE_SIZE = 200

# How many of those pages the collector will walk before it refuses. A period
# wider than this is a period the consolidated report should answer instead, so
# the ceiling exists to say so rather than to page a whole account by accident.
MAX_REPORT_PAGES = 100


class _FinancialsMixin(_BookingsMixin):
    """The ``/finance`` reports and the paginated per-booking collector."""

    if TYPE_CHECKING:
        # Provided by the session.
        _transport: HostawayTransport

    async def get_consolidated_report(
        self,
        *,
        start_date: str,
        end_date: str,
        listing_map_ids: Sequence[int] | None = None,
        date_type: str | None = None,
        channel_id: int | None = None,
        statuses: Sequence[str] | None = None,
    ) -> str:
        """Hostaway's own consolidated financial report, as the CSV text it sends.

        A POST, and still a read: the endpoint returns a report and changes
        nothing.  The answer is CSV rather than Hostaway's usual JSON envelope,
        so it is handed back as text — parsing it as JSON would fail on a report
        that arrived perfectly.
        """
        body: dict[str, Any] = {
            "fromDate": start_date,
            "toDate": end_date,
            "format": "csv",
        }
        if listing_map_ids is not None:
            body["listingMapIds"] = list(listing_map_ids)
        if date_type is not None:
            body["dateType"] = date_type
        if channel_id is not None:
            body["channelIds"] = [channel_id]
        if statuses is not None:
            body["statuses"] = list(statuses)
        response = await self._transport.send("POST", CONSOLIDATED_REPORT, json=body)
        return response.text

    async def list_bookings_for_period(
        self,
        *,
        start_date: str,
        end_date: str,
        listing_id: int | None = None,
        max_pages: int = MAX_REPORT_PAGES,
    ) -> list[dict[str, Any]]:
        """Every reservation active in a period, paged until the last one.

        Active in the period means it overlaps it: departures on or after
        ``start_date`` and arrivals on or before ``end_date``.  A stay that
        starts before the period and ends inside it is part of that period's
        money, and a window built from arrivals alone would miss it.

        A period too wide for ``max_pages`` is refused rather than half-collected:
        a truncated list of reservations is a wrong total that looks like a right
        one.  :meth:`get_consolidated_report` answers a period that large.
        """
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        collected: list[dict[str, Any]] = []
        offset = 0
        for page in range(1, max_pages + 1):
            batch = await self.search_bookings(
                listing_id=listing_id,
                check_out_from=start_date,
                check_in_to=end_date,
                limit=BOOKING_PAGE_SIZE,
                offset=offset,
            )
            collected.extend(batch)
            if len(batch) < BOOKING_PAGE_SIZE:
                return collected
            if page == max_pages:
                break
            offset += BOOKING_PAGE_SIZE
        raise RuntimeError(
            f"reservation collection for {start_date}..{end_date} exceeded {max_pages} pages "
            f"of {BOOKING_PAGE_SIZE}; use get_consolidated_report() for a period this wide"
        )
