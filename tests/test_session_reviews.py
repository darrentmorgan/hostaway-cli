"""The review surface of ``HostawaySession``, driven against mocked routes.

``/reviews`` takes its list filters as indexed keys — ``listingMapIds[0]``,
``statuses[1]`` — rather than as repeated or comma-joined ones, so what these
tests pin is the exact query, and the page and total that come back.

The reviews are invented, and the guests who left them are not named.
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
)


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


def review(review_id: int, **overrides: Any) -> dict[str, Any]:
    """One invented review in the shape Hostaway returns it."""
    row: dict[str, Any] = {
        "id": review_id,
        "listingMapId": VILLA_ID,
        "reservationId": 7001,
        "type": "guest-to-host",
        "status": "published",
        "rating": 5,
        "departureDate": "2026-10-09",
    }
    row.update(overrides)
    return row


def query(route: respx.Route) -> dict[str, str]:
    return dict(httpx.URL(str(route.calls[0].request.url)).params)


async def test_get_reviews_returns_the_page_and_the_total(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    rows = [review(8001), review(8002)]
    route = mock_endpoint(respx_mock, "GET", "/reviews", steps=[ok(rows, count=42)])

    reviews, total = await session().get_reviews(limit=25, offset=50)

    assert ([row["id"] for row in reviews], total) == ([8001, 8002], 42)
    assert query(route) == {"limit": "25", "offset": "50"}


async def test_get_reviews_sends_its_list_filters_as_indexed_keys(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", "/reviews", steps=[ok([])])

    await session().get_reviews(
        listing_map_ids=[1001, 1002],
        statuses=["published", "pending"],
        review_type="guest-to-host",
        sort_by="departureDate",
        sort_order="desc",
        departure_date_start="2026-10-01",
        departure_date_end="2026-10-31",
        reservation_id=7001,
    )

    assert query(route) == {
        "listingMapIds[0]": "1001",
        "listingMapIds[1]": "1002",
        "statuses[0]": "published",
        "statuses[1]": "pending",
        "type": "guest-to-host",
        "sortBy": "departureDate",
        "sortOrder": "desc",
        "departureDateStart": "2026-10-01",
        "departureDateEnd": "2026-10-31",
        "reservationId": "7001",
        "limit": "100",
        "offset": "0",
    }


async def test_a_review_filter_left_unset_is_not_sent_at_all(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", "/reviews", steps=[ok([])])

    await session().get_reviews()

    assert query(route) == {"limit": "100", "offset": "0"}


# The same rule ``list_listings`` applies to its total: a count this seam cannot
# read is zero, never an exception a caller who only wanted the page must catch.
UNREADABLE_COUNTS: dict[str, Any] = {
    "null": None,
    "a word": "abc",
    "a numeric string": "42",
    "an object": {},
    "a boolean": True,
    "a negative total": -1,
}


@pytest.mark.parametrize("count", UNREADABLE_COUNTS.values(), ids=UNREADABLE_COUNTS)
async def test_a_review_total_that_cannot_be_read_is_reported_as_zero(
    respx_mock: respx.MockRouter, count: Any
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/reviews", steps=[ok([review(8001)], count=count)])

    reviews, total = await session().get_reviews()

    assert ([row["id"] for row in reviews], total) == ([8001], 0)


async def test_get_review_reads_one_review_by_id(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    row = review(8001, publicReview="Lovely stay, spotless villa.")
    route = mock_endpoint(respx_mock, "GET", "/reviews/8001", steps=[ok(row)])

    assert await session().get_review(8001) == row
    assert query(route) == {}
