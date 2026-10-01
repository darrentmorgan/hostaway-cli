"""The write gate's own vocabulary: what is protected, and what read back (seam 3).

These are plain functions over plain data — no session, no HTTP. The commands
that use them are driven end to end in the ``test_cli_*`` modules.
"""

from __future__ import annotations

import pytest

from hostaway_cli.writes import (
    DELETES_IMAGE,
    DELETES_LISTING,
    PROTECTED_FIELDS,
    Change,
    dropped,
    protected_fields_in,
    render,
)

# The fields docs/adr/0001 names, in its own words. A field joins this set only by
# joining the ADR: the constant and the decision are meant to be read side by side.
ADR_0001_PROTECTED = {
    "price",
    "currency",
    "cleaning fee",
    "damage deposit",
    "commission/payout formula",
    "calendar availability",
    "deletion of a listing",
    "deletion of a listing photo",
}


def change(field: str, after: object = "after") -> Change:
    return Change(field=field, before="before", after=after)


def test_the_protected_fields_are_the_ones_adr_0001_names() -> None:
    assert set(PROTECTED_FIELDS.values()) == ADR_0001_PROTECTED


@pytest.mark.parametrize(
    "field",
    [
        "price",
        "currencyCode",
        "cleaningFee",
        "refundableDamageDeposit",
        "pmCommission",
        "isAvailable",
        DELETES_LISTING,
        DELETES_IMAGE,
    ],
)
def test_a_protected_field_in_the_change_is_named(field: str) -> None:
    assert protected_fields_in([change(field)]) != []


@pytest.mark.parametrize(
    "field",
    [
        # Markups are a channel multiplier over the price, not the price (docs/adr/0001).
        "airbnbOfficialListingMarkup",
        "bookingEngineMarkup",
        "minimumStay",
        "maximumStay",
        "closedOnArrival",
        "closedOnDeparture",
        "note",
        "name",
        "description",
        "listingAmenities",
        "caption",
    ],
)
def test_an_ordinary_field_is_not_protected(field: str) -> None:
    assert protected_fields_in([change(field)]) == []


def test_a_protected_field_is_named_once_however_many_days_carry_it() -> None:
    """A range write is one decision, however many rows it touches."""
    assert protected_fields_in([change("isAvailable"), change("isAvailable")]) == [
        "calendar availability"
    ]


def test_a_row_id_hostaway_adds_of_its_own_is_not_a_dropped_field() -> None:
    """Sub-resource rows come back carrying an id a write never sends."""
    sent = [{"amenityId": 1}, {"amenityId": 2}]
    stored = [{"id": 9001, "amenityId": 1}, {"id": 9002, "amenityId": 2}]

    assert dropped([(change("listingAmenities", sent), stored)]) == []


def test_a_number_stored_in_another_width_is_not_a_dropped_field() -> None:
    assert dropped([(change("bathroomsNumber", 2), 2.0)]) == []


def test_a_field_the_listing_does_not_carry_is_dropped() -> None:
    assert dropped([(change("name", "Villa Saka"), None)]) == ["name"]


def test_a_secret_is_never_written_into_the_diff() -> None:
    lines = render([Change(field="doorSecurityCode", before="4110", after="8341", secret=True)])

    assert lines == ["  doorSecurityCode: *** -> ***"]
