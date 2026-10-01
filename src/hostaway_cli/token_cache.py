"""An optional, owner-only file holding one account's bearer token between commands.

A Hostaway token is valid for years, so re-authenticating on every command is
both slow and pointless.  The cache is opt-in — ``HSCTL_TOKEN_CACHE`` names the
file — because it puts a live credential on disk, and everything here exists to
make that safe: the file is refused unless only its owner can read it, it is
replaced atomically so a killed command cannot leave a torn token behind, and it
is bound to the account that wrote it (docs/adr/0003).
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hostaway_cli._token import AccessToken

FILE_MODE = 0o600
DIRECTORY_MODE = 0o700

__all__ = ["DIRECTORY_MODE", "FILE_MODE", "TokenCache", "TokenCacheError"]


class TokenCacheError(Exception):
    """The cache file exists but cannot be trusted to hold this account's token."""


@dataclass(frozen=True)
class TokenCache:
    """One account's token cache file. Bound to the account, not just the path."""

    path: Path
    account_id: str

    def load(self) -> AccessToken | None:
        """The cached token, or ``None`` when there is no usable one to spend."""
        if not self.path.exists():
            return None
        self._refuse_unsafe_permissions()
        document = self._contents()
        cached_account = document.get("account_id")
        if cached_account != self.account_id:
            raise TokenCacheError(
                f"Token cache holds another account: {self.path} was written for "
                f"{cached_account or 'no account'}, this command runs on {self.account_id}. "
                "Point HSCTL_TOKEN_CACHE at a file of its own, or delete it."
            )
        return self._token_in(document)

    def save(self, token: AccessToken) -> None:
        """Replace the cache with ``token``, atomically and owner-only."""
        self.path.parent.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = {
            "account_id": self.account_id,
            "access_token": token.access_token,
            "expires_at": token.expires_at.isoformat(),
        }
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _token_in(self, document: dict[str, Any]) -> AccessToken | None:
        """The token this document carries, with the life it has left.

        A token whose life has run out is not a token: ``None`` sends the caller
        to fetch a new one, which is what an empty cache does.  Anything else the
        document gets wrong is the operator's file to fix, so it is named rather
        than left to surface as a key, date or validation error from underneath.
        """
        try:
            expires_at = datetime.fromisoformat(str(document["expires_at"])).astimezone(UTC)
            remaining = int((expires_at - datetime.now(UTC)).total_seconds())
            if remaining < 1:
                return None
            # pydantic raises ValidationError, a ValueError, for a token too
            # short or otherwise unlike one.
            return AccessToken(access_token=str(document["access_token"]), expires_in=remaining)
        except (KeyError, TypeError, ValueError) as error:
            raise TokenCacheError(
                f"Token cache does not hold a usable token: {self.path} ({error}). "
                "Delete the file and run the command again."
            ) from error

    def _refuse_unsafe_permissions(self) -> None:
        """Stop if anyone but the owner can reach the token."""
        mode = stat.S_IMODE(self.path.stat().st_mode)
        if mode & 0o077:
            raise TokenCacheError(
                f"Token cache permissions are unsafe: {self.path} is mode {mode:04o} and "
                f"holds a live bearer token. Run: chmod 0600 {self.path}"
            )

    def _contents(self) -> dict[str, Any]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TokenCacheError(f"Token cache unreadable: {self.path} ({error}).") from error
        if not isinstance(document, dict):
            raise TokenCacheError(f"Token cache is not an object: {self.path}.")
        return document
