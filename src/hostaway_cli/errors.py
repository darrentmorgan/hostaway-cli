"""Typed Hostaway errors — the public error surface of ``HostawaySession``.

Every terminal failure a caller can reasonably branch on is one of these.  They
are raised after the transport has exhausted its retries, so catching one means
the request is finished, not merely unlucky.  Nothing below the session leaks
out: a caller never has to import ``httpx`` to find out what went wrong, and
``except HostawayError`` catches every way a call can fail::

    HostawayError
    ├── HostawayStatusError       Hostaway answered, and the answer is terminal
    │   ├── HostawayAuthError             401, or credentials it rejects
    │   ├── HostawayForbiddenError        403
    │   ├── HostawayNotFoundError         404
    │   ├── HostawayValidationError       422
    │   ├── HostawayRateLimitError        429, retries exhausted
    │   └── HostawayServerError           5xx, retries exhausted
    ├── HostawayTransportError    Hostaway was never reached, retries exhausted
    ├── HostawayProtocolError     the answer violates a documented contract
    │   ├── HostawayPaginationError
    │   └── HostawayCatalogError
    ├── HostawayCreateError       one non-retried create that cannot be trusted
    └── HostawayReadbackError     an applied write the read-back cannot confirm

The one thing outside the hierarchy is the session's own arguments: a session
built without credentials raises ``ValueError`` when it is first used, because
nothing about Hostaway has failed — the call was never made.
"""

from __future__ import annotations


class HostawayError(Exception):
    """Base for all terminal Hostaway-side errors."""


class HostawayStatusError(HostawayError):
    """Hostaway answered with a status the request cannot recover from.

    The base for every status-derived error, and the error a status the contract
    names nothing narrower for becomes, so a caller that does not branch on the
    exact status can still report what Hostaway said.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        status_code: int,
        body: object | None = None,
        message: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.status_code = status_code
        self.body = body
        super().__init__(message or f"Hostaway returned {status_code} for {endpoint}")


class HostawayAuthError(HostawayStatusError):
    """Hostaway rejects the credentials, or 401s again after a forced refresh."""

    def __init__(
        self,
        *,
        endpoint: str,
        status_code: int = 401,
        body: object | None = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            status_code=status_code,
            body=body,
            message=f"Hostaway rejected the credentials for {endpoint}",
        )


class HostawayForbiddenError(HostawayStatusError):
    """Hostaway returned 403 — resource not accessible to this account."""

    def __init__(
        self,
        *,
        endpoint: str,
        body: object | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            status_code=403,
            body=body,
            message=message or f"Hostaway resource not accessible: {endpoint}",
        )


class HostawayNotFoundError(HostawayStatusError):
    """Hostaway returned 404 for the requested resource."""

    def __init__(
        self,
        *,
        endpoint: str,
        body: object | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            status_code=404,
            body=body,
            message=message or f"Hostaway resource not found: {endpoint}",
        )


class HostawayValidationError(HostawayStatusError):
    """Hostaway returned 422 — request payload rejected."""

    def __init__(self, *, endpoint: str, body: object | None = None) -> None:
        super().__init__(
            endpoint=endpoint,
            status_code=422,
            body=body,
            message=f"Hostaway validation failed for {endpoint}",
        )


class HostawayRateLimitError(HostawayStatusError):
    """Hostaway returned 429 even after backoff retries."""

    def __init__(self, *, endpoint: str, body: object | None = None) -> None:
        super().__init__(
            endpoint=endpoint,
            status_code=429,
            body=body,
            message=f"Hostaway rate limit still refusing {endpoint} after retries",
        )


class HostawayServerError(HostawayStatusError):
    """Hostaway kept failing on its own side until the retries ran out."""

    def __init__(self, *, endpoint: str, status_code: int, body: object | None = None) -> None:
        super().__init__(
            endpoint=endpoint,
            status_code=status_code,
            body=body,
            message=f"Hostaway returned {status_code} for {endpoint} after retries",
        )


class HostawayTransportError(HostawayError):
    """Hostaway could not be reached: a timeout or network failure, retries spent.

    ``cause`` names the underlying httpx failure so a report can say which of
    them it was without the caller catching httpx exceptions itself.
    """

    def __init__(self, *, endpoint: str, cause: str) -> None:
        self.endpoint = endpoint
        self.cause = cause
        super().__init__(f"Hostaway could not be reached for {endpoint} ({cause})")


class HostawayProtocolError(HostawayError):
    """Hostaway returned a response that violates a documented contract."""

    def __init__(
        self,
        code: str,
        *,
        endpoint: str = "/listings",
        detail: object | None = None,
    ) -> None:
        self.code = code
        self.endpoint = endpoint
        self.detail = detail
        super().__init__(code)


class HostawayPaginationError(HostawayProtocolError):
    """A listing page cannot prove a complete, non-ambiguous scan."""


class HostawayCatalogError(HostawayProtocolError):
    """A catalog row is missing, malformed or cannot be read without coercion."""


class HostawayCreateError(HostawayError):
    """One non-retrying create attempt failed or returned an unsafe body."""

    def __init__(
        self,
        code: str,
        *,
        endpoint: str = "/listings",
        status_code: int | None = None,
        body: object | None = None,
    ) -> None:
        self.code = code
        self.endpoint = endpoint
        self.status_code = status_code
        self.body = body
        super().__init__(code)


class HostawayReadbackError(HostawayError):
    """An applied write cannot be verified by reading the listing back."""

    def __init__(self, code: str, *, listing_id: int, detail: object | None = None) -> None:
        self.code = code
        self.listing_id = listing_id
        self.detail = detail
        super().__init__(code)


def create_error_code(status_code: int) -> str:
    """Classify a failed create by what the operator can safely do next.

    ``create_ambiguous`` means a listing may or may not exist: reconcile before
    retrying. Every other code says the create definitely did not happen.
    """
    if status_code in {408, 409, 429} or status_code >= 500:
        return "create_ambiguous"
    if status_code in {400, 422}:
        return "create_validation_rejected"
    if status_code in {401, 403}:
        return "create_auth_rejected"
    if status_code == 404:
        return "create_endpoint_not_found"
    if 400 <= status_code < 500:
        return "create_rejected"
    return "create_http_error"
