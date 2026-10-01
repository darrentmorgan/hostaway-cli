"""The review reads of ``HostawaySession``.

Package-private mixin: the transport core (``_get``) belongs to the session,
which mixes this class in.  What this module owns is ``/reviews``'s own query
dialect — its list filters are indexed keys, not repeated or comma-joined ones.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from hostaway_cli._envelope import readable_count

REVIEWS = "/reviews"


class _ReviewsMixin:
    """The ``/reviews`` surface of ``HostawaySession``."""

    if TYPE_CHECKING:
        # Provided by the session's transport core.
        async def _get(self, endpoint: str, *, params: dict[str, Any]) -> dict[str, Any]: ...

    async def get_reviews(
        self,
        *,
        listing_map_ids: Sequence[int] | None = None,
        statuses: Sequence[str] | None = None,
        review_type: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        departure_date_start: str | None = None,
        departure_date_end: str | None = None,
        reservation_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of reviews and the account's total matching count.

        Unlike ``/reservations``, this endpoint does honour ``sort_by`` and
        ``sort_order``.  The total is permissive: one this seam cannot read comes
        back as zero rather than as an error about a field the caller may not care
        about — see :func:`hostaway_cli._envelope.readable_count`.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        # Hostaway reads these two as indexed keys. A repeated key or a joined
        # value is accepted and then matches nothing, which reads as "no reviews".
        for index, listing_map_id in enumerate(listing_map_ids or ()):
            params[f"listingMapIds[{index}]"] = listing_map_id
        for index, status in enumerate(statuses or ()):
            params[f"statuses[{index}]"] = status
        named = {
            "type": review_type,
            "sortBy": sort_by,
            "sortOrder": sort_order,
            "departureDateStart": departure_date_start,
            "departureDateEnd": departure_date_end,
            "reservationId": reservation_id,
        }
        params.update({key: value for key, value in named.items() if value is not None})
        data = await self._get(REVIEWS, params=params)
        result = data.get("result", [])
        return (result if isinstance(result, list) else []), readable_count(data.get("count"))

    async def get_review(self, review_id: int) -> dict[str, Any]:
        """One review in full, as Hostaway holds it."""
        data = await self._get(f"{REVIEWS}/{review_id}", params={})
        result = data.get("result", {})
        return result if isinstance(result, dict) else {}
