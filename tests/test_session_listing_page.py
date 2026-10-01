"""``list_listings_page`` proves a complete, non-ambiguous scan or refuses to.

A caller walking every listing has to know that the page it holds is the page it
asked for. Anything Hostaway can return that would make the walk silently skip or
repeat a listing is a pagination error, never a coerced page.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from hostaway_cli import HostawayPaginationError, HostawaySession
from hostaway_mocks import ACCOUNT_ID, BASE_URL, SECRET_KEY, mock_access_tokens, mock_endpoint

LISTINGS = "/listings"


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


def page_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "status": "success",
        "count": 2,
        "limit": 2,
        "offset": 0,
        "result": [{"id": 1001, "name": "Villa Saka"}, {"id": 1002, "name": "Villa Nira"}],
    }
    body.update(overrides)
    return body


async def fetch(respx_mock: respx.MockRouter, body: object, **kwargs: int) -> object:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(200, json=body)])
    return await session().list_listings_page(
        limit=kwargs.get("limit", 2), offset=kwargs.get("offset", 0)
    )


async def test_a_well_formed_page_carries_its_items_count_and_next_offset(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(
        respx_mock, "GET", LISTINGS, steps=[httpx.Response(200, json=page_body())]
    )

    page = await session().list_listings_page(limit=2, offset=0)

    assert page.listing_ids == (1001, 1002)
    assert page.count == 2
    assert page.next_offset == 2
    assert page.raw_body == page_body()
    assert dict(httpx.URL(str(route.calls[0].request.url)).params) == {"limit": "2", "offset": "0"}


async def test_a_short_page_before_the_end_of_the_scan_is_refused(
    respx_mock: respx.MockRouter,
) -> None:
    """A page shorter than the limit while listings remain would skip the rest."""
    body = page_body(count=9, result=[{"id": 1001}])

    with pytest.raises(HostawayPaginationError) as caught:
        await fetch(respx_mock, body)

    assert caught.value.code == "pagination_page_incomplete"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (page_body(count="two"), "pagination_count_invalid"),
        (page_body(result={"id": 1001}), "pagination_result_invalid"),
        (page_body(limit=50), "pagination_limit_mismatch"),
        (page_body(offset=40), "pagination_offset_mismatch"),
        (page_body(count=1), "pagination_next_offset_exceeds_count"),
        (page_body(result=[{"id": 1001}, {"id": 1001}], count=2), "pagination_duplicate_id"),
        (page_body(result=[{"id": 1001}, {"id": "1002"}]), "pagination_item_invalid:1"),
        (page_body(result=[{"id": 1001}, "not-an-object"]), "pagination_item_invalid:1"),
        (page_body(result=[{"id": 1001}, {"id": True}]), "pagination_item_invalid:1"),
        (page_body(result=[{"id": 1001}, {"name": "unnamed"}]), "pagination_item_invalid:1"),
        ([1001, 1002], "pagination_body_not_object"),
    ],
    ids=[
        "count-not-an-integer",
        "result-not-a-list",
        "echoed-limit-differs",
        "echoed-offset-differs",
        "more-listings-on-the-page-than-in-the-account",
        "the-same-listing-twice",
        "id-as-a-string",
        "item-not-an-object",
        "id-as-a-boolean",
        "item-without-an-id",
        "body-not-an-object",
    ],
)
async def test_a_page_that_cannot_prove_the_scan_is_a_pagination_error(
    respx_mock: respx.MockRouter, body: object, code: str
) -> None:
    with pytest.raises(HostawayPaginationError) as caught:
        await fetch(respx_mock, body)

    assert caught.value.code == code


async def test_a_page_carrying_more_listings_than_were_asked_for_is_refused(
    respx_mock: respx.MockRouter,
) -> None:
    with pytest.raises(HostawayPaginationError) as caught:
        await fetch(respx_mock, page_body(), limit=1)

    assert caught.value.code == "pagination_page_too_large"


async def test_a_non_200_success_is_refused(respx_mock: respx.MockRouter) -> None:
    """Only a 200 carries a page; anything else 2xx says something else happened."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(202)])

    with pytest.raises(HostawayPaginationError) as caught:
        await session().list_listings_page(limit=2, offset=0)

    assert caught.value.code == "pagination_status_invalid"


async def test_an_offset_past_the_end_of_the_account_is_refused(
    respx_mock: respx.MockRouter,
) -> None:
    with pytest.raises(HostawayPaginationError) as caught:
        await fetch(respx_mock, page_body(count=1, offset=40, result=[]), offset=40)

    assert caught.value.code == "pagination_offset_out_of_range"


async def test_a_body_that_is_not_json_is_a_pagination_error(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(200, text="<html>")])

    with pytest.raises(HostawayPaginationError) as caught:
        await session().list_listings_page(limit=2, offset=0)

    assert caught.value.code == "pagination_body_invalid"


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (101, 0), (2, -1)])
async def test_a_page_request_outside_the_documented_window_never_reaches_hostaway(
    respx_mock: respx.MockRouter, limit: int, offset: int
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(
        respx_mock, "GET", LISTINGS, steps=[httpx.Response(200, json=page_body())]
    )

    with pytest.raises(HostawayPaginationError):
        await session().list_listings_page(limit=limit, offset=offset)

    assert not route.called
