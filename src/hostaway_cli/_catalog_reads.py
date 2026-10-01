"""The account-scoped catalog reads of ``HostawaySession``.

Package-private mixin: the transport core (``_get``) belongs to the session,
which mixes this class in.  Row validation itself lives in ``catalogs.py``; what
this module owns is the endpoint each catalog is published at and the envelope
they all answer with.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from hostaway_cli.catalogs import validate_catalog_rows
from hostaway_cli.errors import HostawayCatalogError

# A cancellation policy ID means nothing outside the channel that published it,
# so each channel is read from its own endpoint and named at the call.
CANCELLATION_POLICY_ENDPOINTS: Mapping[str, str] = MappingProxyType(
    {
        "native": "/cancellationPolicies",
        "airbnb": "/cancellationPolicies/airbnb",
        "booking": "/cancellationPolicies/booking",
        "vrbo": "/cancellationPolicies/vrbo",
        "marriott": "/cancellationPolicies/marriott",
    }
)


class _CatalogReadsMixin:
    """Amenity, bed-type, custom-field, property-type and policy catalogs."""

    if TYPE_CHECKING:
        # Provided by the session's transport core.
        async def _get(self, endpoint: str, *, params: dict[str, Any]) -> dict[str, Any]: ...

    async def get_amenities(self) -> list[dict[str, Any]]:
        """The amenity catalog: the names ``amenityId`` values stand for."""
        return await self._catalog("/amenities", kind="amenity")

    async def get_bed_types(self) -> list[dict[str, Any]]:
        """The bed-type catalog a listing's bedroom configuration draws on."""
        return await self._catalog("/bedTypes", kind="bed_type")

    async def get_custom_fields(self) -> list[dict[str, Any]]:
        """The listing custom fields, and only those.

        ``/customFields`` publishes the fields of several object types at once
        and their IDs are not interchangeable, so the object filter belongs to
        the read rather than to the caller: an unfiltered catalog is one from
        which a listing write can be built carrying another object's field ID.
        """
        return await self._catalog(
            "/customFields", kind="custom_field", params={"objectType": "listing"}
        )

    async def get_property_types(self) -> list[dict[str, Any]]:
        """The property-type catalog a listing's type is chosen from."""
        return await self._catalog("/propertyTypes", kind="property_type")

    async def get_cancellation_policies(self, channel: str) -> list[dict[str, Any]]:
        """The cancellation-policy catalog one channel publishes.

        Named channels only: a channel this package has no endpoint for is
        refused here rather than guessed at, because a policy ID read from the
        wrong catalog is a valid number that cancels under different terms.
        """
        endpoint = CANCELLATION_POLICY_ENDPOINTS.get(channel)
        if endpoint is None:
            raise ValueError(
                "unsupported_cancellation_policy_channel: "
                f"{channel!r} is not one of {sorted(CANCELLATION_POLICY_ENDPOINTS)}"
            )
        return await self._catalog(endpoint, kind="cancellation_policy")

    async def _catalog(
        self, endpoint: str, *, kind: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """One catalog endpoint read and validated."""
        data = await self._get(endpoint, params=params or {})
        rows = data.get("result")
        if not isinstance(rows, list):
            raise HostawayCatalogError(
                "catalog_rows_invalid",
                endpoint=endpoint,
                detail={"catalog_kind": kind, "result_type": type(rows).__name__},
            )
        return validate_catalog_rows(rows, catalog_kind=kind, endpoint=endpoint)
