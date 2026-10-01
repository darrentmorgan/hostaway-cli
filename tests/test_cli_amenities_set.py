"""``hsctl amenities-set``: amenity writes merge against the listing's current set.

Hostaway replaces the whole amenity set on every write, so what this command
sends is always the complete set it computed — the merge is the safety, and each
test asserts on the set that reached the wire.
"""

from __future__ import annotations

import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import (
    amenity_catalog,
    cli_env,
    mock_access_tokens,
    mock_endpoint,
    ok,
    plain,
    sent_body,
    villa,
)

runner = CliRunner()


def test_add_sends_the_existing_amenities_as_well_as_the_new_one(
    respx_mock: respx.MockRouter,
) -> None:
    """A write replaces the whole set, so a partial list would wipe the rest."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001, amenity_ids=(1, 2, 3))), ok(villa(1001, amenity_ids=(1, 2, 3, 4)))],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(
        app, ["amenities-set", "1001", "--add", "Pool towels", "--apply"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert sent_body(put) == {
        "listingAmenities": [{"amenityId": 1}, {"amenityId": 2}, {"amenityId": 3}, {"amenityId": 4}]
    }


def test_removing_an_amenity_the_listing_does_not_have_changes_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, amenity_ids=(1, 2)))])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(
        app, ["amenities-set", "1001", "--remove", "5", "--apply"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert "Kitchen" in plain(result.stdout)
    assert "No change" in plain(result.stdout)
    assert not put.called


def test_a_dry_run_shows_the_whole_set_before_and_after_and_sends_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])
    mock_endpoint(
        respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, amenity_ids=(1, 2, 3)))]
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(
        app, ["amenities-set", "1001", "--add", "4", "--remove", "Private pool"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert "before (3): 1:Wifi, 2:Private pool, 3:Air conditioning" in plain(result.stdout)
    assert "after  (3): 1:Wifi, 3:Air conditioning, 4:Pool towels" in plain(result.stdout)
    assert "+ added:   4:Pool towels" in plain(result.stdout)
    assert "- removed: 2:Private pool" in plain(result.stdout)
    assert "DRY RUN" in plain(result.stdout)
    assert not put.called


def test_an_amenity_the_account_catalog_does_not_publish_is_refused(
    respx_mock: respx.MockRouter,
) -> None:
    """An unknown ID is a valid number standing for another amenity, or for none."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(
        app, ["amenities-set", "1001", "--add", "Helipad", "--apply"], env=cli_env()
    )

    assert result.exit_code != 0, result.output
    assert "Helipad" in plain(result.output)
    assert not put.called
