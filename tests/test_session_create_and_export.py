"""Creating a listing, and pushing a saved listing out to a channel.

A create is the one write that must never be retried: a repeat could leave two
listings behind and no way to tell which is which. So it is sent exactly once,
and every ambiguous outcome is reported as ambiguous rather than guessed at.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from hostaway_cli import (
    HostawayAuthError,
    HostawayCreateError,
    HostawayNotFoundError,
    HostawaySession,
)
from hostaway_cli.export import export_listing_to_airbnb
from hostaway_mocks import (
    ACCESS_TOKEN_PATH,
    ACCOUNT_ID,
    BASE_URL,
    SECRET_KEY,
    VILLA_ID,
    mock_access_tokens,
    mock_endpoint,
    ok,
    sent_body,
    villa,
)

LISTINGS = "/listings"
EXPORT = f"/listings/{VILLA_ID}/export/airbnb"
DRAFT = {"name": "Villa Nira", "city": "Ubud", "personCapacity": 6}


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


def created(listing_id: int = VILLA_ID) -> httpx.Response:
    return httpx.Response(201, json={"status": "success", "result": {"id": listing_id}})


# --- create -----------------------------------------------------------------


async def test_create_listing_posts_the_draft_once_and_returns_the_body(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "POST", LISTINGS, steps=[created()])

    body = await session().create_listing(DRAFT)

    assert body == {"status": "success", "result": {"id": VILLA_ID}}
    assert sent_body(route) == DRAFT


async def test_a_create_that_fails_is_never_retried(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "POST", LISTINGS, steps=[httpx.Response(500)])

    with pytest.raises(HostawayCreateError) as caught:
        await session().create_listing(DRAFT)

    assert caught.value.code == "create_ambiguous"
    assert len(route.calls) == 1


async def test_a_create_rejected_as_unauthorised_does_not_force_a_token_refresh(
    respx_mock: respx.MockRouter,
) -> None:
    token_route = mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "POST", LISTINGS, steps=[httpx.Response(401)])

    with pytest.raises(HostawayCreateError) as caught:
        await session().create_listing(DRAFT)

    assert caught.value.code == "create_auth_rejected"
    assert len(route.calls) == 1
    assert len(token_route.calls) == 1


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "create_validation_rejected"),
        (422, "create_validation_rejected"),
        (403, "create_auth_rejected"),
        (404, "create_endpoint_not_found"),
        (409, "create_ambiguous"),
        (429, "create_ambiguous"),
        (503, "create_ambiguous"),
        (418, "create_rejected"),
    ],
)
async def test_a_rejected_create_carries_the_code_for_its_status(
    respx_mock: respx.MockRouter, status: int, code: str
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", LISTINGS, steps=[httpx.Response(status, text="no")])

    with pytest.raises(HostawayCreateError) as caught:
        await session().create_listing(DRAFT)

    assert caught.value.code == code
    assert caught.value.status_code == status


async def test_a_create_that_never_reached_hostaway_is_ambiguous(
    respx_mock: respx.MockRouter,
) -> None:
    """A dropped connection may or may not have created a listing; say so."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", LISTINGS, steps=[httpx.ConnectError("connection reset")])

    with pytest.raises(HostawayCreateError) as caught:
        await session().create_listing(DRAFT)

    assert caught.value.code == "create_ambiguous"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "fail", "result": {"id": 1001}},
        {"status": "success", "result": {}},
        {"status": "success", "result": {"id": 0}},
        {"status": "success", "result": {"id": True}},
        {"status": "success", "result": {"id": "1001"}},
        {"status": "success", "result": [{"id": 1001}]},
    ],
    ids=[
        "status-not-success",
        "no-id",
        "id-not-positive",
        "id-as-a-boolean",
        "id-as-a-string",
        "result-not-an-object",
    ],
)
async def test_a_success_without_a_usable_listing_id_is_refused(
    respx_mock: respx.MockRouter, body: dict[str, object]
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", LISTINGS, steps=[httpx.Response(201, json=body)])

    with pytest.raises(HostawayCreateError) as caught:
        await session().create_listing(DRAFT)

    assert caught.value.code == "create_no_positive_id"


async def test_a_success_that_is_not_a_json_object_is_ambiguous(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", LISTINGS, steps=[httpx.Response(201, text="created")])

    with pytest.raises(HostawayCreateError) as caught:
        await session().create_listing(DRAFT)

    assert caught.value.code == "create_ambiguous"


async def test_credentials_rejected_before_a_create_leave_no_listing_behind(
    respx_mock: respx.MockRouter,
) -> None:
    """The token fetch failed, so the create never went out: auth, not ambiguous."""
    mock_endpoint(respx_mock, "POST", ACCESS_TOKEN_PATH, steps=[httpx.Response(401)])
    route = mock_endpoint(respx_mock, "POST", LISTINGS, steps=[created()])

    with pytest.raises(HostawayAuthError):
        await session().create_listing(DRAFT)

    assert not route.called


async def test_a_draft_that_is_not_a_mapping_never_reaches_hostaway(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "POST", LISTINGS, steps=[created()])

    with pytest.raises(HostawayCreateError) as caught:
        await session().create_listing(["Villa Nira"])  # type: ignore[arg-type]

    assert caught.value.code == "create_payload_invalid"
    assert not route.called


# --- export -----------------------------------------------------------------


async def test_export_posts_an_empty_body_to_the_channel_endpoint(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "POST", EXPORT, steps=[ok({"jobId": 77})])

    assert await session().export_to_airbnb(VILLA_ID) == {
        "status": "success",
        "result": {"jobId": 77},
    }
    assert sent_body(route) == {}


async def test_an_export_accepted_with_no_body_is_a_success(
    respx_mock: respx.MockRouter,
) -> None:
    """Hostaway commonly answers an export with nothing; that is not a failure."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    assert await session().export_to_airbnb(VILLA_ID) == {}


async def test_exporting_a_listing_that_is_not_there_is_a_not_found_error(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(404)])

    with pytest.raises(HostawayNotFoundError) as caught:
        await session().export_to_airbnb(VILLA_ID)

    assert caught.value.endpoint == EXPORT


async def test_the_export_helper_reports_a_triggered_export(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    assert await export_listing_to_airbnb(session(), VILLA_ID) is True


async def test_the_export_helper_reports_a_failure_without_undoing_the_write(
    respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    """The write already landed; a flaky export must not raise over the top of it."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(404)])

    with caplog.at_level(logging.WARNING):
        assert await export_listing_to_airbnb(session(), VILLA_ID) is False

    assert str(VILLA_ID) in caplog.text


async def test_the_session_closes_its_connections(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", f"/listings/{VILLA_ID}", steps=[ok(villa())])
    open_session = session()

    await open_session.get_listing(VILLA_ID)
    await open_session.aclose()

    with pytest.raises(RuntimeError):
        await open_session.get_listing(VILLA_ID)
