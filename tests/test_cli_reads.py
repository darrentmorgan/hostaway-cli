"""``hsctl listings`` and ``hsctl get``, driven through the CLI test runner.

Seam 1: the command is invoked exactly as an operator invokes it, credentials
arrive through the environment, and only the HTTP layer is mocked.  Assertions
are on what the operator sees — the rendered table, the JSON, the banner on
stderr — never on how the command reaches Hostaway.
"""

from __future__ import annotations

import json
import re

import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import cli_env, mock_access_tokens, mock_endpoint, ok, villa, villas

runner = CliRunner()


def cells(line: str) -> list[str]:
    """One table row split back into its columns, on the two-space gutter."""
    return re.split(r"\s{2,}", line.strip())


def test_listings_renders_a_table_of_id_name_internal_name_and_channel_status(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])

    result = runner.invoke(app, ["listings"], env=cli_env())

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "5 listings"
    assert cells(lines[1]) == ["ID", "NAME", "INTERNAL", "CHANNEL"]
    assert cells(lines[2]) == ["1001", "Villa Saka", "Villa Saka (internal)", "exported"]
    assert cells(lines[6]) == ["1005", "Villa Padma", "Villa Padma (internal)", "not exported"]


def test_listings_says_how_many_of_the_total_it_is_showing(
    respx_mock: respx.MockRouter,
) -> None:
    """A page smaller than the account is a fact the operator has to be told."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=41)])

    result = runner.invoke(app, ["listings"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "5 of 41 listings"


def test_listings_prints_a_placeholder_where_a_listing_carries_no_value(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings",
        steps=[ok([villa(1001, name="Villa Saka", internalListingName=None)], count=1)],
    )

    result = runner.invoke(app, ["listings"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert cells(result.stdout.splitlines()[2]) == ["1001", "Villa Saka", "-", "exported"]


def test_get_prints_the_whole_listing_as_json(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    listing = villa(1001, name="Villa Saka", price=275, currencyCode="AUD")
    route = mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(listing)])

    result = runner.invoke(app, ["get", "1001"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == listing
    assert route.calls[0].request.url.path == "/v1/listings/1001"


def test_listings_counts_what_it_prints_when_hostaway_sends_no_usable_total(
    respx_mock: respx.MockRouter,
) -> None:
    """A total the session could not read is zero, and zero is not what is shown."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count="unreadable")])

    result = runner.invoke(app, ["listings"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "5 listings"


def test_listings_never_truncates_an_id(respx_mock: respx.MockRouter) -> None:
    """A shortened name is still a name; a shortened ID is the wrong listing."""
    long_name = "Villa Saka with an Unreasonably Long Marketing Name By The Sea"
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings",
        steps=[ok([villa(123456789012, name=long_name)], count=1)],
    )

    result = runner.invoke(app, ["listings"], env=cli_env())

    assert result.exit_code == 0, result.output
    listing_id, name, _, _ = cells(result.stdout.splitlines()[2])
    assert listing_id == "123456789012"
    assert len(name) == 34
    assert long_name.startswith(name[:-1])
