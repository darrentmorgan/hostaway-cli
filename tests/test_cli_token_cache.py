"""The optional token cache, exercised through the commands that use it.

The cache is a file on an operator's own machine holding a live bearer token, so
its safety properties are the point: owner-only permissions, an atomic replace,
and a hard stop when it holds a different account's token (docs/adr/0003).  Each
test drives a real command, because "the cache was used" is only true if the
command did not go and fetch a token.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import (
    ACCOUNT_ID,
    CACHED_TOKEN,
    FAR_FUTURE,
    FIRST_TOKEN,
    LONG_PAST,
    bearer_tokens,
    cli_env,
    mock_access_tokens,
    mock_endpoint,
    ok,
    villas,
    write_token_cache,
)

runner = CliRunner()


def test_a_cached_token_is_spent_without_asking_for_a_new_one(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """No ``/accessTokens`` route is mocked: reaching for one would fail the run."""
    cache = write_token_cache(tmp_path / "token.json")
    listings = mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])

    result = runner.invoke(app, ["listings"], env=cli_env(HSCTL_TOKEN_CACHE=str(cache)))

    assert result.exit_code == 0, result.output
    assert bearer_tokens(listings) == [CACHED_TOKEN]


def test_a_cache_holding_another_account_is_refused_before_anything_is_sent(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """Nothing is mocked: the command must stop on the file, not on the network."""
    cache = write_token_cache(tmp_path / "token.json", account_id="515151")

    result = runner.invoke(app, ["listings"], env=cli_env(HSCTL_TOKEN_CACHE=str(cache)))

    assert result.exit_code == 2, result.output
    assert "515151" in result.output
    assert ACCOUNT_ID in result.output
    assert not respx_mock.calls


def test_a_cache_other_users_can_read_is_refused(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """A live bearer token readable by the group or the world is not usable."""
    cache = write_token_cache(tmp_path / "token.json", mode=0o644)

    result = runner.invoke(app, ["listings"], env=cli_env(HSCTL_TOKEN_CACHE=str(cache)))

    assert result.exit_code == 2, result.output
    assert "0600" in result.output
    assert not respx_mock.calls


def test_an_expired_cache_is_replaced_by_a_fresh_token(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    cache = write_token_cache(tmp_path / "token.json", expires_at=LONG_PAST)
    mock_access_tokens(respx_mock)
    listings = mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])

    result = runner.invoke(app, ["listings"], env=cli_env(HSCTL_TOKEN_CACHE=str(cache)))

    assert result.exit_code == 0, result.output
    assert bearer_tokens(listings) == [FIRST_TOKEN]
    assert json.loads(cache.read_text(encoding="utf-8"))["access_token"] == FIRST_TOKEN


def test_a_fetched_token_is_written_owner_only_into_a_directory_of_its_own(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    cache = tmp_path / "private" / "token.json"
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok([], count=0)])

    result = runner.invoke(app, ["listings"], env=cli_env(HSCTL_TOKEN_CACHE=str(cache)))

    assert result.exit_code == 0, result.output
    assert json.loads(cache.read_text(encoding="utf-8")) == {
        "account_id": ACCOUNT_ID,
        "access_token": FIRST_TOKEN,
        "expires_at": json.loads(cache.read_text(encoding="utf-8"))["expires_at"],
    }
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache.parent.stat().st_mode) == 0o700
    assert list(cache.parent.iterdir()) == [cache]


# Everything a cache file can hold that is not this account's live token. None of
# them may reach the operator as a raw json, key or validation error from
# underneath the CLI: the file is the operator's to fix, so the message names it.
UNUSABLE_CACHES = {
    "not JSON at all": "{",
    "not an object": '"a bare string"',
    "no token": json.dumps({"account_id": ACCOUNT_ID, "expires_at": FAR_FUTURE}),
    "no expiry": json.dumps({"account_id": ACCOUNT_ID, "access_token": CACHED_TOKEN}),
    "an expiry that is not a timestamp": json.dumps(
        {"account_id": ACCOUNT_ID, "access_token": CACHED_TOKEN, "expires_at": "next tuesday"}
    ),
    "a token too short to be one": json.dumps(
        {"account_id": ACCOUNT_ID, "access_token": "x", "expires_at": FAR_FUTURE}
    ),
}


@pytest.mark.parametrize("body", UNUSABLE_CACHES.values(), ids=UNUSABLE_CACHES)
def test_a_cache_that_is_not_a_token_is_refused_by_name(
    respx_mock: respx.MockRouter, tmp_path: Path, body: str
) -> None:
    cache = tmp_path / "token.json"
    cache.write_text(body, encoding="utf-8")
    cache.chmod(0o600)

    result = runner.invoke(app, ["listings"], env=cli_env(HSCTL_TOKEN_CACHE=str(cache)))

    assert result.exit_code == 2, result.output
    assert str(cache) in result.output
    assert not respx_mock.calls
