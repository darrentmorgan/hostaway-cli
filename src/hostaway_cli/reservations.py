"""What a reservation is allowed to show an operator.

A reservation is the one Hostaway object that carries another person's details:
their name, their email address, their phone number, the address they gave the
channel.  A terminal is a shared, logged, scrolled-back place, so the CLI prints
an allowlist rather than a redaction list: a field Hostaway adds later is absent
until somebody puts it in ``SAFE_RESERVATION_FIELDS`` on purpose.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "RESERVATION_IDENTITY_FIELDS",
    "SAFE_RESERVATION_FIELDS",
    "reservation_identities",
    "safe_reservation",
]

# The fixed allowlist of reservation fields the CLI prints: the identifiers that
# name the stay, where and when it is, and what it is worth.  Guest name, email,
# phone and address are deliberately not here, and nothing personal may be added.
SAFE_RESERVATION_FIELDS: tuple[str, ...] = (
    "id",
    "reservationId",
    "channelReservationId",
    "channelName",
    "listingMapId",
    "listingName",
    "arrivalDate",
    "departureDate",
    "status",
    "totalPrice",
    "currency",
    "currencyCode",
    "paymentStatus",
)


def safe_reservation(booking: Mapping[str, Any]) -> dict[str, Any]:
    """One reservation reduced to :data:`SAFE_RESERVATION_FIELDS`.

    Every allowed field is present in the result, missing ones as ``None``, so
    the printed shape is the same for every reservation and a reader can tell a
    field Hostaway left empty from one this projection dropped.
    """
    return {field: booking.get(field) for field in SAFE_RESERVATION_FIELDS}


# The three fields any one reservation can be named by: Hostaway's own ID, the
# reservation ID it publishes, and the ID the channel booked it under. An
# operator reconciling a payout has whichever of them their statement carries.
RESERVATION_IDENTITY_FIELDS: tuple[str, ...] = (
    "id",
    "reservationId",
    "channelReservationId",
)


def reservation_identities(booking: Mapping[str, Any]) -> set[str]:
    """Every ID this reservation answers to, as text, for matching against input."""
    return {
        str(booking[field])
        for field in RESERVATION_IDENTITY_FIELDS
        if booking.get(field) is not None
    }
