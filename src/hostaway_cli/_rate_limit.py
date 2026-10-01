"""Outbound rate limiting for the Hostaway transport.

Hostaway publishes two limits — 15 requests per 10 seconds per IP and 20 per 10
seconds per account — and a connection pool it is easy to exhaust.  The
transport holds one of these and every request passes through ``acquire``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiolimiter import AsyncLimiter

IP_RATE_LIMIT = 15
ACCOUNT_RATE_LIMIT = 20
TIME_PERIOD_SECONDS = 10.0
MAX_CONCURRENT = 10


class RateLimiter:
    """Token buckets for the two published limits, plus a concurrency cap."""

    def __init__(
        self,
        *,
        ip_rate_limit: int = IP_RATE_LIMIT,
        account_rate_limit: int = ACCOUNT_RATE_LIMIT,
        time_period: float = TIME_PERIOD_SECONDS,
        max_concurrent: int = MAX_CONCURRENT,
    ) -> None:
        self._ip_limiter = AsyncLimiter(max_rate=ip_rate_limit, time_period=time_period)
        self._account_limiter = AsyncLimiter(max_rate=account_rate_limit, time_period=time_period)
        self._semaphore = asyncio.Semaphore(max_concurrent)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        """Wait until one more outbound request is within every limit."""
        async with self._semaphore, self._ip_limiter, self._account_limiter:
            yield
