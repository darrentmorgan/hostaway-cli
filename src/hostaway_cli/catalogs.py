"""Validation for the account-scoped catalog rows Hostaway publishes.

A catalog row is the pair a write depends on: the name an operator recognises
and the numeric ID Hostaway wants.  Every row is validated on the way in and
nothing is coerced — a row whose ID arrives as ``"11"`` is a row this package
refuses, because silently reading it as ``11`` is how a write reaches the wrong
amenity.  Unknown keys are kept, so a caller that wants a category or an icon
still has it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from hostaway_cli.errors import HostawayCatalogError


class HostawayCatalogItem(BaseModel):
    """One validated catalog row. Fields beyond id and name stay available."""

    model_config = ConfigDict(extra="allow", strict=True)

    id: StrictInt = Field(..., gt=0)
    name: str = Field(..., min_length=1)


def validate_catalog_rows(
    rows: Iterable[Any],
    *,
    catalog_kind: str,
    endpoint: str,
) -> list[dict[str, Any]]:
    """Every row validated, in order, or a refusal naming the row that was wrong.

    One bad row fails the whole catalog rather than being dropped: a catalog
    silently missing the entry an operator asked for reads as "no such amenity",
    which is a different and much more confusing failure.
    """
    validated: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise HostawayCatalogError(
                "catalog_row_invalid",
                endpoint=endpoint,
                detail={"catalog_kind": catalog_kind, "index": index},
            )
        try:
            item = HostawayCatalogItem.model_validate(dict(row))
        except ValidationError as exc:
            raise HostawayCatalogError(
                "catalog_row_invalid",
                endpoint=endpoint,
                detail={"catalog_kind": catalog_kind, "index": index},
            ) from exc
        validated.append(item.model_dump(mode="json"))
    return validated
