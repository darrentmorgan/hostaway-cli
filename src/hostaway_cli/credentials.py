"""The account, secret and base URL a command runs against, read from the environment.

hsctl resolves credentials from environment variables and nothing else, so it
makes no assumption about how an operator stores secrets: any secret manager,
any shell, or a ``.env`` file beside the project (docs/adr/0003).

    HOSTAWAY_ACCOUNT_ID   required   the numeric account ID
    HOSTAWAY_SECRET_KEY   required   that account's API secret
    HOSTAWAY_API_BASE_URL optional   defaults to Hostaway's own API
    HSCTL_TOKEN_CACHE     optional   path to the owner-only token cache file
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from hostaway_cli.session import HOSTAWAY_API_BASE_URL
from hostaway_cli.surface import Surface, surface_of

ACCOUNT_ID_ENV_VAR = "HOSTAWAY_ACCOUNT_ID"
SECRET_KEY_ENV_VAR = "HOSTAWAY_SECRET_KEY"
BASE_URL_ENV_VAR = "HOSTAWAY_API_BASE_URL"
TOKEN_CACHE_ENV_VAR = "HSCTL_TOKEN_CACHE"

REQUIRED_ENV_VARS = (ACCOUNT_ID_ENV_VAR, SECRET_KEY_ENV_VAR)

__all__ = [
    "ACCOUNT_ID_ENV_VAR",
    "BASE_URL_ENV_VAR",
    "REQUIRED_ENV_VARS",
    "SECRET_KEY_ENV_VAR",
    "TOKEN_CACHE_ENV_VAR",
    "Credentials",
    "CredentialsError",
    "environment",
    "load_credentials",
]


class CredentialsError(Exception):
    """The environment does not describe one usable Hostaway account."""


@dataclass(frozen=True)
class Credentials:
    """One account's credentials and the surface they will be spent on."""

    account_id: str
    secret_key: str = field(repr=False)
    base_url: str = HOSTAWAY_API_BASE_URL
    token_cache_path: Path | None = None

    @property
    def surface(self) -> Surface:
        """LIVE or SANDBOX, judged from ``base_url`` (docs/adr/0004)."""
        return surface_of(self.base_url)


def load_credentials(env: Mapping[str, str] | None = None) -> Credentials:
    """The account this command runs against, or a refusal naming what is missing.

    Reads ``os.environ`` after loading a ``.env`` file if one is beside the
    caller; pass ``env`` to read a mapping instead, which is what an offline
    check does when it wants to report on an environment other than its own.
    """
    source = environment() if env is None else env
    missing = [name for name in REQUIRED_ENV_VARS if not source.get(name)]
    if missing:
        raise CredentialsError(
            f"Hostaway credentials missing: {', '.join(missing)}. "
            f"Export {' and '.join(REQUIRED_ENV_VARS)} in your shell or a .env file; "
            "hsctl reads credentials from the environment and nowhere else."
        )
    cache = source.get(TOKEN_CACHE_ENV_VAR)
    return Credentials(
        account_id=source[ACCOUNT_ID_ENV_VAR],
        secret_key=source[SECRET_KEY_ENV_VAR],
        base_url=source.get(BASE_URL_ENV_VAR) or HOSTAWAY_API_BASE_URL,
        token_cache_path=Path(cache).expanduser() if cache else None,
    )


def environment() -> Mapping[str, str]:
    """The process environment, with a ``.env`` file folded in if there is one.

    ``load_dotenv`` never overrides a variable that is already set, so an
    exported credential always wins over a file.  Public because everything hsctl
    is configured with is read from here: an offline check reports on the same
    environment a command would run against, folded in the same way.
    """
    load_dotenv()
    return os.environ
