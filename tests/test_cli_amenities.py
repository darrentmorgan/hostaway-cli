"""``hsctl amenities`` and ``hsctl listing-amenities`` through the CLI runner (seam 1).

Both commands exist to plan an amenity change, and an amenity write replaces the
listing's whole set, so what an operator needs first is the truth about two
lists: what the account's catalog publishes, and what this listing already has.
"""

from __future__ import annotations

import re

import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import (
    amenity_catalog,
    cli_env,
    mock_access_tokens,
    mock_endpoint,
    ok,
    villa,
)

runner = CliRunner()


def cells(line: str) -> list[str]:
    """One table row split back into its columns, on the two-space gutter."""
    return re.split(r"\s{2,}", line.strip())


def test_amenities_lists_the_account_catalog(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])

    result = runner.invoke(app, ["amenities"], env=cli_env())

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "5 amenities"
    assert cells(lines[1]) == ["ID", "NAME"]
    assert cells(lines[2]) == ["1", "Wifi"]
    assert cells(lines[6]) == ["5", "Kitchen"]


def test_amenities_searches_the_catalog_by_name(respx_mock: respx.MockRouter) -> None:
    """The search is a substring, whatever its case, and says what it left out."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])

    result = runner.invoke(app, ["amenities", "--search", "POOL"], env=cli_env())

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "2 of 5 amenities"
    assert [cells(line)[1] for line in lines[2:]] == ["Private pool", "Pool towels"]


def test_listing_amenities_resolves_a_listing_set_to_catalog_names(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, amenity_ids=(3, 1)))])

    result = runner.invoke(app, ["listing-amenities", "1001"], env=cli_env())

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "2 amenities on listing 1001"
    assert cells(lines[1]) == ["ID", "NAME"]
    assert [cells(line) for line in lines[2:]] == [["1", "Wifi"], ["3", "Air conditioning"]]


def test_listing_amenities_says_so_when_the_catalog_does_not_publish_one(
    respx_mock: respx.MockRouter,
) -> None:
    """An unnamed ID is still shown: it is the one the operator has to ask about."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, amenity_ids=(1, 87)))])

    result = runner.invoke(app, ["listing-amenities", "1001"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert cells(result.stdout.splitlines()[3]) == ["87", "(unknown)"]
