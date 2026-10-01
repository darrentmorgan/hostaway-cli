"""``HostawaySession`` — the authenticated client for one Hostaway account.

Every read and write goes through it, and every HTTP concern below it —
authentication, retry, rate limiting, error mapping — belongs to the transport
in ``_transport.py``.  The session is bound to one account and one base URL, so
pointing it at a sandbox is a constructor argument, never a global switch.

Listings are here; each of the other resource families is a mixin of its own,
because what makes them different from each other is not the HTTP but the
resource: ``/reviews`` has its own query dialect, a finance report answers in
CSV, an image upload is only proved by reading the listing back.  They compose
into one session, so a caller has one object and one import.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from hostaway_cli._bookings import _BookingsMixin
from hostaway_cli._catalog_reads import _CatalogReadsMixin
from hostaway_cli._envelope import readable_count
from hostaway_cli._financials import _FinancialsMixin
from hostaway_cli._images import _ListingImagesMixin
from hostaway_cli._reviews import _ReviewsMixin
from hostaway_cli._token import TokenStore
from hostaway_cli._transport import HostawayTransport
from hostaway_cli.errors import (
    HostawayCreateError,
    HostawayPaginationError,
    HostawayReadbackError,
    create_error_code,
)
from hostaway_cli.models import HostawayListingPage
from hostaway_cli.payloads import (
    amenity_payload,
    calendar_update_payload,
    listing_update_payload,
)

HOSTAWAY_API_BASE_URL = "https://api.hostaway.com/v1"

LISTINGS = "/listings"

__all__ = ["HOSTAWAY_API_BASE_URL", "HostawaySession"]


class HostawaySession(
    # ``_FinancialsMixin`` extends ``_BookingsMixin`` — it pages
    # ``search_bookings`` — so it has to precede it for a valid MRO.
    _FinancialsMixin,
    _BookingsMixin,
    _CatalogReadsMixin,
    _ListingImagesMixin,
    _ReviewsMixin,
):
    """One account's Hostaway connection. Owns its HTTP client and token state.

    ``token_cache`` is optional and read as the session is built, so a cache that
    refuses — the wrong account, a file other users can read — raises here rather
    than on the first request.
    """

    def __init__(
        self,
        *,
        account_id: str,
        secret_key: str,
        base_url: str = HOSTAWAY_API_BASE_URL,
        token_cache: TokenStore | None = None,
    ) -> None:
        self.account_id = account_id
        self.base_url = base_url
        self._transport = HostawayTransport(
            base_url=base_url,
            account_id=account_id,
            secret_key=secret_key,
            token_cache=token_cache,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()

    # --- listings: reads ---------------------------------------------------

    async def list_listings(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of listings and the account's total listing count.

        Permissive by design: both halves of the envelope are guarded, and one
        this seam cannot read defaults rather than raising — an unreadable result
        is an empty page, an unreadable count is zero. A caller that has to trust
        the total wants :meth:`list_listings_page`, which refuses instead.
        """
        data = await self._get(LISTINGS, params={"limit": limit, "offset": offset})
        result = data.get("result")
        count = data.get("count")
        return (result if isinstance(result, list) else []), readable_count(count)

    async def list_listings_page(self, *, limit: int, offset: int) -> HostawayListingPage:
        """One page of listings, proved complete and unambiguous or refused.

        ``list_listings`` stays permissive for callers that just want the page.
        This is the seam for a caller walking the whole account: it never defaults
        or coerces a pagination field, and it keeps the body Hostaway sent.
        """
        try:
            HostawayListingPage.check_request(limit=limit, offset=offset)
        except ValueError as exc:
            raise HostawayPaginationError(str(exc), endpoint=LISTINGS) from exc
        response = await self._transport.send(
            "GET", LISTINGS, params={"limit": limit, "offset": offset}
        )
        if response.status_code != 200:
            raise HostawayPaginationError(
                "pagination_status_invalid",
                endpoint=LISTINGS,
                detail={"status_code": response.status_code, "body": response.text},
            )
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise HostawayPaginationError(
                "pagination_body_invalid", endpoint=LISTINGS, detail=response.text
            ) from exc
        try:
            return HostawayListingPage.from_body(
                body, requested_limit=limit, requested_offset=offset
            )
        except ValueError as exc:
            raise HostawayPaginationError(str(exc), endpoint=LISTINGS, detail=body) from exc

    async def get_listing(self, listing_id: int) -> dict[str, Any]:
        """One listing in full, sub-resources included."""
        data = await self._get(f"/listings/{listing_id}", params={"includeResources": "1"})
        result = data.get("result", {})
        return result if isinstance(result, dict) else {}

    async def get_listing_readback(self, listing_id: int) -> dict[str, Any]:
        """Read a listing back after an applied write, for exact reconciliation."""
        return await self.get_listing(listing_id)

    async def get_listing_photos(self, listing_id: int) -> list[dict[str, Any]]:
        """The listing's photos, each carrying its per-channel captions."""
        listing = await self.get_listing(listing_id)
        images = listing.get("listingImages", [])
        return images if isinstance(images, list) else []

    async def get_listing_availability(
        self,
        listing_id: int,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """The listing's calendar days across an inclusive date range."""
        data = await self._get(
            f"/listings/{listing_id}/calendar",
            params={"startDate": start_date, "endDate": end_date},
        )
        result = data.get("result", [])
        return result if isinstance(result, list) else []

    # --- listings: writes --------------------------------------------------

    async def update_listing(
        self,
        listing_id: int,
        *,
        fields: Mapping[str, Any] | None = None,
        name: str | None = None,
        description: str | None = None,
        bedrooms: int | None = None,
        bathrooms: int | float | None = None,
        max_guests: int | None = None,
        address: str | None = None,
        city: str | None = None,
        state: str | None = None,
        country: str | None = None,
        zip_code: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        cancellation_policy: str | None = None,
        check_in_time_start: int | None = None,
        check_out_time: int | None = None,
        instant_bookable: bool | None = None,
    ) -> dict[str, Any]:
        """Write listing fields, sending only the ones named here.

        The keyword arguments are the friendly names; ``fields`` takes anything
        else under Hostaway's own wire key. This is a partial update: a field
        left unset is not sent and cannot overwrite what the listing holds.
        """
        payload = listing_update_payload(
            {
                "name": name,
                "description": description,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "max_guests": max_guests,
                "address": address,
                "city": city,
                "state": state,
                "country": country,
                "zip_code": zip_code,
                "latitude": latitude,
                "longitude": longitude,
                "cancellation_policy": cancellation_policy,
                "check_in_time_start": check_in_time_start,
                "check_out_time": check_out_time,
                "instant_bookable": instant_bookable,
            },
            fields,
        )
        return await self._put_listing(listing_id, payload)

    async def update_listing_availability(
        self,
        listing_id: int,
        start_date: str,
        end_date: str,
        *,
        is_available: bool | None = None,
        price: float | None = None,
        minimum_stay: int | None = None,
        maximum_stay: int | None = None,
        closed_on_arrival: bool | None = None,
        closed_on_departure: bool | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Set calendar days across an inclusive date range."""
        payload = calendar_update_payload(
            start_date=start_date,
            end_date=end_date,
            is_available=is_available,
            price=price,
            minimum_stay=minimum_stay,
            maximum_stay=maximum_stay,
            closed_on_arrival=closed_on_arrival,
            closed_on_departure=closed_on_departure,
            note=note,
        )
        data = await self._send_json("PUT", f"{LISTINGS}/{listing_id}/calendar", json=payload)
        result = data.get("result", {})
        return result if isinstance(result, dict) else {}

    async def update_listing_amenities(
        self,
        listing_id: int,
        amenity_ids: Sequence[int],
    ) -> dict[str, Any]:
        """Replace a listing's COMPLETE amenity set.

        Hostaway treats ``listingAmenities`` as the whole set, so this overwrites
        every existing amenity. It is the primitive for a caller that has already
        computed removals; anything else wants :meth:`merge_listing_amenities`.
        """
        return await self._put_listing(listing_id, amenity_payload(list(amenity_ids)))

    async def merge_listing_amenities(
        self,
        listing_id: int,
        amenity_ids: Sequence[int],
    ) -> dict[str, Any]:
        """Add amenities without dropping the ones the listing already has.

        Because a write replaces the whole set, this reads the listing, merges the
        requested IDs in stable order, writes exactly that complete set once, and
        reads the listing back before reporting success.
        """
        requested = _validated_amenity_ids(amenity_ids)
        before = await self.get_listing_readback(listing_id)
        existing = _listing_amenity_ids(before, listing_id=listing_id)
        merged = list(dict.fromkeys(existing + requested))
        if merged == existing:
            return before

        await self.update_listing_amenities(listing_id, merged)
        after = await self.get_listing_readback(listing_id)
        observed = _listing_amenity_ids(after, listing_id=listing_id)
        missing = [amenity_id for amenity_id in merged if amenity_id not in observed]
        if missing:
            raise HostawayReadbackError(
                "amenity_readback_mismatch",
                listing_id=listing_id,
                detail={"expected_ids": merged, "actual_ids": observed, "missing_ids": missing},
            )
        return after

    async def create_listing(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """POST one listing exactly once. No retry, no forced token refresh.

        A repeated create could leave two listings behind with no way to tell
        which is which, so every outcome that does not prove exactly one new
        listing — a dropped connection, a 5xx, a success without a usable id —
        is reported as a create error for the operator to reconcile.
        """
        if not isinstance(payload, Mapping):
            raise HostawayCreateError("create_payload_invalid", body=payload)
        try:
            response = await self._transport.send_once("POST", LISTINGS, json=dict(payload))
        except httpx.RequestError as exc:
            raise HostawayCreateError(
                "create_ambiguous", endpoint=LISTINGS, body={"exception_type": type(exc).__name__}
            ) from exc
        body: object
        try:
            body = response.json()
        except (TypeError, ValueError):
            body = response.text
        if not 200 <= response.status_code < 300:
            raise HostawayCreateError(
                create_error_code(response.status_code),
                endpoint=LISTINGS,
                status_code=response.status_code,
                body=body,
            )
        if not isinstance(body, dict):
            raise HostawayCreateError(
                "create_ambiguous",
                endpoint=LISTINGS,
                status_code=response.status_code,
                body=body,
            )
        result = body.get("result")
        listing_id = result.get("id") if isinstance(result, dict) else None
        if (
            body.get("status") != "success"
            or isinstance(listing_id, bool)
            or not isinstance(listing_id, int)
            or listing_id <= 0
        ):
            raise HostawayCreateError(
                "create_no_positive_id",
                endpoint=LISTINGS,
                status_code=response.status_code,
                body=body,
            )
        return body

    # --- channels ----------------------------------------------------------

    async def export_to_airbnb(self, listing_id: int) -> dict[str, Any]:
        """Ask Hostaway to push this listing's saved content to Airbnb.

        A PUT saves an edit; it does not export it. This enqueues the export
        job, which Airbnb reflects a few minutes later. Fields locked on the
        Airbnb side stay as they are, silently.
        """
        endpoint = f"{LISTINGS}/{listing_id}/export/airbnb"
        response = await self._transport.send("POST", endpoint, json={})
        # An accepted export commonly answers with no body at all, which is a
        # success and must not be read as one.
        if not response.content:
            return {}
        return self._transport.parse(response, endpoint)

    # --- internals ---------------------------------------------------------
    #
    # The session reaches the network through these delegators alone; every
    # transport concern itself lives in ``_transport.py``.

    async def _put_listing(self, listing_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        data = await self._send_json("PUT", f"{LISTINGS}/{listing_id}", json=payload)
        result = data.get("result", {})
        return result if isinstance(result, dict) else {}

    async def _get(self, endpoint: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return await self._transport.get(endpoint, params=params)

    async def _send_json(
        self, method: str, endpoint: str, *, json: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._transport.send_json(method, endpoint, json=json)


def _validated_amenity_ids(amenity_ids: Sequence[int]) -> list[int]:
    """The requested amenity IDs, deduplicated, or a refusal naming the rule."""
    validated: list[int] = []
    for amenity_id in amenity_ids:
        if isinstance(amenity_id, bool) or not isinstance(amenity_id, int) or amenity_id <= 0:
            raise ValueError("amenity IDs must be positive integers")
        if amenity_id not in validated:
            validated.append(amenity_id)
    return validated


def _listing_amenity_ids(listing: Mapping[str, Any], *, listing_id: int) -> list[int]:
    """The amenity IDs a listing carries, refusing anything it cannot read exactly.

    An absent array is not an empty one: writing a merged set computed from a
    guess would delete every amenity the listing actually has.
    """
    if "listingAmenities" not in listing:
        raise HostawayReadbackError(
            "amenity_readback_missing",
            listing_id=listing_id,
            detail={"field": "listingAmenities"},
        )
    rows = listing["listingAmenities"]
    if not isinstance(rows, list):
        raise HostawayReadbackError(
            "amenity_readback_invalid",
            listing_id=listing_id,
            detail={"listingAmenities": rows},
        )
    ids: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise HostawayReadbackError(
                "amenity_readback_invalid",
                listing_id=listing_id,
                detail={"index": index, "row": row},
            )
        amenity_id = row.get("amenityId")
        if amenity_id is None:
            amenity_id = row.get("id")
        if isinstance(amenity_id, bool) or not isinstance(amenity_id, int) or amenity_id <= 0:
            raise HostawayReadbackError(
                "amenity_readback_invalid",
                listing_id=listing_id,
                detail={"index": index, "row": row},
            )
        if amenity_id not in ids:
            ids.append(amenity_id)
    return ids
