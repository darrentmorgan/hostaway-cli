"""The reservation surface of ``HostawaySession``, driven against mocked routes.

The friendly argument names a caller uses and the query keys Hostaway answers to
are different vocabularies, and a mistranslated one is a filter that silently
does nothing — a reservation search that quietly ignores its date window returns
the wrong stays rather than an error. So these tests pin the query that went onto
the wire, and the reservations that came back.

Every reservation here is invented, and none of them carries guest contact
detail: the session hands back what Hostaway sent, and the fixtures say what a
test needs and no more.
"""

from __future__ import annotations

import httpx
import respx

from hostaway_cli import HostawaySession
from hostaway_mocks import (
    ACCOUNT_ID,
    BASE_URL,
    SECRET_KEY,
    VILLA_ID,
    mock_access_tokens,
    mock_endpoint,
    ok,
)


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


def reservation(reservation_id: int, **overrides: object) -> dict[str, object]:
    """One invented reservation in the shape Hostaway returns it."""
    row: dict[str, object] = {
        "id": reservation_id,
        "listingMapId": VILLA_ID,
        "arrivalDate": "2026-10-04",
        "departureDate": "2026-10-09",
        "status": "new",
        "channelName": "airbnb",
        "totalPrice": 1840.0,
    }
    row.update(overrides)
    return row


def query(route: respx.Route, index: int = 0) -> dict[str, str]:
    return dict(httpx.URL(str(route.calls[index].request.url)).params)


async def test_search_bookings_sends_the_window_as_hostaway_names_it(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    rows = [reservation(7001), reservation(7002)]
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok(rows)])

    found = await session().search_bookings(
        listing_id=VILLA_ID,
        check_out_from="2026-10-01",
        check_in_to="2026-10-31",
        limit=50,
        offset=100,
    )

    assert [row["id"] for row in found] == [7001, 7002]
    assert query(route) == {
        "listingId": str(VILLA_ID),
        "departureStartDate": "2026-10-01",
        "arrivalEndDate": "2026-10-31",
        "limit": "50",
        "offset": "100",
    }


async def test_search_bookings_translates_every_filter_it_offers(
    respx_mock: respx.MockRouter,
) -> None:
    """The whole vocabulary at once, so a mistranslated key cannot hide.

    ``status`` is the one that is not a rename: Hostaway takes a single
    comma-joined value, not a repeated key.
    """
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok([])])

    await session().search_bookings(
        listing_id=VILLA_ID,
        check_in_from="2026-10-01",
        check_in_to="2026-10-31",
        check_out_from="2026-10-02",
        check_out_to="2026-11-02",
        status=["new", "modified"],
        guest_email="guest@example.test",
        booking_source="airbnb",
        min_guests=2,
        max_guests=8,
    )

    assert query(route) == {
        "listingId": str(VILLA_ID),
        "arrivalStartDate": "2026-10-01",
        "arrivalEndDate": "2026-10-31",
        "departureStartDate": "2026-10-02",
        "departureEndDate": "2026-11-02",
        "status": "new,modified",
        "guestEmail": "guest@example.test",
        "channelName": "airbnb",
        "minGuests": "2",
        "maxGuests": "8",
        "limit": "100",
        "offset": "0",
    }


async def test_a_filter_left_unset_is_not_sent_at_all(respx_mock: respx.MockRouter) -> None:
    """An unset filter must be absent, not empty: Hostaway reads an empty
    ``status`` as a status nothing matches."""
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok([])])

    await session().search_bookings()

    assert query(route) == {"limit": "100", "offset": "0"}


async def test_a_page_hostaway_answers_without_reservations_is_empty(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/reservations", steps=[httpx.Response(200, json={})])

    assert await session().search_bookings() == []


async def test_get_booking_reads_one_reservation_by_id(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    row = reservation(7001, status="modified")
    route = mock_endpoint(respx_mock, "GET", "/reservations/7001", steps=[ok(row)])

    assert await session().get_booking(7001) == row
    assert query(route) == {}


async def test_get_booking_returns_an_empty_reservation_when_the_body_carries_none(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/reservations/7001", steps=[ok([])])

    assert await session().get_booking(7001) == {}
