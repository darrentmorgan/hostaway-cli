"""The offline check on the environment and the configuration, run before a write.

Doctor answers one question — is this machine set up to operate an account? — and
answers it without a single Hostaway call, so an operator can find a missing
secret, an unsafe token cache or a mistyped configuration path before a command
that matters is typed.  Nothing here opens a socket: every check reads the
environment and, at most, a file the operator already named.

Each check reports PASS, WARN or FAIL and every check runs, because the point is
to see the whole setup at once rather than the first thing that went wrong.  A
WARN is something absent that only some commands need; a FAIL is something wrong.
"""

from __future__ import annotations

import stat
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from hostaway_cli.config import CONFIG_ENV_VAR, ConfigError, load_config
from hostaway_cli.credentials import (
    ACCOUNT_ID_ENV_VAR,
    BASE_URL_ENV_VAR,
    TOKEN_CACHE_ENV_VAR,
    CredentialsError,
    environment,
    load_credentials,
)
from hostaway_cli.session import HOSTAWAY_API_BASE_URL
from hostaway_cli.surface import surface_of
from hostaway_cli.token_cache import TokenCache, TokenCacheError

# Wide enough for the longest check name, so the details line up in a column.
NAME_WIDTH = 13

__all__ = ["Check", "Outcome", "run_checks"]


class Outcome(StrEnum):
    """What one check found, and whether it stops a command."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Check:
    """One thing doctor looked at, and what it found."""

    name: str
    outcome: Outcome
    detail: str

    def line(self) -> str:
        """This check as the one line an operator reads."""
        # A message from underneath can arrive over several lines; doctor's report
        # is one line per check, so it is folded rather than allowed to break the
        # column.
        detail = " ".join(part.strip() for part in self.detail.splitlines() if part.strip())
        return f"{self.outcome:<4}  {self.name:<{NAME_WIDTH}}  {detail}"


def run_checks(env: Mapping[str, str] | None = None) -> list[Check]:
    """Look at the whole setup and report on each part of it, touching no network."""
    source = environment() if env is None else env
    return [
        _credentials_check(source),
        _surface_check(source),
        _token_cache_check(source),
        _configuration_check(source),
    ]


def _credentials_check(env: Mapping[str, str]) -> Check:
    """Is there one account with a secret to spend on it (docs/adr/0003)?"""
    try:
        credentials = load_credentials(env)
    except CredentialsError as error:
        return Check("credentials", Outcome.FAIL, str(error))
    return Check(
        "credentials",
        Outcome.PASS,
        f"account {credentials.account_id}, secret key set, both from the environment",
    )


def _surface_check(env: Mapping[str, str]) -> Check:
    """Where commands would be pointed, and whether that is LIVE (docs/adr/0004)."""
    base_url = env.get(BASE_URL_ENV_VAR) or HOSTAWAY_API_BASE_URL
    split = urlsplit(base_url)
    if split.scheme not in {"http", "https"} or not split.hostname:
        return Check(
            "surface",
            Outcome.FAIL,
            f"{BASE_URL_ENV_VAR} is not a usable base URL: {base_url!r}. "
            f"Unset it for Hostaway itself, or give a full URL such as {HOSTAWAY_API_BASE_URL}.",
        )
    return Check("surface", Outcome.PASS, f"{surface_of(base_url)} | {base_url}")


def _token_cache_check(env: Mapping[str, str]) -> Check:
    """Can the cached token be trusted, and is it this account's (docs/adr/0003)?"""
    configured = env.get(TOKEN_CACHE_ENV_VAR)
    if not configured:
        return Check(
            "token cache",
            Outcome.PASS,
            f"not configured; set {TOKEN_CACHE_ENV_VAR} to keep a token between commands",
        )
    path = Path(configured).expanduser()
    if not path.exists():
        return Check(
            "token cache",
            Outcome.PASS,
            f"{path} does not exist yet; the next command writes it owner-only",
        )
    account_id = env.get(ACCOUNT_ID_ENV_VAR)
    if not account_id:
        return Check(
            "token cache",
            Outcome.WARN,
            f"{path} exists, but which account it should hold is unknown "
            f"until {ACCOUNT_ID_ENV_VAR} is set",
        )
    try:
        token = TokenCache(path=path, account_id=account_id).load()
    except TokenCacheError as error:
        return Check("token cache", Outcome.FAIL, str(error))
    mode = stat.S_IMODE(path.stat().st_mode)
    held = "an expired token; the next command replaces it" if token is None else "a live token"
    return Check(
        "token cache",
        Outcome.PASS,
        f"{path} is mode {mode:04o} and holds {held} for account {account_id}",
    )


def _configuration_check(env: Mapping[str, str]) -> Check:
    """Are the operator's house defaults where they say, and do they parse?

    Absence is a warning, not a failure: reads need no configuration, and doctor
    is not being asked about a particular command.  Create and backfill refuse on
    their own when the file is missing (docs/adr/0002).
    """
    configured = env.get(CONFIG_ENV_VAR)
    if not configured:
        return Check(
            "configuration",
            Outcome.WARN,
            f"{CONFIG_ENV_VAR} is not set; reads are fine, "
            "but create and backfill will refuse without house defaults",
        )
    try:
        config = load_config(configured)
    except ConfigError as error:
        return Check("configuration", Outcome.FAIL, str(error))
    return Check(
        "configuration",
        Outcome.PASS,
        f"{Path(configured).expanduser()}: {len(config.house_defaults)} house defaults, "
        f"{len(config.fill_only_if_empty)} fill-only-if-empty, "
        f"{len(config.markups.wire_fields())} markups",
    )
