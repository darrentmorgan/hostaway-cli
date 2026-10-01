"""The catalog surface of ``HostawaySession``, driven against mocked routes.

A catalog read exists to turn a name an operator typed into the numeric ID a
write has to carry, so these tests assert on the endpoint that was called and on
the rows that come back — never on how the rows are validated inside.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from hostaway_cli import HostawayCatalogError, HostawaySession
from hostaway_mocks import ACCOUNT_ID, BASE_URL, SECRET_KEY, mock_access_tokens, mock_endpoint, ok


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


async def test_get_amenities_reads_the_account_amenity_catalog(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    rows = [{"id": 11, "name": "Private pool"}, {"id": 12, "name": "Air conditioning"}]
    route = mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(rows)])

    assert await session().get_amenities() == rows
    assert route.called


async def test_get_bed_types_reads_the_account_bed_type_catalog(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    rows = [{"id": 21, "name": "King bed"}, {"id": 22, "name": "Bunk bed"}]
    route = mock_endpoint(respx_mock, "GET", "/bedTypes", steps=[ok(rows)])

    assert await session().get_bed_types() == rows
    assert route.called


async def test_get_custom_fields_asks_only_for_listing_fields(
    respx_mock: respx.MockRouter,
) -> None:
    """The object filter is part of the read, not a caller's choice.

    ``/customFields`` publishes fields for several object types in one catalog and
    their IDs are not interchangeable, so a listing write built from an
    unfiltered catalog can carry a reservation field's ID.
    """
    mock_access_tokens(respx_mock)
    rows = [{"id": 31, "name": "Map link"}]
    route = mock_endpoint(respx_mock, "GET", "/customFields", steps=[ok(rows)])

    assert await session().get_custom_fields() == rows
    assert dict(httpx.URL(str(route.calls[0].request.url)).params) == {"objectType": "listing"}


async def test_get_property_types_reads_the_account_property_type_catalog(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    rows = [{"id": 41, "name": "Villa"}]
    route = mock_endpoint(respx_mock, "GET", "/propertyTypes", steps=[ok(rows)])

    assert await session().get_property_types() == rows
    assert route.called


CANCELLATION_POLICY_ENDPOINTS = {
    "native": "/cancellationPolicies",
    "airbnb": "/cancellationPolicies/airbnb",
    "booking": "/cancellationPolicies/booking",
    "vrbo": "/cancellationPolicies/vrbo",
    "marriott": "/cancellationPolicies/marriott",
}


@pytest.mark.parametrize(
    ("channel", "endpoint"),
    CANCELLATION_POLICY_ENDPOINTS.items(),
    ids=CANCELLATION_POLICY_ENDPOINTS,
)
async def test_each_channel_has_its_own_cancellation_policy_catalog(
    respx_mock: respx.MockRouter, channel: str, endpoint: str
) -> None:
    """A policy ID is channel-scoped: the same number means nothing on another."""
    mock_access_tokens(respx_mock)
    rows = [{"id": 51, "name": "Flexible"}, {"id": 52, "name": "Firm"}]
    route = mock_endpoint(respx_mock, "GET", endpoint, steps=[ok(rows)])

    assert await session().get_cancellation_policies(channel) == rows
    assert route.called


async def test_an_unknown_cancellation_policy_channel_is_refused_before_any_request(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)

    with pytest.raises(ValueError, match="unsupported_cancellation_policy_channel"):
        await session().get_cancellation_policies("expedia")

    assert not respx_mock.calls


# A catalog row identifies the thing a write will name. None of these is a row
# this package will hand back: reading any of them as a usable ID is how an
# amenity write lands on the wrong amenity.
UNREADABLE_ROWS: dict[str, Any] = {
    "an id as a string": [{"id": "11", "name": "Private pool"}],
    "a missing id": [{"name": "Private pool"}],
    "a zero id": [{"id": 0, "name": "Private pool"}],
    "a negative id": [{"id": -11, "name": "Private pool"}],
    "a boolean id": [{"id": True, "name": "Private pool"}],
    "a missing name": [{"id": 11}],
    "an empty name": [{"id": 11, "name": ""}],
    "a row that is not an object": [["id", 11]],
    "a good row beside a bad one": [{"id": 11, "name": "Private pool"}, {"id": None}],
}


@pytest.mark.parametrize("rows", UNREADABLE_ROWS.values(), ids=UNREADABLE_ROWS)
async def test_a_catalog_row_that_cannot_be_read_exactly_is_refused(
    respx_mock: respx.MockRouter, rows: Any
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(rows)])

    with pytest.raises(HostawayCatalogError) as caught:
        await session().get_amenities()

    assert caught.value.code == "catalog_row_invalid"


async def test_an_envelope_carrying_no_catalog_is_refused_rather_than_read_as_empty(
    respx_mock: respx.MockRouter,
) -> None:
    """An empty catalog and an unreadable one lead an operator to opposite acts.

    "No such amenity" invites a new name; "Hostaway sent something I cannot read"
    invites a retry. Defaulting the second to the first hides it.
    """
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[httpx.Response(200, json={"ok": True})])

    with pytest.raises(HostawayCatalogError) as caught:
        await session().get_amenities()

    assert caught.value.code == "catalog_rows_invalid"


async def test_a_catalog_row_keeps_the_fields_beyond_id_and_name(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    rows = [{"id": 11, "name": "Private pool", "category": "Outdoor"}]
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(rows)])

    assert await session().get_amenities() == rows
