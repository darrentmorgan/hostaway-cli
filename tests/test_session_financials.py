"""The finance surface of ``HostawaySession``, driven against mocked routes.

Two ways to read a period's money, and the difference matters: Hostaway's own
consolidated report answers as CSV in one request, while the per-booking
collector pages ``/reservations`` and hands back the rows for a caller to total
itself.  These tests pin the request each one makes and what it returns.

Every amount and every reservation here is invented.
"""

from __future__ import annotations

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
    sent_body,
)

CONSOLIDATED = "/finance/report/consolidated"

CSV_REPORT = (
    "reservationId,listingName,arrivalDate,totalPrice\n7001,Villa Saka,2026-10-04,1840.00\n"
)


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


def csv_response() -> httpx.Response:
    return httpx.Response(200, text=CSV_REPORT, headers={"content-type": "text/csv"})


async def test_the_consolidated_report_comes_back_as_the_csv_hostaway_sent(
    respx_mock: respx.MockRouter,
) -> None:
    """A report endpoint that answers in CSV, reached with a POST.

    It is a read despite the verb, and its body is not JSON — a session that
    parsed every answer as JSON would fail on a report that arrived perfectly.
    """
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "POST", CONSOLIDATED, steps=[csv_response()])

    report = await session().get_consolidated_report(start_date="2026-10-01", end_date="2026-10-31")

    assert report == CSV_REPORT
    assert sent_body(route) == {
        "fromDate": "2026-10-01",
        "toDate": "2026-10-31",
        "format": "csv",
    }


async def test_the_consolidated_report_sends_only_the_filters_it_was_given(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "POST", CONSOLIDATED, steps=[csv_response()])

    await session().get_consolidated_report(
        start_date="2026-10-01",
        end_date="2026-10-31",
        listing_map_ids=[1001, 1002],
        date_type="departureDate",
        channel_id=2018,
        statuses=["new", "modified"],
    )

    assert sent_body(route) == {
        "fromDate": "2026-10-01",
        "toDate": "2026-10-31",
        "format": "csv",
        "listingMapIds": [1001, 1002],
        "dateType": "departureDate",
        # One channel, and Hostaway still wants the plural field.
        "channelIds": [2018],
        "statuses": ["new", "modified"],
    }


def reservations(first_id: int, how_many: int) -> list[dict[str, object]]:
    """``how_many`` invented reservations, distinguishable by id."""
    return [
        {
            "id": first_id + index,
            "listingMapId": VILLA_ID,
            "arrivalDate": "2026-10-04",
            "departureDate": "2026-10-09",
            "totalPrice": 1840.0,
        }
        for index in range(how_many)
    ]


def offsets(route: respx.Route) -> list[str]:
    return [dict(httpx.URL(str(call.request.url)).params)["offset"] for call in route.calls]


async def test_the_collector_pages_until_hostaway_returns_a_short_page(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(
        respx_mock,
        "GET",
        "/reservations",
        steps=[ok(reservations(7001, 200)), ok(reservations(7201, 3))],
    )

    collected = await session().list_bookings_for_period(
        start_date="2026-10-01", end_date="2026-10-31"
    )

    assert len(collected) == 203
    assert offsets(route) == ["0", "200"]


async def test_the_collector_asks_for_the_stays_that_overlap_the_period(
    respx_mock: respx.MockRouter,
) -> None:
    """A stay that starts before the period and ends inside it is part of it."""
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok([])])

    await session().list_bookings_for_period(
        start_date="2026-10-01", end_date="2026-10-31", listing_id=VILLA_ID
    )

    assert dict(httpx.URL(str(route.calls[0].request.url)).params) == {
        "listingId": str(VILLA_ID),
        "departureStartDate": "2026-10-01",
        "arrivalEndDate": "2026-10-31",
        "limit": "200",
        "offset": "0",
    }


async def test_a_period_wider_than_the_page_ceiling_is_refused_not_truncated(
    respx_mock: respx.MockRouter,
) -> None:
    """Half the reservations is a wrong total that looks like a right one."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok(reservations(7001, 200))])

    with pytest.raises(RuntimeError, match="get_consolidated_report"):
        await session().list_bookings_for_period(
            start_date="2026-01-01", end_date="2026-12-31", max_pages=1
        )


async def test_the_collector_refuses_a_ceiling_that_allows_no_page_at_all(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)

    with pytest.raises(ValueError, match="max_pages must be positive"):
        await session().list_bookings_for_period(
            start_date="2026-10-01", end_date="2026-10-31", max_pages=0
        )

    assert not respx_mock.calls
