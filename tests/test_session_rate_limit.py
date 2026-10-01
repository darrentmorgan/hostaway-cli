"""Outbound rate limiting, pinned through the session's public surface.

Hostaway publishes two limits — 15 requests per 10 seconds per IP and 20 per 10
seconds per account — and a connection pool that is easy to exhaust. Both are
visible from outside the session: a burst past the IP limit is held back until
there is capacity, and a caller that fires everything at once still gets no more
requests in flight than the transport allows.

These are timing tests, so they assert lower bounds on waiting and an exact cap
on concurrency. A slow machine can only make the waiting longer.
"""

from __future__ import annotations

import asyncio

import httpx
import respx

from hostaway_cli import HostawaySession
from hostaway_mocks import (
    ACCOUNT_ID,
    BASE_URL,
    SECRET_KEY,
    VILLA_ID,
    mock_access_tokens,
    mock_handler,
    ok,
    villa,
)

LISTINGS = "/listings"

# The published limits, as the transport has to honour them.
IP_REQUESTS_PER_PERIOD = 15
PERIOD_SECONDS = 10.0
MAX_IN_FLIGHT = 10

# Once the burst is spent, one more request costs a full share of the period.
SPACING_SECONDS = PERIOD_SECONDS / IP_REQUESTS_PER_PERIOD


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


async def test_a_burst_past_the_ip_limit_waits_for_capacity(
    respx_mock: respx.MockRouter,
) -> None:
    """15 requests go out at once; the 16th waits for the bucket to refill."""
    loop = asyncio.get_running_loop()
    sent_at: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_at.append(loop.time())
        return ok([], count=0)

    mock_access_tokens(respx_mock)
    mock_handler(respx_mock, "GET", LISTINGS, handler)
    bursting = session()

    for _ in range(IP_REQUESTS_PER_PERIOD + 1):
        await bursting.list_listings()

    assert len(sent_at) == IP_REQUESTS_PER_PERIOD + 1
    burst = sent_at[IP_REQUESTS_PER_PERIOD - 1] - sent_at[0]
    assert burst < SPACING_SECONDS / 2, "the published burst is not throttled"
    held_back = sent_at[-1] - sent_at[-2]
    assert held_back >= SPACING_SECONDS / 2, "the 16th request waits for capacity"


async def test_a_caller_firing_everything_at_once_is_held_to_the_pool(
    respx_mock: respx.MockRouter,
) -> None:
    """Concurrency is capped whatever the caller asks for, so the pool survives."""
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        for _ in range(3):
            await asyncio.sleep(0)  # let every other queued request start
        in_flight -= 1
        return ok(villa())

    mock_access_tokens(respx_mock)
    mock_handler(respx_mock, "GET", f"{LISTINGS}/{VILLA_ID}", handler)
    concurrent = session()
    await concurrent.get_listing(VILLA_ID)  # the token is fetched once, up front

    at_once = MAX_IN_FLIGHT + 4  # still inside the burst, so nothing is rate-limited
    await asyncio.gather(*(concurrent.get_listing(VILLA_ID) for _ in range(at_once)))

    assert peak == MAX_IN_FLIGHT
