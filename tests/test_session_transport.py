"""The transport contract, pinned through the session's public surface.

One clause per test: 3 attempts in total, 2s then 4s waits, retryable =
timeout/network/connect plus HTTP 429/500/502/503/504, exactly one forced token
refresh on a first 401, a repeated 401 terminal, and every terminal outcome —
status, exhausted retry or unreachable host — mapped onto a typed error under
``HostawayError``.  A caller of the session never has to catch an httpx
exception, and never has to import httpx to find out what went wrong.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from hostaway_cli import (
    HostawayAuthError,
    HostawayError,
    HostawayForbiddenError,
    HostawayNotFoundError,
    HostawayProtocolError,
    HostawayRateLimitError,
    HostawayServerError,
    HostawaySession,
    HostawayStatusError,
    HostawayTransportError,
    HostawayValidationError,
)
from hostaway_mocks import (
    ACCESS_TOKEN_PATH,
    ACCOUNT_ID,
    BASE_URL,
    FIRST_TOKEN,
    REFRESHED_TOKEN,
    SECRET_KEY,
    Step,
    bearer_tokens,
    mock_access_tokens,
    mock_endpoint,
    ok,
    token_response,
)

LISTINGS = "/listings"

# Every status the contract calls retryable.
TRANSIENT_STATUSES = [429, 500, 502, 503, 504]

# Non-retryable statuses and the typed error each becomes. 401 is excluded: it
# has its own forced-refresh clause.
MAPPED_STATUSES: list[tuple[int, type[Exception]]] = [
    (403, HostawayForbiddenError),
    (404, HostawayNotFoundError),
    (422, HostawayValidationError),
]

# Non-retryable 4xx the contract names no narrower error for.
UNMAPPED_STATUSES = [400, 409, 418]

# The ways the token endpoint can answer 200 with something that is not a token,
# and the code each becomes.  A base URL pointed at a web page or a captive
# proxy answers with HTML; a server answering in its own shape answers with JSON
# that has no token in it, whether or not that JSON is even an object.  None of
# them leaves the session a bearer to send.
TOKEN_BODY_NOT_JSON = httpx.Response(200, text="<html>login</html>")
TOKEN_BODY_WITHOUT_A_TOKEN = httpx.Response(200, json={"hello": "world"})
TOKEN_BODY_NOT_AN_OBJECT = httpx.Response(200, json=["hello"])

JUNK_TOKEN_BODIES: dict[str, tuple[httpx.Response, str]] = {
    "not json": (TOKEN_BODY_NOT_JSON, "token_response_body_invalid"),
    "an object with no token": (TOKEN_BODY_WITHOUT_A_TOKEN, "token_response_not_a_token"),
    "not even an object": (TOKEN_BODY_NOT_AN_OBJECT, "token_response_not_a_token"),
}

HEALTHY_TOKEN = token_response(FIRST_TOKEN)
HEALTHY_LISTINGS = ok([], count=0)

# One of each terminal outcome a caller can hit, written as the pair of answers
# the token endpoint and the listings endpoint give: every status the transport
# maps, every status it does not, the two ways a request never lands, and the
# two ways the token endpoint answers 200 with no token in it.
TERMINAL_FAILURES: dict[str, tuple[Step, Step]] = {
    "400": (HEALTHY_TOKEN, httpx.Response(400)),
    "403": (HEALTHY_TOKEN, httpx.Response(403)),
    "404": (HEALTHY_TOKEN, httpx.Response(404)),
    "418": (HEALTHY_TOKEN, httpx.Response(418)),
    "422": (HEALTHY_TOKEN, httpx.Response(422)),
    "429 exhausted": (HEALTHY_TOKEN, httpx.Response(429)),
    "500 exhausted": (HEALTHY_TOKEN, httpx.Response(500)),
    "503 exhausted": (HEALTHY_TOKEN, httpx.Response(503)),
    "read timeout": (HEALTHY_TOKEN, httpx.ReadTimeout("read timed out")),
    "connect error": (HEALTHY_TOKEN, httpx.ConnectError("connection refused")),
    "token body not json": (TOKEN_BODY_NOT_JSON, HEALTHY_LISTINGS),
    "token body carries no token": (TOKEN_BODY_WITHOUT_A_TOKEN, HEALTHY_LISTINGS),
    "token body not an object": (TOKEN_BODY_NOT_AN_OBJECT, HEALTHY_LISTINGS),
}


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


@pytest.fixture
def recorded_waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the backoff waits instead of really sleeping them."""
    waits: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float, *args: object, **kwargs: object) -> None:
        waits.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return waits


async def test_a_persistent_server_error_makes_exactly_three_attempts(
    respx_mock: respx.MockRouter, recorded_waits: list[float]
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(500)])

    with pytest.raises(HostawayServerError) as caught:
        await session().list_listings()

    assert len(route.calls) == 3
    assert caught.value.status_code == 500


async def test_the_backoff_waits_are_two_then_four_seconds(
    respx_mock: respx.MockRouter, recorded_waits: list[float]
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(503)])

    with pytest.raises(HostawayServerError):
        await session().list_listings()

    assert recorded_waits == [2.0, 4.0]


@pytest.mark.parametrize("status", TRANSIENT_STATUSES)
async def test_a_transient_status_is_retried_and_then_succeeds(
    respx_mock: respx.MockRouter, recorded_waits: list[float], status: int
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(
        respx_mock, "GET", LISTINGS, steps=[httpx.Response(status), ok([], count=0)]
    )

    listings, count = await session().list_listings()

    assert (listings, count) == ([], 0)
    assert len(route.calls) == 2
    assert recorded_waits == [2.0]


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("read timed out"),
        httpx.ReadError("connection reset"),
        httpx.ConnectError("connection refused"),
    ],
    ids=["timeout", "network", "connect"],
)
async def test_a_transport_error_is_retried_and_then_succeeds(
    respx_mock: respx.MockRouter, recorded_waits: list[float], error: Exception
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[error, ok([], count=0)])

    listings, count = await session().list_listings()

    assert (listings, count) == ([], 0)
    assert len(route.calls) == 2


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("x"), httpx.ConnectError("x")], ids=["timeout", "connect"]
)
async def test_a_persistent_transport_error_stops_after_three_attempts(
    respx_mock: respx.MockRouter, recorded_waits: list[float], error: Exception
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[error])

    with pytest.raises(HostawayTransportError) as caught:
        await session().list_listings()

    assert len(route.calls) == 3
    assert recorded_waits == [2.0, 4.0]
    assert caught.value.cause == type(error).__name__


@pytest.mark.parametrize(("status", "error"), MAPPED_STATUSES)
async def test_a_mapped_status_is_not_retried(
    respx_mock: respx.MockRouter,
    recorded_waits: list[float],
    status: int,
    error: type[Exception],
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(status)])

    with pytest.raises(error):
        await session().list_listings()

    assert len(route.calls) == 1
    assert recorded_waits == []


@pytest.mark.parametrize("status", UNMAPPED_STATUSES)
async def test_an_unmapped_status_is_typed_but_not_retried(
    respx_mock: respx.MockRouter, recorded_waits: list[float], status: int
) -> None:
    """A status with no narrower error still arrives as one, carrying the status."""
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(status, text="nope")])

    with pytest.raises(HostawayStatusError) as caught:
        await session().list_listings()

    assert len(route.calls) == 1
    assert recorded_waits == []
    assert (caught.value.status_code, caught.value.endpoint) == (status, LISTINGS)
    assert caught.value.body == "nope"


async def test_a_first_401_forces_exactly_one_token_refresh(
    respx_mock: respx.MockRouter, recorded_waits: list[float]
) -> None:
    token_route = mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(401), ok([], count=0)])

    listings, count = await session().list_listings()

    assert (listings, count) == ([], 0)
    assert len(token_route.calls) == 2, "the 401 must force exactly one extra token fetch"
    assert bearer_tokens(route) == [FIRST_TOKEN, REFRESHED_TOKEN]
    assert recorded_waits == [], "a forced refresh is not a backoff retry"


async def test_a_repeated_401_is_a_terminal_auth_error(
    respx_mock: respx.MockRouter, recorded_waits: list[float]
) -> None:
    token_route = mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(401)])

    with pytest.raises(HostawayAuthError):
        await session().list_listings()

    assert len(route.calls) == 2, "the original request plus one post-refresh retry, no backoff"
    assert len(token_route.calls) == 2
    assert bearer_tokens(route) == [FIRST_TOKEN, REFRESHED_TOKEN]
    assert recorded_waits == []


async def test_an_exhausted_429_becomes_a_rate_limit_error(
    respx_mock: respx.MockRouter, recorded_waits: list[float]
) -> None:
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(429)])

    with pytest.raises(HostawayRateLimitError):
        await session().list_listings()

    assert len(route.calls) == 3


async def test_a_404_becomes_a_not_found_error_naming_the_endpoint(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[httpx.Response(404)])

    with pytest.raises(HostawayNotFoundError) as caught:
        await session().get_listing(1001)

    assert caught.value.endpoint == "/listings/1001"


async def test_a_403_becomes_a_forbidden_error(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[httpx.Response(403)])

    with pytest.raises(HostawayForbiddenError) as caught:
        await session().get_listing(1001)

    assert caught.value.endpoint == "/listings/1001"


@pytest.mark.parametrize("status", [401, 403])
async def test_credentials_the_token_endpoint_rejects_are_an_auth_error(
    respx_mock: respx.MockRouter, status: int
) -> None:
    """Rejected credentials are an auth failure, not an inaccessible listing."""
    mock_endpoint(respx_mock, "POST", ACCESS_TOKEN_PATH, steps=[httpx.Response(status)])
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok({})])

    with pytest.raises(HostawayAuthError) as caught:
        await session().get_listing(1001)

    assert not isinstance(caught.value, HostawayForbiddenError)
    assert (caught.value.endpoint, caught.value.status_code) == (ACCESS_TOKEN_PATH, status)


async def test_a_422_becomes_a_validation_error_carrying_the_body(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock, "GET", "/listings/1001", steps=[httpx.Response(422, text="bad request")]
    )

    with pytest.raises(HostawayValidationError) as caught:
        await session().get_listing(1001)

    assert caught.value.endpoint == "/listings/1001"
    assert caught.value.body == "bad request"


@pytest.mark.parametrize(
    ("token_answer", "listings_answer"), TERMINAL_FAILURES.values(), ids=TERMINAL_FAILURES
)
async def test_no_terminal_failure_reaches_a_caller_as_an_httpx_exception(
    respx_mock: respx.MockRouter,
    recorded_waits: list[float],
    token_answer: Step,
    listings_answer: Step,
) -> None:
    """The whole point of the typed errors: ``except HostawayError`` is enough.

    Whichever of the two endpoints fails, and however it fails, what reaches the
    caller is a ``HostawayError`` — never an httpx, json or pydantic exception
    from underneath the session.
    """
    mock_endpoint(respx_mock, "POST", ACCESS_TOKEN_PATH, steps=[token_answer])
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[listings_answer])

    with pytest.raises(HostawayError):
        await session().list_listings()


@pytest.mark.parametrize(("answer", "code"), JUNK_TOKEN_BODIES.values(), ids=JUNK_TOKEN_BODIES)
async def test_a_token_endpoint_answering_with_junk_is_a_protocol_error(
    respx_mock: respx.MockRouter, answer: httpx.Response, code: str
) -> None:
    """A 200 from the token endpoint that carries no token is terminal, and typed.

    The listings endpoint is healthy here, so the only thing that can fail is
    the token fetch, and the error has to say so: the code names the failure and
    the endpoint names the token path, not the resource the caller asked for.
    """
    mock_endpoint(respx_mock, "POST", ACCESS_TOKEN_PATH, steps=[answer])
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[HEALTHY_LISTINGS])

    with pytest.raises(HostawayProtocolError) as caught:
        await session().list_listings()

    assert (caught.value.code, caught.value.endpoint) == (code, ACCESS_TOKEN_PATH)


async def test_a_junk_token_body_is_reported_without_echoing_its_values(
    respx_mock: respx.MockRouter,
) -> None:
    """The detail names the shape that came back, never the values inside it.

    A token body can fail validation while still carrying a usable secret — a
    token one character short of the minimum, say — so the error says which keys
    arrived and stops there.
    """
    mock_endpoint(
        respx_mock,
        "POST",
        ACCESS_TOKEN_PATH,
        steps=[httpx.Response(200, json={"access_token": "too-short", "expires_in": 1})],
    )
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[HEALTHY_LISTINGS])

    with pytest.raises(HostawayProtocolError) as caught:
        await session().list_listings()

    detail = str(caught.value.detail)
    assert "access_token" in detail
    assert "expires_in" in detail
    assert "too-short" not in detail


async def test_a_failing_token_endpoint_is_typed_by_its_own_status(
    respx_mock: respx.MockRouter, recorded_waits: list[float]
) -> None:
    """A token fetch that keeps 500ing is a server error naming the token path."""
    token_route = mock_endpoint(respx_mock, "POST", ACCESS_TOKEN_PATH, steps=[httpx.Response(500)])
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[HEALTHY_LISTINGS])

    with pytest.raises(HostawayServerError) as caught:
        await session().list_listings()

    assert len(token_route.calls) == 3
    assert (caught.value.endpoint, caught.value.status_code) == (ACCESS_TOKEN_PATH, 500)


async def test_a_body_that_is_not_json_is_a_protocol_error(
    respx_mock: respx.MockRouter,
) -> None:
    """A 200 whose body will not parse as JSON at all breaks the contract."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(200, text="<html>")])

    with pytest.raises(HostawayProtocolError) as caught:
        await session().list_listings()

    assert (caught.value.code, caught.value.endpoint) == ("response_body_invalid", LISTINGS)


async def test_a_body_that_is_json_but_not_an_object_is_a_protocol_error(
    respx_mock: respx.MockRouter,
) -> None:
    """A 200 carrying a JSON array parses cleanly and is still off-contract.

    Hostaway wraps every result in an object; a bare array has no envelope to
    read a status or a count out of, so it cannot be treated as a page.
    """
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[httpx.Response(200, json=[{"id": 1001}])])

    with pytest.raises(HostawayProtocolError) as caught:
        await session().list_listings()

    assert (caught.value.code, caught.value.endpoint) == ("response_body_not_an_object", LISTINGS)


def test_the_endpoint_mock_refuses_an_empty_step_sequence(respx_mock: respx.MockRouter) -> None:
    """A step-less mock would silently answer nothing — fail loudly instead."""
    with pytest.raises(ValueError, match="at least one response"):
        mock_endpoint(respx_mock, "GET", LISTINGS, steps=[])


async def test_the_token_is_fetched_once_and_reused(respx_mock: respx.MockRouter) -> None:
    """A command that makes several calls must not re-authenticate for each one."""
    token_route = mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTINGS, steps=[ok([], count=0)])
    reused = session()

    await reused.list_listings()
    await reused.list_listings()

    assert len(token_route.calls) == 1


async def test_a_token_near_expiry_is_replaced_before_it_is_used(
    respx_mock: respx.MockRouter,
) -> None:
    token_route = mock_endpoint(
        respx_mock,
        "POST",
        ACCESS_TOKEN_PATH,
        steps=[
            httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 60,
                    "access_token": FIRST_TOKEN,
                },
            ),
            httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 63072000,
                    "access_token": REFRESHED_TOKEN,
                },
            ),
        ],
    )
    route = mock_endpoint(respx_mock, "GET", LISTINGS, steps=[ok([], count=0)])
    expiring = session()

    await expiring.list_listings()
    await expiring.list_listings()

    assert len(token_route.calls) == 2
    assert bearer_tokens(route) == [FIRST_TOKEN, REFRESHED_TOKEN]


@pytest.mark.parametrize(("account_id", "secret_key"), [("", SECRET_KEY), (ACCOUNT_ID, "")])
async def test_a_session_without_credentials_says_so_before_anything_else(
    respx_mock: respx.MockRouter, account_id: str, secret_key: str
) -> None:
    route = mock_access_tokens(respx_mock)

    with pytest.raises(ValueError, match="credentials missing"):
        await HostawaySession(
            account_id=account_id, secret_key=secret_key, base_url=BASE_URL
        ).list_listings()

    assert not route.called
