"""``HostawayTransport`` — the authenticated HTTP seam beneath ``HostawaySession``.

Package-private.  This module owns the ``httpx.AsyncClient``, the token manager,
the rate limiter, the retry wrapping from ``_retry.py`` and the mapping of every
terminal outcome onto the typed errors in ``errors.py``.  A session holds exactly
one instance and keeps no transport method on its public surface; nothing outside
this package imports it.

The contract it implements: 3 attempts in total with 2s then 4s waits, retryable
= timeout/network/connect errors plus HTTP 429/500/502/503/504, a 401 forces
exactly one token refresh, and a repeated 401 is terminal.  httpx exceptions stop
here: everything that leaves this module is a ``HostawayError``.
"""

from __future__ import annotations

from typing import Any

import httpx

from hostaway_cli._rate_limit import RateLimiter
from hostaway_cli._retry import TRANSIENT_STATUS, with_retry
from hostaway_cli._token import ACCESS_TOKEN_PATH, TokenManager, TokenStore
from hostaway_cli.errors import (
    HostawayAuthError,
    HostawayError,
    HostawayForbiddenError,
    HostawayNotFoundError,
    HostawayProtocolError,
    HostawayRateLimitError,
    HostawayServerError,
    HostawayStatusError,
    HostawayTransportError,
    HostawayValidationError,
)


class HostawayTransport:
    """Authenticated, rate-limited, retrying HTTP transport for one account."""

    def __init__(
        self,
        *,
        base_url: str,
        account_id: str,
        secret_key: str,
        token_cache: TokenStore | None = None,
    ) -> None:
        self._rate_limiter = RateLimiter()
        self._client = httpx.AsyncClient(
            base_url=base_url,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=30.0,
            ),
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )
        self._token_manager = TokenManager(
            self._client, account_id=account_id, secret_key=secret_key, store=token_cache
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, endpoint: str, *, params: dict[str, Any]) -> dict[str, Any]:
        """GET ``endpoint`` with retry, returning the parsed JSON body."""
        return self.parse(await self.send("GET", endpoint, params=params), endpoint)

    async def send_json(
        self, method: str, endpoint: str, *, json: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON body with retry, returning the parsed JSON response."""
        return self.parse(await self.send(method, endpoint, json=json), endpoint)

    async def send(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send one request through the documented retry and refresh contract.

        Returns only a response the caller can read: every terminal outcome —
        a status, an exhausted retry, an unreachable host — leaves as a typed
        error, so no httpx exception escapes this method.
        """

        async def attempt() -> httpx.Response:
            response = await self._authorized_request(method, endpoint, params=params, json=json)
            if response.status_code == 401:
                # One forced refresh. If it still 401s, the second response is
                # raised below and reaches the caller as HostawayAuthError.
                await self._token_manager.invalidate()
                response = await self._authorized_request(
                    method, endpoint, params=params, json=json
                )
            if response.is_error and response.status_code not in TRANSIENT_STATUS:
                response.raise_for_status()
            return response

        try:
            return await with_retry(attempt)
        except httpx.HTTPStatusError as exc:
            raise _terminal_error(exc, endpoint) from exc
        except httpx.RequestError as exc:
            raise HostawayTransportError(endpoint=endpoint, cause=type(exc).__name__) from exc

    async def send_once(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send one request with no retry, no forced refresh and no status mapping.

        The response comes back whatever its status, because a create has to
        judge its own outcome; only a failure of the token fetch that precedes
        it is mapped, since that is not the caller's request failing.
        """
        try:
            return await self._authorized_request(method, endpoint, params=params, json=json)
        except httpx.HTTPStatusError as exc:
            raise _terminal_error(exc, endpoint) from exc

    async def _authorized_request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None,
    ) -> httpx.Response:
        """One bearer-authenticated, rate-limited request. No status mapping."""
        token = await self._token_manager.get_token()
        headers = {"Authorization": f"Bearer {token.access_token}"}
        async with self._rate_limiter.acquire():
            return await self._client.request(
                method, endpoint, headers=headers, params=params, json=json
            )

    @staticmethod
    def status_error(endpoint: str, response: httpx.Response) -> HostawayError:
        """The typed error a response a caller judged terminal becomes.

        A caller that reads a response itself — a create, an image upload — still
        maps it here, so one status means one error whoever looked at it.
        """
        return _status_error(endpoint, response.status_code, response.text)

    @staticmethod
    def parse(response: httpx.Response, endpoint: str) -> dict[str, Any]:
        """The JSON object Hostaway answered with, or a protocol error."""
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise HostawayProtocolError(
                "response_body_invalid", endpoint=endpoint, detail=response.text
            ) from exc
        if not isinstance(body, dict):
            raise HostawayProtocolError(
                "response_body_not_an_object", endpoint=endpoint, detail=body
            )
        parsed: dict[str, Any] = body
        return parsed


def _terminal_error(exc: httpx.HTTPStatusError, endpoint: str) -> HostawayError:
    """The typed error a terminal status becomes."""
    status = exc.response.status_code
    body = exc.response.text
    if exc.request.url.path.endswith(ACCESS_TOKEN_PATH):
        # The request that actually failed was the token fetch, whatever resource
        # the caller was after, so it is named and classified as one.
        return _token_error(status, body)
    return _status_error(endpoint, status, body)


def _token_error(status: int, body: str) -> HostawayError:
    """A failure of the token fetch itself.

    Credentials the token endpoint rejects are an auth failure, not a listing
    this account may not read.
    """
    if status in {401, 403}:
        return HostawayAuthError(endpoint=ACCESS_TOKEN_PATH, status_code=status, body=body)
    return _status_error(ACCESS_TOKEN_PATH, status, body)


def _status_error(endpoint: str, status: int, body: str) -> HostawayError:
    """A terminal status on a resource request, narrowed as far as it goes."""
    if status == 401:
        return HostawayAuthError(endpoint=endpoint, body=body)
    if status == 403:
        return HostawayForbiddenError(endpoint=endpoint, body=body)
    if status == 404:
        return HostawayNotFoundError(endpoint=endpoint, body=body)
    if status == 422:
        return HostawayValidationError(endpoint=endpoint, body=body)
    if status == 429:
        return HostawayRateLimitError(endpoint=endpoint, body=body)
    if status >= 500:
        return HostawayServerError(endpoint=endpoint, status_code=status, body=body)
    return HostawayStatusError(endpoint=endpoint, status_code=status, body=body)
