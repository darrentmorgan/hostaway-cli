"""The payload builders, driven by a configuration and a synthetic villa draft.

Seam: the two public builders as plain functions. House defaults, fill-only-if-empty
fields and markups arrive as a ``Configuration`` argument — the module carries none of
its own, so a test that swaps the configuration swaps every house default in the payload.

Expected prose is written out in full rather than recomputed with the builder's own
unwrapping, so a change in that logic is a failing test rather than a moving target.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from hostaway_cli.config import Configuration, load_config
from hostaway_cli.listing_payload import (
    DRAFT_TO_WIRE_DISPOSITION,
    build_backfill_payload,
    build_create_payload,
    missing_for_complete,
)

FULL_CONFIG = Path(__file__).parent / "fixtures" / "full-config.yaml"
DRAFT_PATH = Path(__file__).parent / "fixtures" / "villa-nira-draft.yaml"
BED_TYPES = {"king": 1101, "twin": 1103}
AMENITY_IDS = [3, 7, 12]
MAP_LINK_FIELD_ID = 3301
PROPERTY_TYPE_ID = 42

SUMMARY = (
    "Villa Nira stands on the clifftop above the bay, four bedrooms wrapped around "
    "a long infinity pool."
)
SPACE = (
    "🛏️ SLEEPING\n"
    "Bedroom one opens straight onto the pool deck and has its own ensuite, an "
    "outdoor shower and a view down the cliff.\n"
    "\n"
    "Bedroom one: king bed, ensuite, pool access\n"
    "Bedroom two: king bed, ensuite"
)
ACCESS = (
    "1. The gate code is in your arrival message, and the keypad sits on the left "
    "as you face the gate.\n"
    "2. The house key hangs in the lockbox by the front door."
)
INTERACTION = (
    "The host lives ten minutes away and answers messages all day; nobody will call "
    "in unless you ask."
)
NEIGHBOURHOOD = (
    "A quiet lane of family compounds, with the surf break and two warungs a short walk downhill."
)
TRANSIT = (
    "The airport is fifty minutes by car outside peak hours, and we can arrange the pickup for you."
)
NOTES = (
    "The cliff path is unlit after dark, so bring a torch or use the stairs by the pool instead."
)


def draft() -> dict[str, Any]:
    return dict(yaml.safe_load(DRAFT_PATH.read_text(encoding="utf-8")))


def config() -> Configuration:
    return load_config(FULL_CONFIG)


def create(
    source: dict[str, Any] | None = None,
    configuration: Configuration | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    return build_create_payload(
        draft() if source is None else source,
        config() if configuration is None else configuration,
        **{
            "amenity_ids": AMENITY_IDS,
            "bed_types": BED_TYPES,
            "map_link_custom_field_id": MAP_LINK_FIELD_ID,
            "property_type_id": PROPERTY_TYPE_ID,
            **overrides,
        },
    )


def backfill(
    source: dict[str, Any] | None = None,
    configuration: Configuration | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    return build_backfill_payload(
        draft() if source is None else source,
        config() if configuration is None else configuration,
        **{"bed_types": BED_TYPES, **overrides},
    )


def test_a_draft_and_a_configuration_make_one_exact_create_payload() -> None:
    assert create() == {
        # From the configuration's house_defaults, not from this package.
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
        # From the draft.
        "propertyTypeId": 42,
        "name": "Villa Nira — clifftop pool villa",
        "externalListingName": "Villa Nira — clifftop pool villa",
        "internalListingName": "DEMO-NIRA",
        "description": SUMMARY,
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
        "listingAmenities": [{"amenityId": 3}, {"amenityId": 7}, {"amenityId": 12}],
        "listingBedTypes": [
            {"bedTypeId": 1101, "quantity": 1, "bedroomNumber": 1},
            {"bedTypeId": 1101, "quantity": 1, "bedroomNumber": 2},
            {"bedTypeId": 1103, "quantity": 2, "bedroomNumber": 3},
        ],
        "airbnbName": "Villa Nira — clifftop pool villa",
        "airbnbSummary": SUMMARY,
        "airbnbSpace": SPACE,
        "airbnbAccess": ACCESS,
        "airbnbInteraction": INTERACTION,
        "airbnbNeighborhoodOverview": NEIGHBOURHOOD,
        "airbnbTransit": TRANSIT,
        "airbnbNotes": NOTES,
        "customFieldValues": [
            {"customFieldId": 3301, "value": "https://maps.example.com/villa-nira"}
        ],
    }
    assert missing_for_complete(create()) == []


def test_the_house_defaults_come_from_the_configuration_and_nowhere_else() -> None:
    """Swap the configuration and every house default in the payload swaps with it."""
    other = Configuration(house_defaults={"language": "fr", "contactName": "Reception"})

    payload = create(configuration=other)

    assert payload["language"] == "fr"
    assert payload["contactName"] == "Reception"
    assert "cancellationPolicyId" not in payload
    assert "contactEmail" not in payload


def test_a_configuration_with_no_house_defaults_adds_nothing_to_the_draft() -> None:
    bare = Configuration(house_defaults={})

    payload = create(configuration=bare)

    assert set(payload) == set(create()) - set(config().house_defaults)


def test_a_house_default_never_overwrites_what_the_draft_says() -> None:
    """The draft is property fact; a house default only says what the account prefers."""
    loud = Configuration(
        house_defaults={
            "minNights": 30,
            "cancellationPolicy": "strict",
            "maxNights": 365,
            "roomType": "private_room",
        }
    )

    payload = create(configuration=loud)

    assert payload["minNights"] == 2
    assert payload["cancellationPolicy"] == "moderate"
    assert payload["maxNights"] == 90
    assert payload["roomType"] == "entire_home"


def test_a_configured_house_default_beats_the_builders_last_resort() -> None:
    """Hostaway needs these three fields; only the draft and the operator may say what."""
    source = draft()
    del source["max_stay"]
    del source["room_type"]
    configured = Configuration(
        house_defaults={"maxNights": 365, "roomType": "private_room", "bedType": "futon"}
    )

    payload = create(source, configuration=configured)

    assert payload["maxNights"] == 365
    assert payload["roomType"] == "private_room"
    assert payload["bedType"] == "futon"


def test_the_last_resort_wire_values_apply_only_when_nobody_else_speaks() -> None:
    """What is left when the draft is silent and the configuration names nothing."""
    source = draft()
    del source["max_stay"]
    del source["room_type"]

    payload = create(source, configuration=Configuration(house_defaults={}))

    assert "maxNights" not in payload
    assert "roomType" not in payload
    assert payload["bedType"] == "real_bed"


def test_a_house_default_fills_a_wire_field_the_draft_leaves_empty() -> None:
    """An absent draft key is silence, not an instruction to drop the configured value."""
    source = draft()
    del source["min_stay"]

    payload = create(source, configuration=Configuration(house_defaults={"minNights": 3}))

    assert payload["minNights"] == 3


def test_the_map_link_custom_field_is_only_written_when_its_id_is_known() -> None:
    assert "customFieldValues" not in create(map_link_custom_field_id=None)


def test_a_draft_with_no_map_link_writes_no_custom_field() -> None:
    source = draft()
    del source["address"]["google_map_link"]

    assert "customFieldValues" not in create(source)


def test_two_bed_types_in_one_room_share_a_bedroom_number() -> None:
    source = draft()
    source["bed_config"] = [
        {"room_id": "bedroom_1", "bed_type": "king", "quantity": 1},
        {"room_id": "bedroom_1", "bed_type": "twin", "quantity": 1},
        {"room_id": "bedroom_2", "bed_type": "king", "quantity": 1},
    ]

    assert [row["bedroomNumber"] for row in create(source)["listingBedTypes"]] == [1, 1, 2]
    assert create(source)["bedroomsNumber"] == 2


def test_a_bed_with_no_room_id_fails_loud_instead_of_guessing() -> None:
    """Hostaway files a row with no bedroomNumber into bedroom 1, silently."""
    source = draft()
    source["bed_config"] = [{"bed_type": "king", "quantity": 1}]

    with pytest.raises(ValueError, match="no room_id"):
        create(source)
    with pytest.raises(ValueError, match="no room_id"):
        backfill(source)


@pytest.mark.parametrize("value", ["", "noon", "24:00", "14:60", 24, -1, True])
def test_a_malformed_check_in_hour_is_rejected(value: object) -> None:
    source = draft()
    source["check_in"]["earliest"] = value

    with pytest.raises(ValueError, match="expected an integer from 0 to 23"):
        create(source)


def test_the_disposition_table_accounts_for_every_key_in_a_draft() -> None:
    assert set(DRAFT_TO_WIRE_DISPOSITION) == set(draft())


def test_backfill_carries_the_configured_house_defaults_and_the_property_detail() -> None:
    fields = backfill(wifi_password="s3cret")

    assert fields["language"] == "en"
    assert fields["cancellationPolicyId"] == 2001
    assert fields["contactEmail"] == "stays@example.com"
    assert fields["checkInTimeEnd"] == 22
    assert fields["homeawayPropertyHeadline"] == "Villa Nira — clifftop pool villa"
    assert fields["squareMeters"] == 320
    assert fields["wifiUsername"] == "NIRA-GUEST"
    assert fields["wifiPassword"] == "s3cret"


def test_backfill_omits_the_network_secret_when_it_was_not_supplied() -> None:
    """A blank secret must be absent, never an empty string written over a good one."""
    assert "wifiPassword" not in backfill()


def test_backfill_never_carries_an_amount_and_omits_markups_by_default() -> None:
    fields = backfill(wifi_password="s3cret")

    assert not {
        "price",
        "currencyCode",
        "cleaningFee",
        "refundableDamageDeposit",
        "pmCommission",
    } & set(fields)
    assert not [key for key in fields if key.endswith("Markup")]


def test_backfill_adds_the_configured_markups_only_when_asked() -> None:
    fields = backfill(markups=True)

    assert fields["airbnbOfficialListingMarkup"] == 1.2
    assert fields["bookingEngineMarkup"] == 1.05
    assert fields["homeawayApiMarkup"] == 1.2
    assert "marriottListingMarkup" not in fields
    assert not {"price", "cleaningFee", "pmCommission"} & set(fields)


def test_a_configuration_with_no_markups_has_none_to_add() -> None:
    silent = Configuration(house_defaults={"language": "en"})

    assert not [key for key in backfill(configuration=silent, markups=True) if "Markup" in key]


def test_a_create_payload_carries_no_markup_at_all() -> None:
    """Markups are a separate, money-adjacent act; creation never rides along."""
    assert not [key for key in create() if "Markup" in key]


def test_missing_for_complete_names_what_hostaway_needs_but_keeps_a_zero_fee() -> None:
    good = {
        "name": "Villa Nira",
        "externalListingName": "Villa Nira",
        "address": "Jl. Contoh No. 12",
        "price": 410,
        "currencyCode": "USD",
        "guestsIncluded": 6,
        "priceForExtraPerson": 0,
    }
    assert missing_for_complete(good) == []
    for field, value in (
        ("name", None),
        ("externalListingName", ""),
        ("address", "   "),
        ("price", "410"),
        ("price", 0),
        ("currencyCode", 3),
        ("guestsIncluded", 1.5),
        ("priceForExtraPerson", None),
    ):
        assert field in missing_for_complete(good | {field: value})


def test_a_draft_with_no_extra_guest_fee_includes_every_guest() -> None:
    source = draft()
    source["fees"] = {"cleaning_fee": 45}

    payload = create(source)

    assert payload["guestsIncluded"] == 8
    assert payload["priceForExtraPerson"] == 0


@pytest.mark.parametrize(
    "text",
    [
        # Bulleted with no space after the dash, as operators really write them.
        "BEDROOMS\n-King beds in all three rooms, with premium linens\n-Blackout curtains",
        # A header below prose is not the prose's continuation, however wide the prose ran.
        "The fully equipped kitchen has everything you need for longer stays or meals.\n"
        "KITCHEN ESSENTIALS",
        # A list written without bullets: every line is short, so none was wrapped.
        "Check-in: 2:00 PM\nCheck-out: 11:00 AM\nDaily housekeeping available",
        # Far past any wrap column, so the line was never wrapped and the next one is new.
        "Villa Nira is a four-bedroom clifftop villa for groups of up to eight, with a "
        "private infinity pool, air conditioning throughout, fast internet and four "
        "ensuite bathrooms.\n"
        "The whole villa is yours, with nothing shared with other guests.",
    ],
)
def test_structure_the_author_meant_survives_unwrapping(text: str) -> None:
    source = draft()
    source["summary"] = text

    assert create(source)["description"] == text


def test_house_rules_keep_one_rule_per_line() -> None:
    """Folding rules into a run-on paragraph is exactly what a guest must not get."""
    assert create()["houseRules"].count("\n") == len(draft()["house_rules"]) - 1


def test_backfill_sends_no_bed_configuration_when_the_draft_describes_none() -> None:
    """``listingBedTypes`` is replace-semantics: an empty array deletes every bed."""
    source = draft()
    del source["bed_config"]

    assert "listingBedTypes" not in backfill(source)


def test_backfill_keeps_a_house_default_the_draft_is_silent_about() -> None:
    """A draft that says nothing about a field is not an instruction to drop it.

    Several house-default wire fields are ones a draft can also name. Stacking a
    silent draft over the operator's file would erase exactly the values a backfill
    exists to write.
    """
    configured = Configuration(
        house_defaults={"checkInTimeEnd": 22, "wifiUsername": "HOUSE-NET", "squareMeters": 100}
    )

    assert backfill({}, configuration=configured) == {
        "checkInTimeEnd": 22,
        "wifiUsername": "HOUSE-NET",
        "squareMeters": 100,
    }


def test_a_draft_wins_over_the_house_default_naming_the_same_wire_field() -> None:
    """Where both speak, the property's own fact beats the account-wide convention."""
    configured = Configuration(house_defaults={"squareMeters": 100, "checkInTimeEnd": 20})

    fields = backfill(configuration=configured)

    assert fields["squareMeters"] == 320
    assert fields["checkInTimeEnd"] == 22


def test_internal_name_is_the_property_name_without_a_template() -> None:
    payload = create(draft(), configuration=Configuration(house_defaults={}))

    assert payload["internalListingName"] == draft()["property_name"]


def test_internal_name_template_keeps_the_portfolio_prefix_available() -> None:
    configured = Configuration(
        house_defaults={}, listing_name_template="{portfolio}-{property_slug}"
    )

    assert create(draft(), configuration=configured)["internalListingName"] == "DEMO-NIRA"


def test_an_unknown_template_field_is_refused() -> None:
    configured = Configuration(house_defaults={}, listing_name_template="{nope}")

    with pytest.raises(ValueError, match="listing_name_template"):
        create(draft(), configuration=configured)


def test_property_type_and_amenities_are_omitted_when_absent() -> None:
    payload = create(draft(), amenity_ids=[], property_type_id=None)

    assert "propertyTypeId" not in payload
    assert "listingAmenities" not in payload
