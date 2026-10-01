"""The listing surface of ``HostawaySession``, driven against mocked routes.

Each test asserts on what went onto the wire — the path, the query and the exact
request body — or on the value the session hands back, never on how the session
is built inside.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
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
    villa,
)


def session(base_url: str = BASE_URL) -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=base_url)


async def test_list_listings_returns_the_result_and_the_total_count(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(
        respx_mock,
        "GET",
        "/listings",
        steps=[ok([villa(1001), villa(1002, name="Villa Nira")], count=17)],
    )

    listings, count = await session().list_listings(limit=50, offset=0)

    assert [listing["id"] for listing in listings] == [1001, 1002]
    assert count == 17
    assert dict(httpx.URL(str(route.calls[0].request.url)).params) == {
        "limit": "50",
        "offset": "0",
    }


# What a Hostaway envelope can carry where the documented integer count belongs.
# A proxy, a stub or a bad deploy puts any of these there, and none of them is a
# total this seam can report: a numeric string is listed too, because "readable
# if you squint" is the half-guard that lets a malformed body pass as a page.
OFF_CONTRACT_COUNTS: dict[str, Any] = {
    "null": None,
    "a word": "abc",
    "a numeric string": "17",
    "an object": {},
    "an array": [1],
    "a boolean": True,
    "a negative total": -1,
}


@pytest.mark.parametrize("count", OFF_CONTRACT_COUNTS.values(), ids=OFF_CONTRACT_COUNTS)
async def test_list_listings_reports_a_count_it_cannot_read_as_zero(
    respx_mock: respx.MockRouter, count: Any
) -> None:
    """A count this seam cannot read defaults, exactly as an unreadable result does.

    ``list_listings`` is the permissive surface — the page a caller just wants to
    look at — so both halves of the envelope are guarded the same way and a count
    it cannot read costs the page nothing. What it must never do is hand the
    caller a raw ``TypeError`` or ``ValueError`` from underneath the session; a
    caller that has to trust the total asks ``list_listings_page``, which refuses.
    """
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok([villa(1001)], count=count)])

    listings, total = await session().list_listings()

    assert ([listing["id"] for listing in listings], total) == ([1001], 0)


async def test_list_listings_reports_an_envelope_with_no_count_as_zero(
    respx_mock: respx.MockRouter,
) -> None:
    """A body that never mentions a count is the same default, not a ``KeyError``.

    Distinct from ``count: null`` on the wire even though both reach the guard as
    ``None``: this is the body that has no count field at all.
    """
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok([villa(1001)])])

    listings, total = await session().list_listings()

    assert ([listing["id"] for listing in listings], total) == ([1001], 0)


async def test_get_listing_asks_for_the_listing_sub_resources(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", f"/listings/{VILLA_ID}", steps=[ok(villa())])

    listing = await session().get_listing(VILLA_ID)

    assert listing["id"] == VILLA_ID
    assert dict(httpx.URL(str(route.calls[0].request.url)).params) == {"includeResources": "1"}


@pytest.mark.parametrize("base_url", ["https://sandbox.example.test/v1"])
async def test_a_session_talks_to_the_base_url_it_was_given(
    respx_mock: respx.MockRouter, base_url: str
) -> None:
    respx_mock.post(f"{base_url}/accessTokens").mock(
        return_value=httpx.Response(
            200,
            json={
                "token_type": "Bearer",
                "expires_in": 63072000,
                "access_token": "tok-sandbox-padded-1234567890",
            },
        )
    )
    route = respx_mock.get(f"{base_url}/listings").mock(
        return_value=httpx.Response(200, json={"status": "success", "result": [], "count": 0})
    )

    listings, count = await session(base_url).list_listings()

    assert (listings, count) == ([], 0)
    assert route.called


async def test_get_listing_readback_re_reads_the_listing_after_a_write(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", f"/listings/{VILLA_ID}", steps=[ok(villa(name="Villa Nira"))])

    listing = await session().get_listing_readback(VILLA_ID)

    assert listing["name"] == "Villa Nira"


async def test_get_listing_photos_returns_the_listing_images(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    images = [{"id": 5001, "caption": "Pool at dusk"}, {"id": 5002, "caption": "Kitchen"}]
    mock_endpoint(
        respx_mock, "GET", f"/listings/{VILLA_ID}", steps=[ok(villa(listingImages=images))]
    )

    assert await session().get_listing_photos(VILLA_ID) == images


async def test_get_listing_photos_is_empty_when_the_listing_carries_none(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", f"/listings/{VILLA_ID}", steps=[ok(villa())])

    assert await session().get_listing_photos(VILLA_ID) == []


async def test_get_listing_availability_passes_the_date_range_as_query(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    days = [{"date": "2026-10-01", "isAvailable": 1}, {"date": "2026-10-02", "isAvailable": 0}]
    route = mock_endpoint(respx_mock, "GET", f"/listings/{VILLA_ID}/calendar", steps=[ok(days)])

    calendar = await session().get_listing_availability(VILLA_ID, "2026-10-01", "2026-10-02")

    assert calendar == days
    assert dict(httpx.URL(str(route.calls[0].request.url)).params) == {
        "startDate": "2026-10-01",
        "endDate": "2026-10-02",
    }
