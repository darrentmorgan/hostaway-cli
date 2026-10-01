"""Listing image uploads and the read-back that proves them, for ``HostawaySession``.

Package-private mixin: it reaches the network through the session's transport
and re-reads listings through the session's own read-back.

Hostaway's image endpoint queues the work, answers before it is done, and offers
no idempotency key.  Two consequences shape everything here.  The POST is sent
once and never retried — a retried upload is how a listing ends up with the same
photo twice, with no way to tell which row to delete.  And the answer is not the
proof: an accepted upload can still be dropped, so what settles the outcome is
reading the listing back and finding the image on it (docs/adr/0001).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import httpx

from hostaway_cli._transport import HostawayTransport
from hostaway_cli.errors import HostawayReadbackError
from hostaway_cli.models import HostawayListingImage

# Statuses that leave the upload genuinely unsettled: the request may have been
# queued before the failure. Everything else in the 4xx range is a refusal.
AMBIGUOUS_STATUS = frozenset({408, 409, 429})


class _ListingImagesMixin:
    """The ``/listings/{id}/images`` surface of ``HostawaySession``."""

    if TYPE_CHECKING:
        # Provided by the session.
        _transport: HostawayTransport

        async def get_listing_readback(self, listing_id: int) -> dict[str, Any]: ...

    async def upload_listing_images(
        self,
        listing_id: int,
        images: Sequence[HostawayListingImage | Mapping[str, Any]],
        *,
        max_readback_attempts: int = 5,
        readback_interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """Add images to a listing and return the listing that proves they landed.

        The listing is read first: an image it already carries with the same URL
        and the same captions and sort order is not posted again.  If that leaves
        nothing to do, no upload is sent at all.

        What comes back is the listing as Hostaway holds it once every posted
        image is on it.  If the queue has not caught up, the read-back is
        repeated up to ``max_readback_attempts`` times, ``readback_interval_seconds``
        apart.  An image still missing then raises
        :class:`~hostaway_cli.errors.HostawayReadbackError`, whose code says
        whether the upload was accepted and dropped
        (``image_upload_not_reconciled``) or never settled at all
        (``image_upload_ambiguous``) — the second means the operator has to look
        before sending it again.
        """
        wanted = _validated_images(images)
        if max_readback_attempts <= 0:
            raise ValueError("max_readback_attempts must be positive")
        if readback_interval_seconds < 0:
            raise ValueError("readback_interval_seconds cannot be negative")

        before = await self.get_listing_readback(listing_id)
        pending = [image for image in wanted if not _listing_carries(before, image)]
        if not pending:
            return before

        endpoint = f"/listings/{listing_id}/images"
        payload = {"images": [image.to_wire() for image in pending]}
        try:
            response = await self._transport.send_once("POST", endpoint, json=payload)
        except httpx.RequestError as exc:
            ambiguous: bool = True
            detail: object = {"exception_type": type(exc).__name__}
        else:
            ambiguous, detail = _upload_outcome(response, endpoint)

        return await self._reconcile_images(
            listing_id,
            pending,
            max_attempts=max_readback_attempts,
            interval_seconds=readback_interval_seconds,
            ambiguous=ambiguous,
            detail=detail,
        )

    async def upload_listing_image(
        self,
        listing_id: int,
        image: HostawayListingImage | Mapping[str, Any],
        *,
        max_readback_attempts: int = 5,
        readback_interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """One image, through :meth:`upload_listing_images`."""
        return await self.upload_listing_images(
            listing_id,
            [image],
            max_readback_attempts=max_readback_attempts,
            readback_interval_seconds=readback_interval_seconds,
        )

    async def _reconcile_images(
        self,
        listing_id: int,
        expected: list[HostawayListingImage],
        *,
        max_attempts: int,
        interval_seconds: float,
        ambiguous: bool,
        detail: object,
    ) -> dict[str, Any]:
        """Re-read the listing until every posted image is on it, or refuse."""
        current: dict[str, Any] = {}
        for attempt in range(max_attempts):
            if attempt:
                await asyncio.sleep(interval_seconds)
            current = await self.get_listing_readback(listing_id)
            if all(_listing_carries(current, image) for image in expected):
                return current
        missing = [image.to_wire() for image in expected if not _listing_carries(current, image)]
        raise HostawayReadbackError(
            "image_upload_ambiguous" if ambiguous else "image_upload_not_reconciled",
            listing_id=listing_id,
            detail={
                "expected": [image.to_wire() for image in expected],
                "missing": missing,
                "last_readback": current,
                "context": detail,
            },
        )


def _validated_images(
    images: Sequence[HostawayListingImage | Mapping[str, Any]],
) -> list[HostawayListingImage]:
    """The requested images as validated models, or a refusal before anything is sent."""
    validated: list[HostawayListingImage] = []
    for image in images:
        if isinstance(image, HostawayListingImage):
            validated.append(image)
        elif isinstance(image, Mapping):
            validated.append(HostawayListingImage.model_validate(dict(image)))
        else:
            raise TypeError("images must be HostawayListingImage values or mappings")
    if not validated:
        raise ValueError("at least one image must be provided")
    return validated


def _upload_outcome(response: httpx.Response, endpoint: str) -> tuple[bool, object]:
    """Whether one upload response leaves the outcome unsettled, and why.

    A refusal that cannot have queued anything is raised here as the typed error
    it is; everything else goes to the read-back to be settled by the listing.
    """
    status = response.status_code
    if status in AMBIGUOUS_STATUS or status >= 500:
        return True, {"status_code": status, "body": response.text}
    if not 200 <= status < 300:
        raise HostawayTransport.status_error(endpoint, response)
    try:
        body = response.json()
    except (TypeError, ValueError):
        body = None
    if not isinstance(body, dict):
        # A 2xx whose body cannot be read says nothing about the queue either way.
        return True, {"status_code": status, "body": response.text}
    return False, {"upload_response": body}


def _listing_carries(listing: Mapping[str, Any], expected: HostawayListingImage) -> bool:
    """Whether the listing already holds this exact image.

    Exact means every field that was sent: an image at the same URL with a
    different caption is a row still waiting to be corrected, not a match.
    """
    rows = listing.get("listingImages")
    if not isinstance(rows, list):
        return False
    wire = expected.to_wire()
    for row in rows:
        if not isinstance(row, Mapping) or row.get("url") != wire["url"]:
            continue
        if all(_row_field(row, key) == value for key, value in wire.items() if key != "url"):
            return True
    return False


def _row_field(row: Mapping[str, Any], key: str) -> Any:
    """One field of a listing image row, under either name Hostaway gives it."""
    # Hostaway takes ``sortOrder`` on the way in and can return it as ``order``.
    if key == "sortOrder" and key not in row:
        return row.get("order")
    return row.get(key)
