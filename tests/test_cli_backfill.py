"""``hsctl backfill``: the operator's house defaults onto a listing that exists (seam 1).

Every test drives the command as an operator does. What these tests pin is the one
judgement a backfill makes that no other write makes: which of the configured values
belong on this listing, given what it already carries.
"""

from __future__ import annotations

from pathlib import Path

import respx
import yaml
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_cli.config import load_config
from hostaway_mocks import (
    bed_type_catalog,
    cli_env,
    mock_access_tokens,
    mock_endpoint,
    ok,
    plain,
    sent_body,
    squashed,
    villa,
)

runner = CliRunner()

LISTING_ID = 1001

FULL_CONFIG = Path(__file__).parent / "fixtures" / "full-config.yaml"
DRAFT_PATH = Path(__file__).parent / "fixtures" / "villa-nira-draft.yaml"


def configured_env(**overrides: str | None) -> dict[str, str | None]:
    """The CLI environment, pointed at the shipped example configuration."""
    return cli_env(HSCTL_CONFIG=str(FULL_CONFIG), **overrides)


def test_a_backfill_shows_the_house_defaults_and_sends_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    """The default outcome of a backfill is a diff and an untouched listing."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(villa(LISTING_ID))])
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(app, ["backfill", str(LISTING_ID)], env=configured_env())

    assert result.exit_code == 0, result.output
    assert "cancellationPolicyId: None -> 2001" in plain(result.stdout)
    assert "contactEmail: None -> 'stays@example.com'" in plain(result.stdout)
    assert "DRY RUN" in plain(result.stdout)
    assert not put.called


def test_a_house_default_the_listing_already_carries_is_not_a_change(
    respx_mock: respx.MockRouter,
) -> None:
    """A backfill fills gaps; a field already holding the configured value is not one."""
    mock_access_tokens(respx_mock)
    settled = villa(LISTING_ID, language="en", cancellationPolicyId=2001)
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(settled)])

    result = runner.invoke(app, ["backfill", str(LISTING_ID)], env=configured_env())

    assert result.exit_code == 0, result.output
    assert "language:" not in plain(result.stdout)
    assert "cancellationPolicyId:" not in plain(result.stdout)
    assert "airbnbCancellationPolicyId: None -> 2002" in plain(result.stdout)


def test_every_configured_house_default_reaches_the_listing_even_with_no_draft(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """``hsctl backfill <id>`` alone means the configuration, all of it.

    Some house defaults name wire fields a draft can also speak for — the check-out
    hour, the floor area, the network name. Without a draft nobody is speaking for
    them but the operator's file, so silence must not be read as an instruction to
    leave them behind.
    """
    mock_access_tokens(respx_mock)
    config = tmp_path / "config.yaml"
    configured = {
        "checkInTimeEnd": 22,
        "wifiUsername": "HOUSE-NET",
        "squareMeters": 100,
        "language": "en",
    }
    config.write_text(yaml.safe_dump({"house_defaults": configured}), encoding="utf-8")
    mock_endpoint(
        respx_mock,
        "GET",
        f"/listings/{LISTING_ID}",
        steps=[ok(villa(LISTING_ID)), ok(villa(LISTING_ID) | configured)],
    )
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(
        app, ["backfill", str(LISTING_ID), "--apply"], env=cli_env(HSCTL_CONFIG=str(config))
    )

    assert result.exit_code == 0, result.output
    assert "backfilling 4 fields" in plain(result.stdout)
    assert "checkInTimeEnd: None -> 22" in plain(result.stdout)
    assert "wifiUsername: None -> 'HOUSE-NET'" in plain(result.stdout)
    assert "squareMeters: None -> 100" in plain(result.stdout)
    assert sent_body(put) == configured


def test_a_populated_fill_only_if_empty_field_is_left_alone_and_an_empty_one_is_filled(
    respx_mock: respx.MockRouter,
) -> None:
    """One listing's contact block says one thing and the configuration another.

    Deciding which is right is not a backfill's job: a house default fills a gap and
    stops there, so an operator's deliberate edit survives every later backfill.
    """
    mock_access_tokens(respx_mock)
    edited = villa(LISTING_ID, contactName="Ari", contactEmail="")
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(edited)])

    result = runner.invoke(app, ["backfill", str(LISTING_ID)], env=configured_env())

    assert result.exit_code == 0, result.output
    assert "contactName:" not in plain(result.stdout)
    assert "contactEmail: '' -> 'stays@example.com'" in plain(result.stdout)
    assert "Left alone" in plain(result.stdout)
    assert "contactName" in plain(result.stdout)


def test_force_overwrites_a_populated_fill_only_if_empty_field(
    respx_mock: respx.MockRouter,
) -> None:
    """An operator repairing a contact block asks for the convention to win."""
    mock_access_tokens(respx_mock)
    edited = villa(LISTING_ID, contactName="Ari")
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(edited)])

    result = runner.invoke(app, ["backfill", str(LISTING_ID), "--force"], env=configured_env())

    assert result.exit_code == 0, result.output
    assert "contactName: 'Ari' -> 'Guest'" in plain(result.stdout)
    assert "Left alone" not in plain(result.stdout)


def test_a_listing_that_already_answers_the_configuration_is_left_untouched(
    respx_mock: respx.MockRouter,
) -> None:
    """Nothing to write is not an empty write: the PUT is never made, even with --apply."""
    mock_access_tokens(respx_mock)
    config = load_config(FULL_CONFIG)
    settled = villa(LISTING_ID, **config.house_defaults)
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(settled)])
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(app, ["backfill", str(LISTING_ID), "--apply"], env=configured_env())

    assert result.exit_code == 0, result.output
    assert "nothing to backfill" in plain(result.stdout)
    assert not put.called


def test_apply_sends_only_the_fields_the_diff_showed_and_reads_the_listing_back(
    respx_mock: respx.MockRouter,
) -> None:
    """What the operator approved is what goes: the held-back field never reaches the wire."""
    mock_access_tokens(respx_mock)
    config = load_config(FULL_CONFIG)
    expected = {
        field: value for field, value in config.house_defaults.items() if field != "contactName"
    }
    before = villa(LISTING_ID, contactName="Ari")
    mock_endpoint(
        respx_mock,
        "GET",
        f"/listings/{LISTING_ID}",
        steps=[ok(before), ok(before | expected)],
    )
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(app, ["backfill", str(LISTING_ID), "--apply"], env=configured_env())

    assert result.exit_code == 0, result.output
    assert sent_body(put) == expected
    assert "contactEmail: stored" in plain(result.stdout)
    assert "Verified." in plain(result.stdout)
    assert "DRY RUN" not in plain(result.stdout)


def test_a_house_default_hostaway_discarded_is_named_and_the_command_fails(
    respx_mock: respx.MockRouter,
) -> None:
    """Hostaway answers success and stores part of a backfill; the read-back says so."""
    mock_access_tokens(respx_mock)
    config = load_config(FULL_CONFIG)
    landed = dict(config.house_defaults)
    del landed["marriottCancellationPolicyId"]
    mock_endpoint(
        respx_mock,
        "GET",
        f"/listings/{LISTING_ID}",
        steps=[ok(villa(LISTING_ID)), ok(villa(LISTING_ID) | landed)],
    )
    mock_endpoint(respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})])

    result = runner.invoke(app, ["backfill", str(LISTING_ID), "--apply"], env=configured_env())

    assert result.exit_code == 1, result.output
    assert "cancellationPolicyId: stored" in plain(result.stdout)
    assert "marriottCancellationPolicyId: dropped" in plain(result.stdout)
    assert "Dropped by Hostaway: marriottCancellationPolicyId." in plain(result.stdout)


def test_the_configured_markups_stay_out_of_a_backfill_that_did_not_ask_for_them(
    respx_mock: respx.MockRouter,
) -> None:
    """Money-adjacent: a multiplier rides along with nothing."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(villa(LISTING_ID))])

    result = runner.invoke(app, ["backfill", str(LISTING_ID)], env=configured_env())

    assert result.exit_code == 0, result.output
    assert "Markup" not in plain(result.stdout)


def test_markups_are_ordinary_fields_and_apply_without_the_protected_flag(
    respx_mock: respx.MockRouter,
) -> None:
    """A markup is a multiplier over an amount, not the amount: ordinary (docs/adr/0001)."""
    mock_access_tokens(respx_mock)
    config = load_config(FULL_CONFIG)
    landed = dict(config.house_defaults) | config.markups.wire_fields()
    mock_endpoint(
        respx_mock,
        "GET",
        f"/listings/{LISTING_ID}",
        steps=[ok(villa(LISTING_ID)), ok(villa(LISTING_ID) | landed)],
    )
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(
        app, ["backfill", str(LISTING_ID), "--markups", "--apply"], env=configured_env()
    )

    assert result.exit_code == 0, result.output
    assert "airbnbOfficialListingMarkup: None -> 1.2" in plain(result.stdout)
    assert sent_body(put) == landed
    assert "Channel markups in this change: airbnbOfficialListingMarkup, " in plain(result.stdout)
    assert "Protected fields in this change" not in plain(result.stdout)
    assert "Verified." in plain(result.stdout)


def test_backfill_without_a_configuration_refuses_and_sends_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    """House defaults are the operator's; hsctl has none to fall back on (docs/adr/0002)."""
    tokens = mock_access_tokens(respx_mock)
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(app, ["backfill", str(LISTING_ID)], env=cli_env())

    assert result.exit_code == 2, result.output
    assert "HSCTL_CONFIG is not set" in plain(result.stderr)
    assert not put.called
    assert not tokens.called


def test_a_protected_house_default_still_needs_the_protected_flag(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """The gate reads the change, never the command that built it (docs/adr/0001)."""
    mock_access_tokens(respx_mock)
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump({"house_defaults": {"cleaningFee": 45, "language": "en"}}),
        encoding="utf-8",
    )
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(villa(LISTING_ID))])
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(
        app, ["backfill", str(LISTING_ID), "--apply"], env=cli_env(HSCTL_CONFIG=str(config))
    )

    assert result.exit_code == 3, result.output
    assert "cleaning fee" in plain(result.stderr)
    assert not put.called


def test_a_draft_adds_the_property_facts_a_create_never_sent(
    respx_mock: respx.MockRouter,
) -> None:
    """Headline, floor area, network and beds: the fields a create has no place for."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/bedTypes", steps=[ok(bed_type_catalog())])
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(villa(LISTING_ID))])

    result = runner.invoke(
        app,
        ["backfill", str(LISTING_ID), str(DRAFT_PATH)],
        env=configured_env(HSCTL_WIFI_PASSWORD="a-network-secret"),
    )

    assert result.exit_code == 0, result.output
    assert "homeawayPropertyHeadline: None -> 'Villa Nira — clifftop pool villa'" in plain(
        result.stdout
    )
    assert "squareMeters: None -> 320" in plain(result.stdout)
    assert "wifiUsername: None -> 'NIRA-GUEST'" in plain(result.stdout)
    assert "listingBedTypes: None -> [{'bedTypeId': 1101," in plain(result.stdout)


def test_a_draft_speaks_for_itself_and_stays_silent_over_the_rest_of_the_configuration(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """Where a draft and the configuration name the same field, the draft is the fact.

    Where the draft says nothing the configuration still stands: a draft that omits
    the check-out hour is not an operator withdrawing the one they configured.
    """
    mock_access_tokens(respx_mock)
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"house_defaults": {"checkInTimeEnd": 22, "squareMeters": 100, "language": "en"}}
        ),
        encoding="utf-8",
    )
    partial = tmp_path / "draft.yaml"
    partial.write_text(yaml.safe_dump({"square_meters": 320}), encoding="utf-8")
    expected = {"checkInTimeEnd": 22, "squareMeters": 320, "language": "en"}
    mock_endpoint(
        respx_mock,
        "GET",
        f"/listings/{LISTING_ID}",
        steps=[ok(villa(LISTING_ID)), ok(villa(LISTING_ID) | expected)],
    )
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(
        app,
        ["backfill", str(LISTING_ID), str(partial), "--apply"],
        env=cli_env(HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 0, result.output
    assert "squareMeters: None -> 320" in plain(result.stdout)
    assert "checkInTimeEnd: None -> 22" in plain(result.stdout)
    assert sent_body(put) == expected


def test_the_network_secret_is_shown_as_set_and_never_printed(
    respx_mock: respx.MockRouter,
) -> None:
    """A diff scrolls into terminal history and screen shares; the password does not."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/bedTypes", steps=[ok(bed_type_catalog())])
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(villa(LISTING_ID))])

    result = runner.invoke(
        app,
        ["backfill", str(LISTING_ID), str(DRAFT_PATH)],
        env=configured_env(HSCTL_WIFI_PASSWORD="a-network-secret"),
    )

    assert result.exit_code == 0, result.output
    assert "wifiPassword: (unset) -> ***" in plain(result.stdout)
    assert "a-network-secret" not in plain(result.stdout)


def test_a_network_name_is_shown_without_its_password_but_never_written_alone(
    respx_mock: respx.MockRouter,
) -> None:
    """The operator has to see the diff they are being asked to approve.

    The notice is written in the vocabulary the tool uses everywhere else: a write
    that sends nothing is a dry run (CONTEXT.md).
    """
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/bedTypes", steps=[ok(bed_type_catalog())])
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(villa(LISTING_ID))])
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    dry_run = runner.invoke(
        app, ["backfill", str(LISTING_ID), str(DRAFT_PATH)], env=configured_env()
    )
    assert dry_run.exit_code == 0, dry_run.output
    notice = "HSCTL_WIFI_PASSWORD is unset, so wifiPassword is absent from this dry run."
    assert notice in squashed(dry_run.stdout)
    assert "wifiPassword:" not in plain(dry_run.stdout)

    applied = runner.invoke(
        app, ["backfill", str(LISTING_ID), str(DRAFT_PATH), "--apply"], env=configured_env()
    )
    assert applied.exit_code == 2, applied.output
    assert "HSCTL_WIFI_PASSWORD is unset" in squashed(applied.output)
    assert not put.called


BED_ROWS = [
    {"bedTypeId": 1101, "quantity": 1, "bedroomNumber": 1},
    {"bedTypeId": 1101, "quantity": 1, "bedroomNumber": 2},
    {"bedTypeId": 1103, "quantity": 2, "bedroomNumber": 3},
]


def test_a_bed_configuration_the_listing_stored_reads_back_as_stored(
    respx_mock: respx.MockRouter,
) -> None:
    """Hostaway gives every bed row an id of its own; a read-back must see past it."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/bedTypes", steps=[ok(bed_type_catalog())])
    landed = villa(
        LISTING_ID,
        listingBedTypes=[
            {"id": 9100 + index, "listingId": LISTING_ID, **row}
            for index, row in enumerate(BED_ROWS)
        ],
    )
    mock_endpoint(
        respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(villa(LISTING_ID)), ok(landed)]
    )
    put = mock_endpoint(
        respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})]
    )

    result = runner.invoke(
        app,
        ["backfill", str(LISTING_ID), str(DRAFT_PATH), "--apply"],
        env=configured_env(HSCTL_WIFI_PASSWORD="a-network-secret"),
    )

    assert sent_body(put)["listingBedTypes"] == BED_ROWS
    assert "listingBedTypes: stored" in plain(result.stdout)


def test_a_bed_configuration_the_listing_already_carries_is_not_a_change(
    respx_mock: respx.MockRouter,
) -> None:
    """Row ids the listing added are not a difference the operator asked for."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/bedTypes", steps=[ok(bed_type_catalog())])
    settled = villa(
        LISTING_ID,
        listingBedTypes=[
            {"id": 9100 + index, "listingId": LISTING_ID, **row}
            for index, row in enumerate(BED_ROWS)
        ],
    )
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(settled)])

    result = runner.invoke(
        app,
        ["backfill", str(LISTING_ID), str(DRAFT_PATH)],
        env=configured_env(HSCTL_WIFI_PASSWORD="a-network-secret"),
    )

    assert result.exit_code == 0, result.output
    assert "listingBedTypes" not in plain(result.stdout)


def test_export_pushes_the_backfilled_listing_on_to_the_channel(
    respx_mock: respx.MockRouter,
) -> None:
    """A save is not an export: content backfilled here is invisible until it is pushed."""
    mock_access_tokens(respx_mock)
    config = load_config(FULL_CONFIG)
    landed = villa(LISTING_ID) | dict(config.house_defaults)
    mock_endpoint(
        respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(villa(LISTING_ID)), ok(landed)]
    )
    mock_endpoint(respx_mock, "PUT", f"/listings/{LISTING_ID}", steps=[ok({"id": LISTING_ID})])
    published = mock_endpoint(
        respx_mock, "POST", f"/listings/{LISTING_ID}/export/airbnb", steps=[ok({})]
    )

    result = runner.invoke(
        app, ["backfill", str(LISTING_ID), "--apply", "--export"], env=configured_env()
    )

    assert result.exit_code == 0, result.output
    assert "Channel-facing" in plain(result.stdout)
    assert published.called
    assert "Export to airbnb triggered" in plain(result.stdout)


def test_the_markup_warning_names_the_multipliers_that_are_actually_changing(
    respx_mock: respx.MockRouter,
) -> None:
    """A warning that fires on every run is one an operator learns to scroll past."""
    mock_access_tokens(respx_mock)
    config = load_config(FULL_CONFIG)
    settled = villa(LISTING_ID) | config.markups.wire_fields()
    mock_endpoint(respx_mock, "GET", f"/listings/{LISTING_ID}", steps=[ok(settled)])

    result = runner.invoke(app, ["backfill", str(LISTING_ID), "--markups"], env=configured_env())

    assert result.exit_code == 0, result.output
    assert "Channel markups in this change" not in plain(result.stdout)
    assert "language: None -> 'en'" in plain(result.stdout)
