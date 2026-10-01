"""Transparent retry helper for the Hostaway transport.

Wraps a single async HTTP attempt with:

- 3 attempts in total
- exponential backoff of exactly 2 then 4 seconds
- retryable = httpx timeout/network/connect errors plus HTTP 429 and 500/502/503/504

Terminal outcomes — a mapped status, an exhausted 429 or 5xx, an exhausted
timeout — are propagated as the httpx exception they arrived as, and
``_transport.send`` turns every one of them into a typed error before it can
reach a caller of the session.

The 401-then-refresh dance lives in ``_transport.py`` because it has to mutate
the token manager; keeping it here would bleed concerns.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

MAX_ATTEMPTS = 3
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException | httpx.NetworkError | httpx.ConnectError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in TRANSIENT_STATUS
    return False


async def with_retry(send: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response:
    """Execute ``send`` up to three times with 2s then 4s backoff.

    On exhaustion the underlying exception is re-raised rather than wrapped in a
    tenacity ``RetryError`` — a timeout, a network error, or an
    ``HTTPStatusError`` for 429/5xx — because the transport maps it onto the
    typed error that names what actually failed.
    """
    retrying = AsyncRetrying(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async for attempt in retrying:
        with attempt:
            response = await send()
            if response.status_code in TRANSIENT_STATUS:
                response.raise_for_status()  # surface as HTTPStatusError -> retry
            return response
    raise AssertionError("retry loop ended without a response")  # pragma: no cover
