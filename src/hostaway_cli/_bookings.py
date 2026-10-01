"""The reservation reads of ``HostawaySession``.

Package-private mixin: the transport core (``_get``) belongs to the session,
which mixes this class in.  What this module owns is the translation between the
arguments a caller writes and the query keys Hostaway answers to — a pairing
where a wrong name is not an error but a filter that silently does nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

RESERVATIONS = "/reservations"

# Every reservation filter, under the query key Hostaway reads it as. The date
# pairs are the ones worth reading twice: a *check-in* bound is an ``arrival``
# key and a *check-out* bound is a ``departure`` key, and swapping them returns
# stays that overlap the window from the wrong end.
BOOKING_QUERY_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "listing_id": "listingId",
        "check_in_from": "arrivalStartDate",
        "check_in_to": "arrivalEndDate",
        "check_out_from": "departureStartDate",
        "check_out_to": "departureEndDate",
        "guest_email": "guestEmail",
        "booking_source": "channelName",
        "min_guests": "minGuests",
        "max_guests": "maxGuests",
    }
)


class _BookingsMixin:
    """The ``/reservations`` surface of ``HostawaySession``."""

    if TYPE_CHECKING:
        # Provided by the session's transport core.
        async def _get(self, endpoint: str, *, params: dict[str, Any]) -> dict[str, Any]: ...

    async def search_bookings(
        self,
        *,
        listing_id: int | None = None,
        check_in_from: str | None = None,
        check_in_to: str | None = None,
        check_out_from: str | None = None,
        check_out_to: str | None = None,
        status: list[str] | None = None,
        guest_email: str | None = None,
        booking_source: str | None = None,
        min_guests: int | None = None,
        max_guests: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """One page of reservations matching every filter given.

        A filter left unset is not sent. The reservations come back in the order
        Hostaway returns them and there is no ordering argument: Hostaway does not
        honour one on this endpoint, so a caller that needs an order sorts the page
        itself. (:meth:`get_reviews` does take one — ``/reviews`` honours it.)
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        named: dict[str, Any] = {
            "listing_id": listing_id,
            "check_in_from": check_in_from,
            "check_in_to": check_in_to,
            "check_out_from": check_out_from,
            "check_out_to": check_out_to,
            "guest_email": guest_email,
            "booking_source": booking_source,
            "min_guests": min_guests,
            "max_guests": max_guests,
        }
        for key, value in named.items():
            if value is not None:
                params[BOOKING_QUERY_NAMES[key]] = value
        if status is not None:
            params["status"] = ",".join(status)
        data = await self._get(RESERVATIONS, params=params)
        result = data.get("result", [])
        return result if isinstance(result, list) else []

    async def get_booking(self, booking_id: int) -> dict[str, Any]:
        """One reservation in full, as Hostaway holds it."""
        data = await self._get(f"{RESERVATIONS}/{booking_id}", params={})
        result = data.get("result", {})
        return result if isinstance(result, dict) else {}
