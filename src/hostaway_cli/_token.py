"""OAuth 2.0 client-credentials lifecycle for the Hostaway transport.

``AccessToken`` is the token itself, with the expiry arithmetic a cache needs.
``TokenManager`` owns one token per session: it fetches lazily, refreshes before
expiry, and serialises concurrent callers behind a lock so a burst of requests
cannot start a stampede of token fetches.

A status the token endpoint returns is left as the httpx error it arrived as,
because ``_transport`` names and classifies it there along with every other
status.  A 200 that carries no token has no status to classify, so it is mapped
here, onto the same typed error surface: no json or pydantic exception escapes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from hostaway_cli.errors import HostawayProtocolError

ACCESS_TOKEN_PATH = "/accessTokens"
GRANT_TYPE = "client_credentials"
SCOPE = "general"
REFRESH_THRESHOLD_DAYS = 7


class AccessToken(BaseModel):
    """A bearer token for the Hostaway API and the moment it was issued."""

    access_token: str = Field(..., min_length=20)
    token_type: str = Field(default="Bearer", pattern=r"^Bearer$")
    expires_in: int = Field(..., ge=1)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scope: str = Field(default=SCOPE)

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + timedelta(seconds=self.expires_in)

    @property
    def days_until_expiration(self) -> int:
        return max(0, (self.expires_at - datetime.now(UTC)).days)

    def should_refresh(self, threshold_days: int = REFRESH_THRESHOLD_DAYS) -> bool:
        """True when the token expires within ``threshold_days``."""
        return self.days_until_expiration <= threshold_days


class TokenStore(Protocol):
    """Somewhere a token outlives the process that fetched it.

    The file-backed implementation is ``token_cache.TokenCache``; the protocol is
    here so nothing under the session has to know where a token is kept.  Both
    calls are synchronous: a store is a small local read and write, and hiding
    that behind ``await`` would suggest otherwise.
    """

    def load(self) -> AccessToken | None:
        """The stored token, or ``None`` when there is no usable one."""

    def save(self, token: AccessToken) -> None:
        """Store ``token`` in place of whatever was there."""


class TokenManager:
    """One session's token: fetched lazily, refreshed early, shared safely."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        account_id: str,
        secret_key: str,
        refresh_threshold_days: int = REFRESH_THRESHOLD_DAYS,
        store: TokenStore | None = None,
    ) -> None:
        self._client = client
        self._account_id = account_id
        self._secret_key = secret_key
        self._refresh_threshold_days = refresh_threshold_days
        self._store = store
        # Read eagerly: a store that refuses — the wrong account, a file anyone
        # can read — must stop the command before it sends anything, not on the
        # first request.
        self._token: AccessToken | None = None if store is None else store.load()
        self._lock = asyncio.Lock()

    async def get_token(self) -> AccessToken:
        async with self._lock:
            if self._token is None or self._token.should_refresh(self._refresh_threshold_days):
                await self._refresh()
            if self._token is None:  # pragma: no cover - _refresh either sets or raises
                raise RuntimeError("Failed to obtain a Hostaway access token")
            return self._token

    async def invalidate(self) -> None:
        """Drop the held token so the next request fetches a fresh one."""
        async with self._lock:
            self._token = None

    async def _refresh(self) -> None:
        if not self._account_id or not self._secret_key:
            raise ValueError("Hostaway credentials missing: account ID and secret key are required")
        response = await self._client.post(
            ACCESS_TOKEN_PATH,
            data={
                "grant_type": GRANT_TYPE,
                "client_id": self._account_id,
                "client_secret": self._secret_key,
                "scope": SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        self._token = _token_in(response)
        if self._store is not None:
            self._store.save(self._token)


def _token_in(response: httpx.Response) -> AccessToken:
    """The token a 200 from the token endpoint carries, or a protocol error.

    A 200 with no token in it is as terminal as a rejected credential — the
    session has no bearer to send — and a caller must not have to catch a json
    or pydantic exception to find that out.  A base URL pointed at a web page or
    a captive proxy answers with HTML; a server answering in its own shape
    answers with JSON that is not a token.
    """
    try:
        body = response.json()
    except (TypeError, ValueError) as exc:
        raise HostawayProtocolError(
            "token_response_body_invalid", endpoint=ACCESS_TOKEN_PATH, detail=response.text
        ) from exc
    try:
        return AccessToken.model_validate(body)
    except ValidationError as exc:
        raise HostawayProtocolError(
            "token_response_not_a_token", endpoint=ACCESS_TOKEN_PATH, detail=_shape_of(body)
        ) from exc


def _shape_of(body: object) -> str:
    """What came back, named without echoing anything that might be a secret.

    A body can fail validation and still carry a live token, so the detail
    reports the keys that arrived rather than the values under them.
    """
    if isinstance(body, dict):
        return f"object with keys {sorted(str(key) for key in body)}"
    return type(body).__name__
