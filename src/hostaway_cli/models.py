"""The strict wire contracts: a listing page, and an image to be uploaded.

Both are places where a value that is *nearly* right is worse than one that is
wrong.  ``list_listings`` stays permissive — it is the surface behind ``hsctl
listings`` and a missing count there costs nothing — but a caller *walking* every
listing needs the page it holds to be provably the page it asked for, or a
listing can be silently skipped or visited twice; and an image is posted to a
queue that answers before the work is done, so the fields it carries have to be
exactly the fields the read-back will be compared against.  Everything here
refuses rather than coerces, and each refusal names what was wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

MAX_PAGE_LIMIT = 100


def _listing_id(item: Any, index: int) -> int:
    """The listing id of one page item, or a refusal naming its position."""
    invalid = ValueError(f"pagination_item_invalid:{index}")
    if not isinstance(item, dict):
        raise invalid
    listing_id = item.get("id")
    # A bool is an int in Python but never a listing id, and a numeric string is
    # not one either: accepting either would let a malformed page pass as a scan.
    if isinstance(listing_id, bool) or not isinstance(listing_id, int) or listing_id <= 0:
        raise invalid
    return listing_id


@dataclass(frozen=True)
class HostawayListingPage:
    """One validated page of listings, with the body Hostaway actually sent."""

    requested_limit: int
    requested_offset: int
    count: int
    result: tuple[dict[str, Any], ...]
    raw_body: dict[str, Any]

    @property
    def listing_ids(self) -> tuple[int, ...]:
        return tuple(_listing_id(item, index) for index, item in enumerate(self.result))

    @property
    def next_offset(self) -> int:
        """The only safe next cursor: the requested offset plus the page length."""
        return self.requested_offset + len(self.result)

    @staticmethod
    def check_request(*, limit: int, offset: int) -> None:
        """Refuse a page request Hostaway's pagination cannot answer meaningfully."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_PAGE_LIMIT
        ):
            raise ValueError("pagination_limit_invalid")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("pagination_offset_invalid")

    @classmethod
    def from_body(
        cls,
        body: Any,
        *,
        requested_limit: int,
        requested_offset: int,
    ) -> HostawayListingPage:
        """Build a page while enforcing the wire contract without coercion."""
        cls.check_request(limit=requested_limit, offset=requested_offset)
        if not isinstance(body, dict):
            raise ValueError("pagination_body_not_object")

        count = body.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("pagination_count_invalid")
        result = body.get("result")
        if not isinstance(result, list):
            raise ValueError("pagination_result_invalid")
        if len(result) > requested_limit:
            raise ValueError("pagination_page_too_large")
        if requested_offset > count:
            raise ValueError("pagination_offset_out_of_range")

        # Hostaway echoes the pagination it applied. A page answering a different
        # window than the one asked for cannot be placed in the scan.
        echoed_limit = body.get("limit")
        if "limit" in body and (
            isinstance(echoed_limit, bool)
            or not isinstance(echoed_limit, int)
            or echoed_limit != requested_limit
        ):
            raise ValueError("pagination_limit_mismatch")
        echoed_offset = body.get("offset")
        if "offset" in body and (
            isinstance(echoed_offset, bool)
            or not isinstance(echoed_offset, int)
            or echoed_offset != requested_offset
        ):
            raise ValueError("pagination_offset_mismatch")

        seen: set[int] = set()
        for index, item in enumerate(result):
            listing_id = _listing_id(item, index)
            if listing_id in seen:
                raise ValueError("pagination_duplicate_id")
            seen.add(listing_id)

        next_offset = requested_offset + len(result)
        if next_offset > count:
            raise ValueError("pagination_next_offset_exceeds_count")
        if next_offset < count and len(result) < requested_limit:
            raise ValueError("pagination_page_incomplete")

        return cls(
            requested_limit=requested_limit,
            requested_offset=requested_offset,
            count=count,
            result=tuple(result),
            raw_body=body,
        )


def _wire_field(wire_name: str) -> Any:
    """A field readable under either spelling and always written as Hostaway's.

    The Python name is what a caller writes; the wire name is what Hostaway
    takes and what a body loaded from JSON or YAML already uses, so both are
    accepted in and only Hostaway's goes out.
    """
    return Field(
        default=None,
        validation_alias=AliasChoices(wire_name, _snake(wire_name)),
        serialization_alias=wire_name,
    )


def _snake(wire_name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in wire_name)


class HostawayListingImage(BaseModel):
    """One image to add to a listing, and the fields its read-back is judged on.

    Strict and closed: a misspelled caption field would otherwise be posted,
    accepted, discarded by Hostaway, and then looked for in vain in the listing
    that comes back.  ``to_wire`` drops what was never set, so an unset caption
    is absent from the body rather than sent as null.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    url: str
    caption: str | None = None
    booking_engine_caption: str | None = _wire_field("bookingEngineCaption")
    airbnb_caption: str | None = _wire_field("airbnbCaption")
    vrbo_caption: str | None = _wire_field("vrboCaption")
    sort_order: int | None = _wire_field("sortOrder")

    @field_validator("url")
    @classmethod
    def _public_http_url(cls, value: str) -> str:
        """Hostaway fetches the image itself, so the URL has to be reachable."""
        if not value.startswith(("http://", "https://")):
            raise ValueError("a Hostaway image URL must be a public http(s) URL")
        return value

    @field_validator("sort_order")
    @classmethod
    def _non_negative_sort_order(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("sortOrder cannot be negative")
        return value

    def to_wire(self) -> dict[str, Any]:
        """The body Hostaway is sent, under its own field names, unset dropped."""
        wire: dict[str, Any] = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        return wire
