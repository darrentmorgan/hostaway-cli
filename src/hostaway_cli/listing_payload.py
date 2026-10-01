"""Build Hostaway listing payloads from a listing draft and an operator's configuration.

House defaults, fill-only-if-empty fields and markups arrive as a
:class:`~hostaway_cli.config.Configuration`. This module holds no house defaults of its
own — only the last-resort wire values in ``_WIRE_FALLBACKS``, which lose to both the
draft and the configuration — and a caller without a configuration cannot build a
payload at all (docs/adr/0002).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any, TypeGuard

from hostaway_cli.config import Configuration

# Every top-level draft key is accounted for here. Values name the wire field(s) the
# key reaches, or state why the value stays local to the draft.
DRAFT_TO_WIRE_DISPOSITION = {
    "property_name": "derived: internalListingName",
    "portfolio": "available to listing_name_template as {portfolio}",
    "title": "mapped: name, externalListingName, airbnbName",
    "summary": "mapped: description, airbnbSummary",
    "the_space": "derived: airbnbSpace",
    "inventory_by_room": "derived: airbnbSpace",
    "access": "mapped: airbnbAccess",
    "interaction": "mapped: airbnbInteraction",
    "neighbourhood": "mapped: airbnbNeighborhoodOverview",
    "transit": "mapped: airbnbTransit",
    "other_things_to_note": "mapped: airbnbNotes",
    "max_guests": "mapped: personCapacity; derived: guestsIncluded when no extra fee",
    "min_stay": "mapped: minNights",
    "max_stay": "mapped: maxNights",
    "room_type": "mapped: roomType",
    "property_type": "local: the caller resolves this name to propertyTypeId",
    "cancellation_policy": "mapped: cancellationPolicy",
    "weekly_discount": "mapped: weeklyDiscount",
    "monthly_discount": "mapped: monthlyDiscount",
    "instant_bookable": "mapped: instantBookable",
    "bed_config": "derived: bedroomsNumber, bedsNumber, listingBedTypes",
    "bathroom_count": "mapped: bathroomsNumber",
    "square_meters": "backfill: squareMeters",
    "wifi_ssid": "backfill: wifiUsername",
    "amenities_by_room": "local",
    "hostaway_amenities": "local: the caller resolves these names to listingAmenities ids",
    "map_link_custom_field": (
        "local: the caller resolves this name to the customFieldValues id "
        "carrying address.google_map_link"
    ),
    "house_rules": "mapped: houseRules",
    "fees": "mapped: cleaningFee, refundableDamageDeposit, guestsIncluded, priceForExtraPerson",
    "check_in": "mapped: checkInTimeStart, checkInTimeEnd, checkOutTime",
    "pricing": "mapped: price, currencyCode; local: floor_price",
    "address": (
        "mapped: country, countryCode, state, city, street, address, publicAddress, "
        "zipcode, lat, lng, timeZoneName, customFieldValues"
    ),
}

# How far below a paragraph's own widest line a wrapped line may fall. A wrapper breaks
# before the next word, so the shortfall is one word. Measured against the paragraph
# rather than a fixed column: drafts are not all wrapped at the same width.
_WRAP_SLACK = 20

# A hard wrap also bounds a line absolutely: too short and it is a list the author wrote
# without bullets (`Check-in: 2:00 PM`), too long and it was never wrapped at all — a whole
# paragraph on one line, with the next line a new paragraph rather than its continuation.
_WRAP_MIN = 45
_WRAP_MAX = 120

# A list item starts its own line however long the item above it ran: a bullet, or a
# numbered step such as the "1." / "2." of a check-in instruction. The space after a
# bullet is optional — operators do write `-King-sized beds` with none.
_LIST_ITEM = re.compile(r"^([-*•]\s?|\d+[.)]\s)")

# Wire fields carrying guest-facing prose. A YAML draft is hard-wrapped at ~80 columns
# for readability, and Hostaway stores those newlines verbatim and ships them to every
# channel — the listing reads as ragged half-lines. Unwrapped on the way out.
# houseRules is NOT here: rules are emitted one per line on purpose, and folding those
# into a run-on paragraph is exactly what a guest should not get.
_PROSE_FIELDS = frozenset(
    {
        "description",
        "airbnbSummary",
        "airbnbSpace",
        "airbnbAccess",
        "airbnbInteraction",
        "airbnbNeighborhoodOverview",
        "airbnbTransit",
        "airbnbNotes",
    }
)

# NOTE: this completeness rule (including guestsIncluded and priceForExtraPerson) is
# this tool's own opinion of a listing ready to activate. It has not been verified
# against Hostaway's API. Supply the values in the draft: fees.extra_guest_after
# (guestsIncluded, defaulting to max_guests) and fees.extra_guest_fee
# (priceForExtraPerson, defaulting to 0).
_COMPLETE_FIELDS = (
    "name",
    "externalListingName",
    "address",
    "price",
    "currencyCode",
    "guestsIncluded",
    "priceForExtraPerson",
)

# The wire field kept as a last-resort value on a create. Unverified whether Hostaway
# requires bedType, so it stays; roomType and maxNights are no longer guessed and are
# sent only when the draft (room_type, max_stay) or the house defaults name them. It
# loses to the draft AND to the operator's house defaults (docs/adr/0002).
_WIRE_FALLBACKS = {
    "bedType": "real_bed",
}


def build_create_payload(
    draft: Mapping[str, Any],
    config: Configuration,
    *,
    amenity_ids: Sequence[int],
    bed_types: Mapping[str, int],
    property_type_id: int | None = None,
    map_link_custom_field_id: int | None = None,
) -> dict[str, Any]:
    """Map a listing draft to a Hostaway POST /listings payload.

    Catalog ids are resolved by the caller against the current account. The house
    defaults come from ``config`` and lose to anything the draft actually says, while
    beating the last-resort wire values in ``_WIRE_FALLBACKS``, which are all this
    module holds. Values are omitted only when ``None``; zero stays a money value.
    """
    address = draft.get("address") or {}
    fees = draft.get("fees") or {}
    check_in = draft.get("check_in") or {}
    pricing = draft.get("pricing") or {}
    bed_config = draft.get("bed_config") or []

    title = draft.get("title")
    max_guests = draft.get("max_guests")
    extra_guest_after = fees.get("extra_guest_after")
    extra_guest_fee = fees.get("extra_guest_fee")
    guests_included = max_guests if extra_guest_after is None else extra_guest_after
    price_for_extra_person = 0 if extra_guest_fee is None else extra_guest_fee

    bed_rows = _listing_bed_types(bed_config, bed_types)

    payload: dict[str, Any] = {
        "propertyTypeId": property_type_id,
        "name": title,
        "externalListingName": title,
        "internalListingName": _internal_listing_name(draft, config),
        "description": draft.get("summary"),
        "houseRules": _render_house_rules(draft.get("house_rules") or {}),
        "country": address.get("country"),
        "countryCode": _upper(address.get("country_code") or address.get("countryCode")),
        "state": address.get("state"),
        "city": address.get("city"),
        "street": address.get("street"),
        # street already carries city/state/postcode in this draft; do not join it again.
        "address": address.get("street"),
        "publicAddress": _join_nonempty(
            address.get("city"), address.get("state"), address.get("country")
        ),
        "zipcode": address.get("zip") or address.get("postcode"),
        "lat": address.get("lat"),
        "lng": address.get("lng"),
        "timeZoneName": address.get("timezone"),
        "price": pricing.get("base_price"),
        "currencyCode": _upper(pricing.get("currency")),
        "weeklyDiscount": draft.get("weekly_discount"),
        "monthlyDiscount": draft.get("monthly_discount"),
        "cleaningFee": fees.get("cleaning_fee"),
        "refundableDamageDeposit": fees.get("security_deposit"),
        "priceForExtraPerson": price_for_extra_person,
        "guestsIncluded": guests_included,
        "personCapacity": max_guests,
        # Count ROOMS, not rows — two bed types in one room is still one bedroom.
        "bedroomsNumber": len({row["bedroomNumber"] for row in bed_rows}),
        "bedsNumber": sum(int(bed.get("quantity", 1)) for bed in bed_config),
        "bathroomsNumber": draft.get("bathroom_count"),
        "roomType": draft.get("room_type"),
        "minNights": draft.get("min_stay"),
        "maxNights": draft.get("max_stay"),
        "checkInTimeStart": _hour_int(check_in.get("earliest"), key="check_in.earliest"),
        "checkInTimeEnd": _hour_int(check_in.get("latest"), key="check_in.latest"),
        "checkOutTime": _hour_int(check_in.get("check_out"), key="check_in.check_out"),
        "cancellationPolicy": draft.get("cancellation_policy"),
        "instantBookable": _wire_bool(draft.get("instant_bookable")),
        "listingAmenities": [{"amenityId": int(amenity_id)} for amenity_id in amenity_ids] or None,
        "listingBedTypes": bed_rows,
        "airbnbName": title,
        "airbnbSummary": draft.get("summary"),
        "airbnbSpace": _join_space_and_inventory(draft),
        "airbnbAccess": draft.get("access"),
        "airbnbInteraction": draft.get("interaction"),
        "airbnbNeighborhoodOverview": draft.get("neighbourhood"),
        "airbnbTransit": draft.get("transit"),
        "airbnbNotes": draft.get("other_things_to_note"),
    }
    # House defaults are sent at creation because an update cannot set some of them.
    # Observed on a live account: an update carrying the Booking.com, Vrbo and Marriott
    # cancellation policy ids returns "success" and silently discards all three, while
    # the account-wide and Airbnb policy ids stick. The ids were valid catalog ids, so
    # this is a Hostaway write restriction rather than bad data. Whether creation
    # accepts them is unverified, so a create must still be read back.
    #
    # A key the draft is silent about is dropped before the layers are stacked: silence
    # is not an instruction to erase what the operator configured. Precedence, lowest
    # first — this module's last resort, the house defaults, then the draft.
    stated = {key: value for key, value in payload.items() if value is not None}
    payload = {**_WIRE_FALLBACKS, **config.house_defaults, **stated}

    for field in _PROSE_FIELDS & payload.keys():
        payload[field] = _unwrap(payload[field])

    map_link = address.get("google_map_link")
    if map_link is not None and map_link_custom_field_id is not None:
        payload["customFieldValues"] = [
            {"customFieldId": int(map_link_custom_field_id), "value": map_link}
        ]
    return {key: value for key, value in payload.items() if value is not None}


def build_backfill_payload(
    draft: Mapping[str, Any],
    config: Configuration,
    *,
    bed_types: Mapping[str, int],
    wifi_password: str | None = None,
    markups: bool = False,
) -> dict[str, Any]:
    """Build the fields an existing listing needs before a channel export.

    Covers the configured house defaults plus the property fields the create path
    never sent. The listing's own price, fees and payout formula never appear here:
    a markup is a channel multiplier over an amount, not the amount itself.

    Every configured house default is written, the fill-only-if-empty ones included:
    this builder sees no listing, so it cannot tell which fields already carry a
    value. Withholding them is the caller's job — a caller holding the listing drops
    the fields ``Configuration.is_fill_only_if_empty`` names wherever that listing is
    not empty, or the backfill lands on top of an operator's deliberate edit.

    A draft is optional and adds to that rather than replacing it. Where the draft and
    the configuration name the same wire field the draft wins, because it is a fact
    about this property and the house default is an account-wide convention; where the
    draft is silent the house default stands. So ``build_backfill_payload({}, config)``
    is exactly the operator's configuration, which is what ``hsctl backfill <id>``
    with no draft means.

    ``markups`` adds the configured channel multipliers. Off by default because they
    are money-adjacent and should be a deliberate, separately confirmed act rather
    than something that rides along in a content backfill.

    ``wifi_password`` is passed in rather than read from the draft — the secret must
    never be committed to a repository. A draft with no beds writes no bed
    configuration at all, because that field replaces the whole set.
    """
    check_in = draft.get("check_in") or {}
    bed_config = draft.get("bed_config") or []
    stated: dict[str, Any] = {
        "checkInTimeEnd": _hour_int(check_in.get("latest"), key="check_in.latest"),
        "homeawayPropertyHeadline": draft.get("title"),
        "squareMeters": draft.get("square_meters"),
        "wifiUsername": draft.get("wifi_ssid"),
        "wifiPassword": wifi_password,
        # Replace-semantics, so silence and emptiness are not the same thing: a
        # draft that describes no beds has nothing to say about the listing's,
        # while an empty array sent over the wire deletes every bed it has.
        "listingBedTypes": _listing_bed_types(bed_config, bed_types) or None,
    }
    # A key the draft is silent about is dropped before the layers are stacked, as in
    # :func:`build_create_payload`: several of these wire fields can also be named
    # under house_defaults, and stacking a silent draft over the operator's file would
    # erase the value they configured. Precedence, lowest first — the house defaults,
    # then the draft. A configured value is never None, so nothing survives to filter.
    payload: dict[str, Any] = {
        **config.house_defaults,
        **{key: value for key, value in stated.items() if value is not None},
    }
    if markups:
        payload.update(config.markups.wire_fields())
    return payload


def missing_for_complete(payload: Mapping[str, Any]) -> list[str]:
    """Return incomplete Hostaway activation fields, preserving zero extra-person fees."""
    missing: list[str] = []
    for field in _COMPLETE_FIELDS:
        value = payload.get(field)
        if field in {"name", "externalListingName", "address", "currencyCode"}:
            valid = isinstance(value, str) and bool(value.strip())
        elif field == "price":
            valid = _is_number(value) and value > 0
        elif field == "guestsIncluded":
            valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
        else:  # priceForExtraPerson
            valid = _is_number(value)
        if not valid:
            missing.append(field)
    return missing


def _listing_bed_types(
    bed_config: Sequence[Mapping[str, Any]], bed_types: Mapping[str, int]
) -> list[dict[str, int]]:
    """One row per bed, each tagged with the bedroom it stands in.

    Every row MUST carry ``bedroomNumber``. Without it Hostaway files every bed into
    bedroom 1 — a defect that has shipped in practice, four beds landing in one room
    while the UI warned three bedrooms against one. Quantities are per-room and are
    never summed across rooms for the same reason: two kings in two rooms is not one
    row of quantity two.

    Rooms are numbered by first appearance of ``room_id``, so a room holding two
    different bed types yields two rows sharing one ``bedroomNumber``.
    """
    room_numbers: dict[str, int] = {}
    rows: list[dict[str, int]] = []
    for index, bed in enumerate(bed_config):
        # No room_id means the draft never recorded which room the bed is in. Guessing
        # is what produces the defect above: one bed per invented room inflates
        # bedroomsNumber, one shared room collapses real rooms, and both read as a
        # valid listing. Missing room data fails loud.
        if not bed.get("room_id"):
            raise ValueError(
                f"bed_config[{index}] has no room_id — cannot place the bed in a bedroom. "
                "Add room_id to every bed in the draft."
            )
        room_id = str(bed["room_id"])
        if room_id not in room_numbers:
            room_numbers[room_id] = len(room_numbers) + 1
        rows.append(
            {
                "bedTypeId": bed_types[str(bed.get("bed_type"))],
                "quantity": int(bed.get("quantity", 1)),
                "bedroomNumber": room_numbers[room_id],
            }
        )
    return rows


def _hour_int(value: Any, *, key: str) -> int | None:
    """Convert a draft time to a Hostaway hour, rejecting malformed input.

    ``key`` is the draft key the value was read from: a draft names three times and
    an operator reading the refusal has to know which one to go and fix.
    """
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        hour = value
    elif isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError(f"Invalid {key} {value!r}; expected an integer from 0 to 23.")
        hour, minute = (int(part) for part in parts)
        if not 0 <= minute <= 59:
            raise ValueError(f"Invalid {key} {value!r}; expected an integer from 0 to 23.")
    else:
        raise ValueError(f"Invalid {key} {value!r}; expected an integer from 0 to 23.")
    if not 0 <= hour <= 23:
        raise ValueError(f"Invalid {key} {value!r}; expected an integer from 0 to 23.")
    return hour


def _internal_listing_name(draft: Mapping[str, Any], config: Configuration) -> str | None:
    """The internal name: the configured template, else just the property name.

    Template fields: ``{portfolio}`` (draft key), ``{property_name}`` (as written) and
    ``{property_slug}`` (upper case, spaces and underscores as hyphens).
    """
    raw = str(draft.get("property_name") or "")
    template = config.listing_name_template
    if not template:
        return raw or None
    fields = {
        "portfolio": str(draft.get("portfolio") or ""),
        "property_name": raw,
        "property_slug": raw.upper().replace(" ", "-").replace("_", "-"),
    }
    try:
        return template.format(**fields).strip("-") or None
    except (KeyError, IndexError) as error:
        raise ValueError(f"listing_name_template: unknown field {error}") from error


def _unwrap(text: Any) -> Any:
    """Undo a draft's hard wrapping without flattening its real structure.

    Blank-line paragraph breaks and bullets survive; a newline in the middle of a
    sentence does not. A wrapped continuation line joins the bullet above it rather
    than becoming a paragraph of its own.
    """
    if not isinstance(text, str):
        return text
    paragraphs = []
    for paragraph in text.split("\n\n"):
        lines = [line.strip() for line in paragraph.split("\n") if line.strip()]
        # Calibrate against this paragraph's own widest line instead of assuming a
        # column: a line the wrapper cut lands within a word of the full width, while
        # a line the author ended — a section header (`🛏️ SLEEPING`), a scan break —
        # falls well short of it. A structural marker in the draft would beat this
        # heuristic, but the draft format carries none.
        threshold = max((len(line) for line in lines), default=0) - _WRAP_SLACK
        chunks: list[str] = []
        previous = ""
        for line in lines:
            # `str.isupper` is the header test: true only when a line has cased letters
            # and shouts all of them. A wrapper never emits one, so a header keeps its
            # line however wide it runs. Caseless scripts are false, so they still wrap.
            # The cost is that all-caps emphatic prose reads as a header.
            wrapped = (
                bool(chunks)
                and threshold <= len(previous) <= _WRAP_MAX
                and len(previous) >= _WRAP_MIN
                and not previous.isupper()
            )
            if wrapped and not _LIST_ITEM.match(line) and not line.isupper():
                chunks[-1] = f"{chunks[-1]} {line}"
            else:
                chunks.append(line)
            previous = line
        if chunks:
            paragraphs.append("\n".join(chunks))
    return "\n\n".join(paragraphs)


def _join_nonempty(*values: Any) -> str:
    return ", ".join(str(value) for value in values if value not in (None, ""))


def _join_space_and_inventory(draft: Mapping[str, Any]) -> str:
    prose = str(draft.get("the_space") or "").rstrip()
    inventory = str(draft.get("inventory_by_room") or "").lstrip()
    return f"{prose}\n\n{inventory}" if prose and inventory else prose or inventory


def _render_house_rules(rules: Mapping[str, Any]) -> str:
    return "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in rules.items())


def _upper(value: Any) -> str | None:
    return str(value).upper() if value is not None else None


def _wire_bool(value: Any) -> int | None:
    return None if value is None else int(bool(value))


def _is_number(value: Any) -> TypeGuard[float]:
    """A money value: any real number, but never a bool masquerading as 0 or 1."""
    return isinstance(value, Real) and not isinstance(value, bool)
