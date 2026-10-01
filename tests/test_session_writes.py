"""Listing writes: the exact body that reaches Hostaway, and what is refused first.

A write that names the wrong wire key is accepted by Hostaway and then silently
discarded, so these tests assert on the request body rather than on a return
value or a mocked call count.
"""

from __future__ import annotations

import pytest
import respx

from hostaway_cli import HostawayReadbackError, HostawaySession
from hostaway_mocks import (
    ACCOUNT_ID,
    BASE_URL,
    SECRET_KEY,
    VILLA_ID,
    mock_access_tokens,
    mock_endpoint,
    ok,
    sent_bodies,
    sent_body,
    villa,
)

LISTING = f"/listings/{VILLA_ID}"
CALENDAR = f"{LISTING}/calendar"


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


def put_listing(respx_mock: respx.MockRouter) -> respx.Route:
    mock_access_tokens(respx_mock)
    return mock_endpoint(respx_mock, "PUT", LISTING, steps=[ok(villa())])


# --- ordinary field updates -------------------------------------------------


async def test_update_listing_sends_only_the_fields_it_was_given(
    respx_mock: respx.MockRouter,
) -> None:
    route = put_listing(respx_mock)

    await session().update_listing(VILLA_ID, name="Villa Nira", city="Ubud")

    assert sent_body(route) == {"name": "Villa Nira", "city": "Ubud"}


async def test_update_listing_uses_the_wire_names_a_listing_actually_carries(
    respx_mock: respx.MockRouter,
) -> None:
    """A listing has bedroomsNumber and lat/lng; the pretty names write nothing."""
    route = put_listing(respx_mock)

    await session().update_listing(
        VILLA_ID,
        bedrooms=3,
        bathrooms=2.5,
        max_guests=6,
        zip_code="12345",
        latitude=-8.5,
        longitude=115.2,
    )

    assert sent_body(route) == {
        "bedroomsNumber": 3,
        "bathroomsNumber": 2.5,
        "personCapacity": 6,
        "zipcode": "12345",
        "lat": -8.5,
        "lng": 115.2,
    }


async def test_every_friendly_field_name_maps_to_a_wire_key(
    respx_mock: respx.MockRouter,
) -> None:
    """One test over the whole map: an unmapped name is a write Hostaway discards."""
    route = put_listing(respx_mock)

    await session().update_listing(
        VILLA_ID,
        name="Villa Nira",
        description="Three bedrooms above the river.",
        bedrooms=3,
        bathrooms=2.5,
        max_guests=6,
        address="Jalan Contoh 12",
        city="Ubud",
        state="Exampleshire",
        country="Indonesia",
        zip_code="12345",
        latitude=-8.5,
        longitude=115.2,
        cancellation_policy="moderate",
        check_in_time_start=14,
        check_out_time=11,
        instant_bookable=True,
    )

    assert sent_body(route) == {
        "name": "Villa Nira",
        "description": "Three bedrooms above the river.",
        "bedroomsNumber": 3,
        "bathroomsNumber": 2.5,
        "personCapacity": 6,
        "address": "Jalan Contoh 12",
        "city": "Ubud",
        "state": "Exampleshire",
        "country": "Indonesia",
        "zipcode": "12345",
        "lat": -8.5,
        "lng": 115.2,
        "cancellationPolicy": "moderate",
        "checkInTimeStart": 14,
        "checkOutTime": 11,
        "instantBookable": 1,
    }


async def test_update_listing_sends_a_flag_as_the_integer_hostaway_expects(
    respx_mock: respx.MockRouter,
) -> None:
    """Instant book off is 0, and 0 has to survive the drop-the-unset filter."""
    route = put_listing(respx_mock)

    await session().update_listing(VILLA_ID, instant_bookable=False)

    assert sent_body(route) == {"instantBookable": 0}


async def test_update_listing_merges_wire_fields_with_the_named_ones(
    respx_mock: respx.MockRouter,
) -> None:
    route = put_listing(respx_mock)

    await session().update_listing(
        VILLA_ID, name="Villa Nira", fields={"internalListingName": "NIRA-01"}
    )

    assert sent_body(route) == {"name": "Villa Nira", "internalListingName": "NIRA-01"}


async def test_update_listing_returns_the_listing_hostaway_answered_with(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "PUT", LISTING, steps=[ok(villa(name="Villa Nira"))])

    result = await session().update_listing(VILLA_ID, name="Villa Nira")

    assert result["name"] == "Villa Nira"


async def test_update_listing_with_nothing_to_write_never_reaches_hostaway(
    respx_mock: respx.MockRouter,
) -> None:
    route = put_listing(respx_mock)

    with pytest.raises(ValueError, match="At least one field"):
        await session().update_listing(VILLA_ID)

    assert not route.called


@pytest.mark.parametrize("name", ["Villa Nira | Ubud", "Villa Nira, Ubud"])
async def test_a_bookingcom_property_name_with_a_pipe_or_comma_is_refused_locally(
    respx_mock: respx.MockRouter, name: str
) -> None:
    """Hostaway answers 403, not a validation error, so say why before sending."""
    route = put_listing(respx_mock)

    with pytest.raises(ValueError, match="bookingcomPropertyName"):
        await session().update_listing(VILLA_ID, fields={"bookingcomPropertyName": name})

    assert not route.called


async def test_a_plain_bookingcom_property_name_is_sent(respx_mock: respx.MockRouter) -> None:
    route = put_listing(respx_mock)

    await session().update_listing(VILLA_ID, fields={"bookingcomPropertyName": "Villa Nira"})

    assert sent_body(route) == {"bookingcomPropertyName": "Villa Nira"}


# --- calendar ---------------------------------------------------------------


async def test_update_listing_availability_carries_the_date_range_in_the_body(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "PUT", CALENDAR, steps=[ok({})])

    await session().update_listing_availability(
        VILLA_ID, "2026-10-01", "2026-10-07", is_available=False, note="Owner stay"
    )

    assert sent_body(route) == {
        "isAvailable": 0,
        "note": "Owner stay",
        "startDate": "2026-10-01",
        "endDate": "2026-10-07",
    }


async def test_update_listing_availability_sends_calendar_flags_as_integers(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "PUT", CALENDAR, steps=[ok({})])

    await session().update_listing_availability(
        VILLA_ID,
        "2026-10-01",
        "2026-10-07",
        closed_on_arrival=True,
        closed_on_departure=False,
        minimum_stay=3,
    )

    assert sent_body(route) == {
        "closedOnArrival": 1,
        "closedOnDeparture": 0,
        "minimumStay": 3,
        "startDate": "2026-10-01",
        "endDate": "2026-10-07",
    }


async def test_update_listing_availability_can_set_a_per_day_price_and_max_stay(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "PUT", CALENDAR, steps=[ok({})])

    await session().update_listing_availability(
        VILLA_ID, "2026-12-24", "2026-12-31", price=520.0, maximum_stay=14
    )

    assert sent_body(route) == {
        "price": 520.0,
        "maximumStay": 14,
        "startDate": "2026-12-24",
        "endDate": "2026-12-31",
    }


async def test_a_stay_rule_change_does_not_touch_availability(
    respx_mock: respx.MockRouter,
) -> None:
    """Minimum stay is an ordinary write; availability must not ride along."""
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "PUT", CALENDAR, steps=[ok({})])

    await session().update_listing_availability(
        VILLA_ID, "2026-10-01", "2026-10-07", minimum_stay=3
    )

    assert "isAvailable" not in sent_body(route)


async def test_update_listing_availability_with_nothing_to_write_is_refused(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "PUT", CALENDAR, steps=[ok({})])

    with pytest.raises(ValueError, match="At least one field"):
        await session().update_listing_availability(VILLA_ID, "2026-10-01", "2026-10-07")

    assert not route.called


# --- amenities --------------------------------------------------------------


async def test_update_listing_amenities_writes_the_complete_set(
    respx_mock: respx.MockRouter,
) -> None:
    route = put_listing(respx_mock)

    await session().update_listing_amenities(VILLA_ID, [1, 2, 3])

    assert sent_body(route) == {
        "listingAmenities": [{"amenityId": 1}, {"amenityId": 2}, {"amenityId": 3}]
    }


async def test_merging_amenities_keeps_the_ones_already_on_the_listing(
    respx_mock: respx.MockRouter,
) -> None:
    """Hostaway replaces the whole set, so a merge writes existing plus requested."""
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        LISTING,
        steps=[ok(villa(amenity_ids=(1, 2))), ok(villa(amenity_ids=(1, 2, 7)))],
    )
    route = mock_endpoint(respx_mock, "PUT", LISTING, steps=[ok(villa())])

    listing = await session().merge_listing_amenities(VILLA_ID, [7, 2])

    assert sent_body(route) == {
        "listingAmenities": [{"amenityId": 1}, {"amenityId": 2}, {"amenityId": 7}]
    }
    assert [row["amenityId"] for row in listing["listingAmenities"]] == [1, 2, 7]


async def test_merging_amenities_already_present_writes_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTING, steps=[ok(villa(amenity_ids=(1, 2, 3)))])
    route = mock_endpoint(respx_mock, "PUT", LISTING, steps=[ok(villa())])

    await session().merge_listing_amenities(VILLA_ID, [2, 3])

    assert not route.called


async def test_an_amenity_hostaway_silently_dropped_is_reported(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        LISTING,
        steps=[ok(villa(amenity_ids=(1,))), ok(villa(amenity_ids=(1,)))],
    )
    mock_endpoint(respx_mock, "PUT", LISTING, steps=[ok(villa())])

    with pytest.raises(HostawayReadbackError) as caught:
        await session().merge_listing_amenities(VILLA_ID, [7])

    assert caught.value.code == "amenity_readback_mismatch"
    assert caught.value.listing_id == VILLA_ID
    assert caught.value.detail == {
        "expected_ids": [1, 7],
        "actual_ids": [1],
        "missing_ids": [7],
    }


async def test_a_listing_without_an_amenity_array_cannot_be_merged(
    respx_mock: respx.MockRouter,
) -> None:
    """No array is not an empty array: writing one would guess at the whole set."""
    mock_access_tokens(respx_mock)
    listing = villa()
    del listing["listingAmenities"]
    mock_endpoint(respx_mock, "GET", LISTING, steps=[ok(listing)])
    route = mock_endpoint(respx_mock, "PUT", LISTING, steps=[ok(villa())])

    with pytest.raises(HostawayReadbackError) as caught:
        await session().merge_listing_amenities(VILLA_ID, [7])

    assert caught.value.code == "amenity_readback_missing"
    assert not route.called


@pytest.mark.parametrize("amenity_ids", [[0], [-1], [True], ["7"]], ids=str)
async def test_merging_refuses_an_id_that_is_not_a_positive_integer(
    respx_mock: respx.MockRouter, amenity_ids: list[object]
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTING, steps=[ok(villa())])

    with pytest.raises(ValueError, match="positive integers"):
        await session().merge_listing_amenities(VILLA_ID, amenity_ids)  # type: ignore[arg-type]

    assert not route.called


async def test_merging_an_amenity_asked_for_twice_writes_it_once(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        LISTING,
        steps=[ok(villa(amenity_ids=())), ok(villa(amenity_ids=(7,)))],
    )
    route = mock_endpoint(respx_mock, "PUT", LISTING, steps=[ok(villa())])

    await session().merge_listing_amenities(VILLA_ID, [7, 7])

    assert sent_bodies(route) == [{"listingAmenities": [{"amenityId": 7}]}]
