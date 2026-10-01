"""``hsctl create``: a YAML draft, the operator's house defaults, one POST (seam 1).

Every test drives the command as an operator does. A create is the one write that
cannot be taken back or safely repeated, so what these tests pin is not only the
payload but the two moments nothing may be sent: no configuration to merge, and no
``--apply``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from typer.testing import CliRunner, Result

from hostaway_cli.cli import app
from hostaway_mocks import (
    cli_env,
    mock_access_tokens,
    mock_catalogs,
    mock_endpoint,
    ok,
    plain,
    sent_body,
    squashed,
    villas,
)

runner = CliRunner()

FULL_CONFIG = Path(__file__).parent / "fixtures" / "full-config.yaml"
DRAFT_PATH = Path(__file__).parent / "fixtures" / "villa-nira-draft.yaml"

NEW_LISTING_ID = 1006

# The whole POST body the villa draft and the shipped example configuration make,
# written out rather than rebuilt with the builder, so a change in either is a
# failing test rather than a moving target.
EXPECTED_PAYLOAD = {
    # From the example configuration's house_defaults, not from this package.
    "language": "en",
    "allowSameDayBooking": 1,
    "sameDayBookingLeadTime": 12,
    "cancellationPolicyId": 2001,
    "airbnbCancellationPolicyId": 2002,
    "bookingCancellationPolicyId": 2003,
    "vrboCancellationPolicyId": 2004,
    "marriottCancellationPolicyId": 2005,
    "airbnbBookingLeadTime": 5,
    "airbnbBookingLeadTimeAllowRequestToBook": 1,
    "contactName": "Guest",
    "contactSurName": "Services",
    "contactEmail": "stays@example.com",
    "contactLanguage": "English",
    "contactAddress": "Example City",
    # From the draft, with catalog names resolved against the account's catalogs.
    "propertyTypeId": 42,
    "name": "Villa Nira \u2014 clifftop pool villa",
    "externalListingName": "Villa Nira \u2014 clifftop pool villa",
    "internalListingName": "DEMO-NIRA",
    "description": (
        "Villa Nira stands on the clifftop above the bay, four bedrooms wrapped "
        "around a long infinity pool."
    ),
    "houseRules": "No Parties: No parties or events\nQuiet Hours: 10:00 PM to 7:00 AM",
    "country": "Indonesia",
    "countryCode": "ID",
    "state": "Example Province",
    "city": "Example Bay",
    "street": "Jl. Contoh No. 12, Example Bay, Example Province 80999",
    "address": "Jl. Contoh No. 12, Example Bay, Example Province 80999",
    "publicAddress": "Example Bay, Example Province, Indonesia",
    "zipcode": "80999",
    "lat": -8.1234,
    "lng": 115.4321,
    "timeZoneName": "Asia/Makassar",
    "price": 410,
    "currencyCode": "USD",
    "weeklyDiscount": 0.9,
    "monthlyDiscount": 0.8,
    "cleaningFee": 45,
    "refundableDamageDeposit": 200,
    "priceForExtraPerson": 25,
    "guestsIncluded": 6,
    "personCapacity": 8,
    "bedroomsNumber": 3,
    "bedsNumber": 4,
    "bathroomsNumber": 4,
    "roomType": "entire_home",
    "bedType": "real_bed",
    "minNights": 2,
    "maxNights": 90,
    "checkInTimeStart": 14,
    "checkInTimeEnd": 22,
    "checkOutTime": 11,
    "cancellationPolicy": "moderate",
    "instantBookable": 1,
    "listingAmenities": [
        {"amenityId": 1},
        {"amenityId": 3},
        {"amenityId": 2},
        {"amenityId": 4},
    ],
    "listingBedTypes": [
        {"bedTypeId": 1101, "quantity": 1, "bedroomNumber": 1},
        {"bedTypeId": 1101, "quantity": 1, "bedroomNumber": 2},
        {"bedTypeId": 1103, "quantity": 2, "bedroomNumber": 3},
    ],
    "airbnbName": "Villa Nira \u2014 clifftop pool villa",
    "airbnbSummary": (
        "Villa Nira stands on the clifftop above the bay, four bedrooms wrapped "
        "around a long infinity pool."
    ),
    "airbnbSpace": (
        "\U0001f6cf\ufe0f SLEEPING\n"
        "Bedroom one opens straight onto the pool deck and has its own ensuite, an "
        "outdoor shower and a view down the cliff.\n"
        "\n"
        "Bedroom one: king bed, ensuite, pool access\n"
        "Bedroom two: king bed, ensuite"
    ),
    "airbnbAccess": (
        "1. The gate code is in your arrival message, and the keypad sits on the "
        "left as you face the gate.\n"
        "2. The house key hangs in the lockbox by the front door."
    ),
    "airbnbInteraction": (
        "The host lives ten minutes away and answers messages all day; nobody will "
        "call in unless you ask."
    ),
    "airbnbNeighborhoodOverview": (
        "A quiet lane of family compounds, with the surf break and two warungs a "
        "short walk downhill."
    ),
    "airbnbTransit": (
        "The airport is fifty minutes by car outside peak hours, and we can arrange "
        "the pickup for you."
    ),
    "airbnbNotes": (
        "The cliff path is unlit after dark, so bring a torch or use the stairs by "
        "the pool instead."
    ),
    "customFieldValues": [{"customFieldId": 3301, "value": "https://maps.example.com/villa-nira"}],
}


def configured_env(**overrides: str | None) -> dict[str, str | None]:
    """The CLI environment, pointed at the shipped example configuration."""
    return cli_env(HSCTL_CONFIG=str(FULL_CONFIG), **overrides)


def previewed_payload(stdout: str) -> dict[str, object]:
    """The JSON payload the command printed, read back off its own output."""
    body, _ = json.JSONDecoder().raw_decode(stdout[stdout.index("{") :])
    assert isinstance(body, dict)
    return body


def created(listing_id: int = NEW_LISTING_ID) -> httpx.Response:
    """Hostaway's answer to a POST it accepted: the id of the listing it made."""
    return httpx.Response(201, json={"status": "success", "result": {"id": listing_id}})


def uncaught(result: Result) -> BaseException | None:
    """The exception that escaped the command, if one did.

    ``CliRunner`` catches it and writes no traceback into ``output``, so asserting
    that the word Traceback is absent proves nothing — a crash and a refusal read the
    same there. A refusal leaves through ``SystemExit``; anything else is the
    traceback the operator would have got at their own terminal.
    """
    error = result.exception
    return None if error is None or isinstance(error, SystemExit) else error


# Shapes a draft written by hand plausibly takes when a key is typed as the wrong kind
# of thing: an address written as the one line it is on an envelope, a bed
# configuration written as the list of bed names it reads like, a price with its
# currency inside it, and ``none`` written where YAML wants nothing at all.
# The third column is what the refusal has to name: the key the operator has to go
# and fix, down to the row of it when the key is a list.
MISTYPED_DRAFT_KEYS = [
    ("address", "Jl. Contoh No. 12, Example Bay", "address must be"),
    ("bed_config", "king bed", "bed_config must be"),
    ("bed_config", ["king bed", "twin bed"], "bed_config[0] must be"),
    ("check_in", "2pm", "check_in must be"),
    ("pricing", "410 usd", "pricing must be"),
    ("fees", "none", "fees must be"),
    ("house_rules", ["no parties"], "house_rules must be"),
]


def test_create_without_a_configuration_refuses_and_sends_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    """House defaults are the operator's; hsctl has none to fall back on (docs/adr/0002)."""
    tokens = mock_access_tokens(respx_mock)
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created(1006)])

    result = runner.invoke(app, ["create", str(DRAFT_PATH)], env=cli_env())

    assert result.exit_code == 2, result.output
    assert "HSCTL_CONFIG is not set" in plain(result.stderr)
    assert not post.called
    assert not tokens.called


def test_create_with_a_configuration_path_that_names_no_file_refuses(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    tokens = mock_access_tokens(respx_mock)
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])
    absent = tmp_path / "config.yaml"

    result = runner.invoke(app, ["create", str(DRAFT_PATH)], env=cli_env(HSCTL_CONFIG=str(absent)))

    assert result.exit_code == 2, result.output
    assert f"Configuration file not found: {absent}" in plain(result.stderr)
    assert "config.example.yaml" in plain(result.stderr)
    assert not post.called
    assert not tokens.called


def test_create_previews_the_whole_payload_and_sends_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    """House defaults merged, catalog names resolved, and the POST never made."""
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])

    result = runner.invoke(app, ["create", str(DRAFT_PATH)], env=configured_env())

    assert result.exit_code == 0, result.output
    assert previewed_payload(result.stdout) == EXPECTED_PAYLOAD
    assert "DRY RUN" in plain(result.stdout)
    assert not post.called


def stored(**overrides: object) -> dict[str, object]:
    """The listing Hostaway hands back after storing the whole payload.

    Each sub-resource row comes back with an ID and a back-reference the create
    never sent, which is what a read-back has to see past.
    """
    listing: dict[str, object] = {"id": NEW_LISTING_ID, **EXPECTED_PAYLOAD}
    for field, first_row_id in (
        ("listingAmenities", 9000),
        ("listingBedTypes", 9100),
        ("customFieldValues", 9200),
    ):
        rows = EXPECTED_PAYLOAD[field]
        assert isinstance(rows, list)
        listing[field] = [
            {"id": first_row_id + index, "listingId": NEW_LISTING_ID, **row}
            for index, row in enumerate(rows)
        ]
    listing.update(overrides)
    return listing


def test_apply_posts_the_payload_once_and_reads_the_new_listing_back(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])
    mock_endpoint(respx_mock, "GET", f"/listings/{NEW_LISTING_ID}", steps=[ok(stored())])

    result = runner.invoke(
        app, ["create", str(DRAFT_PATH), "--apply", "--allow-protected"], env=configured_env()
    )

    assert result.exit_code == 0, result.output
    assert sent_body(post) == EXPECTED_PAYLOAD
    assert f"Created listing {NEW_LISTING_ID}." in plain(result.stdout)
    assert "listingAmenities: stored" in plain(result.stdout)
    assert "price: stored" in plain(result.stdout)
    assert "Verified." in plain(result.stdout)
    assert "DRY RUN" not in plain(result.stdout)


def test_a_field_the_new_listing_did_not_keep_is_named_and_the_command_fails(
    respx_mock: respx.MockRouter,
) -> None:
    """Hostaway answers success and stores only part of a create; the read-back says so."""
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])
    mock_endpoint(
        respx_mock,
        "GET",
        f"/listings/{NEW_LISTING_ID}",
        # The account-wide policy id landed; the three channel ones were discarded.
        steps=[
            ok(
                stored(
                    airbnbCancellationPolicyId=None,
                    bookingCancellationPolicyId=None,
                    vrboCancellationPolicyId=None,
                )
            )
        ],
    )

    result = runner.invoke(
        app, ["create", str(DRAFT_PATH), "--apply", "--allow-protected"], env=configured_env()
    )

    assert result.exit_code == 1, result.output
    assert "cancellationPolicyId: stored" in plain(result.stdout)
    assert "airbnbCancellationPolicyId: dropped" in plain(result.stdout)
    assert "Dropped by Hostaway: airbnbCancellationPolicyId, " in plain(result.stdout)


def test_a_name_the_account_already_carries_is_refused_before_anything_is_sent(
    respx_mock: respx.MockRouter,
) -> None:
    """A create cannot be undone, and two listings of one name read alike ever after."""
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    twin = villas()[0] | {"name": "Villa Nira — clifftop pool villa"}
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok([twin], count=1)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])

    result = runner.invoke(app, ["create", str(DRAFT_PATH), "--apply"], env=configured_env())

    assert result.exit_code != 0, result.output
    assert "already exists" in squashed(result.output)
    assert not post.called


def test_a_catalog_name_the_account_does_not_publish_is_refused(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """An unknown amenity is refused rather than dropped: a create sends the whole set."""
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])
    draft = yaml.safe_load(DRAFT_PATH.read_text(encoding="utf-8"))
    draft["hostaway_amenities"] = ["Wifi", "Helipad"]
    unknown = tmp_path / "draft.yaml"
    unknown.write_text(yaml.safe_dump(draft), encoding="utf-8")

    result = runner.invoke(app, ["create", str(unknown), "--apply"], env=configured_env())

    assert result.exit_code != 0, result.output
    assert "Unknown amenity: 'Helipad'" in squashed(result.output)
    assert not post.called


def test_a_draft_hostaway_could_not_activate_is_refused_before_the_post(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])
    draft = yaml.safe_load(DRAFT_PATH.read_text(encoding="utf-8"))
    del draft["pricing"]
    priceless = tmp_path / "draft.yaml"
    priceless.write_text(yaml.safe_dump(draft), encoding="utf-8")

    result = runner.invoke(app, ["create", str(priceless), "--apply"], env=configured_env())

    assert result.exit_code != 0, result.output
    assert "price, currencyCode" in squashed(result.output)
    assert not post.called


def test_a_draft_without_a_title_costs_no_hostaway_call(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    tokens = mock_access_tokens(respx_mock)
    draft = yaml.safe_load(DRAFT_PATH.read_text(encoding="utf-8"))
    del draft["title"]
    typeless = tmp_path / "draft.yaml"
    typeless.write_text(yaml.safe_dump(draft), encoding="utf-8")

    result = runner.invoke(app, ["create", str(typeless)], env=configured_env())

    assert result.exit_code == 2, result.output
    assert "has no title" in squashed(result.output)
    assert not tokens.called


def test_a_draft_file_that_is_not_there_is_reported_not_raised(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    tokens = mock_access_tokens(respx_mock)

    result = runner.invoke(app, ["create", str(tmp_path / "absent.yaml")], env=configured_env())

    assert result.exit_code == 2, result.output
    assert "does not exist" in squashed(result.output)
    assert uncaught(result) is None
    assert not tokens.called


def test_a_create_carrying_money_fields_is_refused_without_the_protected_flag(
    respx_mock: respx.MockRouter,
) -> None:
    """The gate reads the change, never the command name (docs/adr/0001).

    Every create payload carries a price, a currency, a cleaning fee and a deposit, so
    a create is a protected write like any other. It is also the one write that cannot
    be taken back, which is the last write that should be exempt from the second flag.
    """
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])

    result = runner.invoke(app, ["create", str(DRAFT_PATH), "--apply"], env=configured_env())

    assert result.exit_code == 3, result.output
    assert (
        "Protected fields in this change: price, currency, cleaning fee, damage deposit"
        in plain(result.stdout)
    )
    assert "--allow-protected" in squashed(result.output)
    assert not post.called


def test_the_money_fields_are_named_on_a_dry_run_that_needs_no_flag_at_all(
    respx_mock: respx.MockRouter,
) -> None:
    """Nothing is sent without --apply, so a dry run asks for no second flag."""
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])

    result = runner.invoke(app, ["create", str(DRAFT_PATH)], env=configured_env())

    assert result.exit_code == 0, result.output
    assert "Protected fields in this change: price, currency" in plain(result.stdout)
    assert "DRY RUN" in plain(result.stdout)
    assert not post.called


def test_a_bed_with_no_room_id_is_refused_rather_than_raised(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """A draft an operator can plausibly write must not reach them as a traceback.

    Every bed carries the room it stands in; without it the payload builder refuses
    rather than guessing, and that refusal is the operator's, not Python's.
    """
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])
    draft = yaml.safe_load(DRAFT_PATH.read_text(encoding="utf-8"))
    for bed in draft["bed_config"]:
        del bed["room_id"]
    roomless = tmp_path / "draft.yaml"
    roomless.write_text(yaml.safe_dump(draft), encoding="utf-8")

    result = runner.invoke(
        app, ["create", str(roomless), "--apply", "--allow-protected"], env=configured_env()
    )

    assert result.exit_code == 2, result.output
    assert uncaught(result) is None
    assert "bed_config[0] has no room_id" in squashed(result.output)
    assert not post.called


def test_a_check_in_time_that_is_not_an_hour_is_refused_rather_than_raised(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """``2pm`` is a thing an operator types; a traceback is not a thing they can act on."""
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=5)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])
    draft = yaml.safe_load(DRAFT_PATH.read_text(encoding="utf-8"))
    draft["check_in"]["earliest"] = "2pm"
    vague = tmp_path / "draft.yaml"
    vague.write_text(yaml.safe_dump(draft), encoding="utf-8")

    result = runner.invoke(
        app, ["create", str(vague), "--apply", "--allow-protected"], env=configured_env()
    )

    assert result.exit_code == 2, result.output
    assert uncaught(result) is None
    assert "Invalid check_in.earliest '2pm'" in squashed(result.output)
    assert not post.called


def test_an_account_the_walk_could_not_read_whole_stops_the_create(
    respx_mock: respx.MockRouter,
) -> None:
    """A page that skips listings cannot prove the name is free, so nothing is sent."""
    mock_access_tokens(respx_mock)
    mock_catalogs(respx_mock)
    # Five listings offered as the first page of five hundred: the rest are unread.
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok(villas(), count=500)])
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])

    result = runner.invoke(
        app, ["create", str(DRAFT_PATH), "--apply", "--allow-protected"], env=configured_env()
    )

    assert result.exit_code == 1, result.output
    assert (
        "Hostaway did not answer a page this walk can trust (pagination_page_incomplete)"
        in squashed(result.output)
    )
    assert "cannot be ruled out. Nothing sent." in squashed(result.output)
    assert not post.called


@pytest.mark.parametrize(("key", "written", "named"), MISTYPED_DRAFT_KEYS)
def test_a_draft_key_written_as_the_wrong_kind_of_thing_is_refused_before_any_call(
    respx_mock: respx.MockRouter, tmp_path: Path, key: str, written: object, named: str
) -> None:
    """A draft an operator can plausibly write must not reach them as a traceback.

    The shape of a draft is read before a session exists, so a key written as the
    wrong kind of thing costs no Hostaway call at all — not even the catalog reads
    the create makes before it builds anything.
    """
    tokens = mock_access_tokens(respx_mock)
    post = mock_endpoint(respx_mock, "POST", "/listings", steps=[created()])
    draft = yaml.safe_load(DRAFT_PATH.read_text(encoding="utf-8"))
    draft[key] = written
    mistyped = tmp_path / "draft.yaml"
    mistyped.write_text(yaml.safe_dump(draft), encoding="utf-8")

    result = runner.invoke(
        app, ["create", str(mistyped), "--apply", "--allow-protected"], env=configured_env()
    )

    assert result.exit_code == 2, result.output
    assert uncaught(result) is None
    assert named in squashed(result.output)
    assert not tokens.called
    assert not post.called
