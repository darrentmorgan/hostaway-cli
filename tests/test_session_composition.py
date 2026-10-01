"""``HostawaySession`` carries every resource family *and* the token cache.

The listings reads are written on the class; the other resource families arrive
as mixins; the token cache arrives as a constructor argument.  Each half is
proved on its own elsewhere, and nothing pinned the two together — so a merge
that kept one and dropped the other type-checked and passed.  This is the test
that fails when that happens.
"""

from __future__ import annotations

import respx

from hostaway_cli import AccessToken, HostawaySession, TokenStore
from hostaway_mocks import ACCOUNT_ID, BASE_URL, SECRET_KEY, mock_endpoint, ok

CACHED_TOKEN = "tok-out-of-the-cache-1234567890"

# One public method per resource family, so a family that stops composing in is
# named by the failure rather than hidden behind a generic attribute error.
RESOURCE_FAMILY_READS = (
    "list_listings",
    "get_reviews",
    "search_bookings",
    "get_amenities",
    "get_consolidated_report",
    "upload_listing_images",
)


class _StoredToken:
    """An in-memory ``TokenStore``: a token to spend, and what was saved to it."""

    def __init__(self, token: AccessToken) -> None:
        self.token: AccessToken | None = token
        self.saved: list[AccessToken] = []

    def load(self) -> AccessToken | None:
        return self.token

    def save(self, token: AccessToken) -> None:
        self.saved.append(token)
        self.token = token


def cached_session() -> tuple[HostawaySession, _StoredToken]:
    """A session over a cache already holding a token with years left on it."""
    store = _StoredToken(AccessToken(access_token=CACHED_TOKEN, expires_in=63072000))
    cache: TokenStore = store
    session = HostawaySession(
        account_id=ACCOUNT_ID,
        secret_key=SECRET_KEY,
        base_url=BASE_URL,
        token_cache=cache,
    )
    return session, store


def test_a_session_over_a_token_cache_still_answers_for_every_resource_family() -> None:
    session, _ = cached_session()

    missing = [name for name in RESOURCE_FAMILY_READS if not callable(getattr(session, name, None))]

    assert missing == []


async def test_a_mixin_read_spends_the_cached_token_without_authenticating(
    respx_mock: respx.MockRouter,
) -> None:
    """No ``/accessTokens`` route is mocked at all.

    ``respx`` fails an unmocked request rather than letting it out, so a session
    that had lost its ``token_cache`` argument would fetch a token here and fail
    the test instead of quietly authenticating.
    """
    session, _ = cached_session()
    route = mock_endpoint(respx_mock, "GET", "/reviews", steps=[ok([], count=0)])

    await session.get_reviews()

    assert route.calls[0].request.headers["Authorization"] == f"Bearer {CACHED_TOKEN}"
