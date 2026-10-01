"""Pure builders for the listing write bodies.

Hostaway accepts a PUT that names a field it does not have, reports success and
discards it, so the wire names below are the ones a listing actually carries —
not the prettier names an earlier client sent.  Everything here is a plain
function over plain data: no HTTP, no session, no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

BOOKINGCOM_PROPERTY_NAME = "bookingcomPropertyName"

# Hostaway answers 403 Forbidden — not a validation error — when this field
# carries a pipe or a comma; either character alone does it. Refusing locally
# turns an unexplained permission error into a sentence about the value.
BOOKINGCOM_REJECTED_CHARACTERS = ("|", ",")

# The friendly names ``update_listing`` takes, and the wire key each one writes.
# A listing carries bedroomsNumber/bathroomsNumber/personCapacity/zipcode/lat/lng
# and has no bedrooms/bathrooms/maxGuests/zipCode/latitude/longitude key at all.
LISTING_FIELD_WIRE_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "name": "name",
        "description": "description",
        "bedrooms": "bedroomsNumber",
        "bathrooms": "bathroomsNumber",
        "max_guests": "personCapacity",
        "address": "address",
        "city": "city",
        "state": "state",
        "country": "country",
        "zip_code": "zipcode",
        "latitude": "lat",
        "longitude": "lng",
        "cancellation_policy": "cancellationPolicy",
        "check_in_time_start": "checkInTimeStart",
        "check_out_time": "checkOutTime",
        "instant_bookable": "instantBookable",
    }
)

# Hostaway reads flags as the integer enum 0/1; JSON true/false can be discarded.
_INTEGER_FLAGS = frozenset({"instant_bookable"})
_CALENDAR_INTEGER_FLAGS = frozenset({"isAvailable", "closedOnArrival", "closedOnDeparture"})


def check_bookingcom_property_name(value: Any) -> None:
    """Refuse a Booking.com property name Hostaway will answer 403 to."""
    if isinstance(value, str) and any(c in value for c in BOOKINGCOM_REJECTED_CHARACTERS):
        rejected = " and ".join(repr(c) for c in BOOKINGCOM_REJECTED_CHARACTERS)
        raise ValueError(
            f"{BOOKINGCOM_PROPERTY_NAME} rejects {rejected} (Hostaway answers 403). "
            f"Got {value!r} — use the plain property name."
        )


def listing_update_payload(
    named: Mapping[str, Any] | None = None,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The body for ``PUT /listings/{id}``: wire-named, unset fields dropped.

    ``named`` uses the friendly names in :data:`LISTING_FIELD_WIRE_NAMES`;
    ``fields`` is already wire-named and passes through untouched.
    """
    payload: dict[str, Any] = {}
    for key, value in (named or {}).items():
        if value is None:
            continue
        payload[LISTING_FIELD_WIRE_NAMES[key]] = int(value) if key in _INTEGER_FLAGS else value
    for key, value in (fields or {}).items():
        if value is None:
            continue
        if key == BOOKINGCOM_PROPERTY_NAME:
            check_bookingcom_property_name(value)
        payload[key] = value
    if not payload:
        raise ValueError("At least one field must be provided for update")
    return payload


def calendar_update_payload(
    *,
    start_date: str,
    end_date: str,
    is_available: bool | None = None,
    price: float | None = None,
    minimum_stay: int | None = None,
    maximum_stay: int | None = None,
    closed_on_arrival: bool | None = None,
    closed_on_departure: bool | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """The body for ``PUT /listings/{id}/calendar`` over one date range."""
    proposed: dict[str, Any] = {
        "isAvailable": is_available,
        "price": price,
        "minimumStay": minimum_stay,
        "maximumStay": maximum_stay,
        "closedOnArrival": closed_on_arrival,
        "closedOnDeparture": closed_on_departure,
        "note": note,
    }
    payload = {
        key: int(value) if key in _CALENDAR_INTEGER_FLAGS else value
        for key, value in proposed.items()
        if value is not None
    }
    if not payload:
        raise ValueError("At least one field must be provided for update")
    return {**payload, "startDate": start_date, "endDate": end_date}


def amenity_payload(amenity_ids: list[int]) -> dict[str, Any]:
    """The body that replaces a listing's complete amenity set."""
    return {"listingAmenities": [{"amenityId": int(a)} for a in amenity_ids]}
