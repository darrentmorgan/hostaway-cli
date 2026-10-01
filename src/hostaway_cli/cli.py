"""The ``hsctl`` command-line entry point.

Every command that talks to Hostaway builds its session here, which is also
where the surface banner is printed: one place decides what an operator is
pointed at, so no command can quietly skip saying it (docs/adr/0004).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date
from importlib.metadata import version as package_version
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

import typer
import yaml

from hostaway_cli.config import ConfigError, Configuration, load_config
from hostaway_cli.credentials import Credentials, CredentialsError, load_credentials
from hostaway_cli.doctor import Outcome, run_checks
from hostaway_cli.errors import HostawayError, HostawayPaginationError
from hostaway_cli.export import Channel, export_listing_to_airbnb
from hostaway_cli.listing_payload import (
    build_backfill_payload,
    build_create_payload,
    missing_for_complete,
)
from hostaway_cli.models import MAX_PAGE_LIMIT
from hostaway_cli.payloads import LISTING_FIELD_WIRE_NAMES
from hostaway_cli.reservations import reservation_identities, safe_reservation
from hostaway_cli.session import HostawaySession
from hostaway_cli.surface import Surface
from hostaway_cli.token_cache import TokenCache, TokenCacheError
from hostaway_cli.writes import (
    DELETES_IMAGE,
    Change,
    Observation,
    dropped,
    protected_fields_in,
    render,
    render_readback,
    same_value,
)

app = typer.Typer(
    name="hsctl",
    no_args_is_help=True,
    add_completion=False,
)

# Column widths for the listings table. Hostaway listing IDs are six digits, and
# the two name columns are wide enough to read at a glance and narrow enough that
# a row still fits an eighty-column terminal.
ID_WIDTH = 8
NAME_WIDTH = 34
INTERNAL_WIDTH = 26

# Column widths for the calendar table. A date is never shortened, the two stay
# bounds are small numbers, and "departure" is the longest closure there is.
DATE_WIDTH = 10
AVAIL_WIDTH = 5
PRICE_WIDTH = 9
STAY_WIDTH = 3
CLOSED_WIDTH = 9

BLANK = "-"

# What a listing's amenity is called when the account catalog does not publish
# it: the ID is still printed, because that is the one the operator has to ask
# Hostaway about.
UNNAMED = "(unknown)"

# A create is asked for by name, so the whole account is read first to prove no
# listing already carries that name. The walk goes through the session's strict
# pagination seam — a page that skips or repeats a listing is refused rather than
# scanned — and these bound it: Hostaway's own page ceiling, and enough pages to
# cover an account far larger than any one operator runs.
LISTING_PAGE_SIZE = MAX_PAGE_LIMIT
MAX_LISTING_PAGES = 50

# The draft keys a create cannot be built without, and what each one is for. Every
# other key may be absent (property_type and hostaway_amenities are optional: when
# given they are resolved against the account's catalogs, when absent the field is
# left out of the payload); these are checked before a session exists, so a draft
# that cannot produce a listing costs no Hostaway call at all.
REQUIRED_DRAFT_KEYS: Mapping[str, str] = MappingProxyType(
    {
        "title": "the listing name, which is also what the duplicate check looks for",
    }
)

# What each draft key has to be, for the keys the builders walk into rather than read
# as one value. A draft is written by hand, and a key typed as the wrong kind of thing
# — an address written as the one line it is on an envelope, a bed configuration
# written as the list of bed names it reads like — is an ordinary mistake. It is named
# here, before a session exists, because further in it is an attribute error on a
# string: a traceback is not something an operator can act on.
DRAFT_SHAPES: Mapping[str, tuple[type, str]] = MappingProxyType(
    {
        "address": (Mapping, "a mapping of country, state, city, street and the rest"),
        "check_in": (Mapping, "a mapping of earliest, latest and check_out"),
        "pricing": (Mapping, "a mapping of base_price and currency"),
        "fees": (Mapping, "a mapping of cleaning_fee, security_deposit and the extra-guest fees"),
        "house_rules": (Mapping, "a mapping of rule name to rule text"),
        "bed_config": (list, "a list of beds, each a mapping of room_id, bed_type and quantity"),
        "hostaway_amenities": (list, "a list of amenity names or ids from the account's catalog"),
    }
)

# Reservations come back a page at a time; this is the page Hostaway is asked for.
RESERVATION_PAGE_SIZE = 100

# The widest check-out window a lookup will search. A reservation search is a
# bounded question about a season; a wider one is a report, and asking Hostaway
# for it a page at a time is how a terminal command turns into a crawl.
MAX_WINDOW_DAYS = 366

# And the most pages it will walk before refusing. Hostaway answers a window,
# not a count, so a window holding more reservations than this is one the
# operator has to narrow: the alternative is a command that never comes back.
MAX_RESERVATION_PAGES = 20

# The most reservations one lookup will be asked to find by ID. Beyond this it
# is an export rather than a reconciliation, and the walk above cannot promise
# to reach them all inside the window.
MAX_RESERVATION_IDS = 50

# ``calendar-set``'s own option names, the key each field carries on a calendar day,
# and what the diff calls it. The wire key is what the gate matches on.
CALENDAR_WIRE_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "is_available": "isAvailable",
        "minimum_stay": "minimumStay",
        "maximum_stay": "maximumStay",
        "closed_on_arrival": "closedOnArrival",
        "closed_on_departure": "closedOnDeparture",
        "note": "note",
    }
)

CALENDAR_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "is_available": "availability",
        "minimum_stay": "minimum stay",
        "maximum_stay": "maximum stay",
        "closed_on_arrival": "closed on arrival",
        "closed_on_departure": "closed on departure",
        "note": "note",
    }
)

# The four caption fields Hostaway exposes on a photo. One caption fills all of them:
# the channels have no reason to carry different words for the same picture.
CAPTION_FIELDS = ("caption", "airbnbCaption", "vrboCaption", "bookingEngineCaption")

# Fields whose value is a secret. A secret passed as argv survives in shell history
# and in every process listing on the machine, so redacting the diff is not enough:
# it arrives through the environment or not at all.
SECRET_FIELDS = frozenset({"doorSecurityCode", "wifiPassword"})

DOOR_CODE_ENV = "HSCTL_DOOR_CODE"
WIFI_PASSWORD_ENV = "HSCTL_WIFI_PASSWORD"

# Whole-array fields: whatever is sent becomes the entire set, so a scalar typed on
# the command line here deletes everything the array holds. Each names what rebuilds
# it from the live listing instead.
REPLACE_SEMANTICS_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "listingImages": "hsctl captions rebuilds it from the live listing",
        "listingBedTypes": "hsctl backfill rebuilds it from a draft's bed_config",
        "customFieldValues": "no hsctl command rebuilds it yet",
    }
)

# A misconfigured environment is not a mistyped command line, and neither is a
# refusal from Hostaway, so both exit with their own message rather than click's
# usage box. They exit differently because the operator's next move differs: fix
# the setup, or take it up with Hostaway.
SETUP_EXIT_CODE = 2
HOSTAWAY_EXIT_CODE = 1

# A write the gate refused. Nothing was sent and Hostaway was never asked, so it is
# neither of the two above: the change itself is what needs the operator's decision.
REFUSED_EXIT_CODE = 3

# A write that landed, followed by an export that did not. Its own code because the
# operator's next move is its own: the listing is correct on Hostaway and stale on the
# channel, and re-running the write would be the wrong repair.
EXPORT_EXIT_CODE = 4

# What --export says on every write command that offers it. Content and amenities do
# not reach a channel on a save, so the operator has to ask.
EXPORT_HELP = "After the write lands, export the listing to Airbnb."

# What each doctor outcome looks like when the terminal has colour.
OUTCOME_COLOURS = {
    Outcome.PASS: typer.colors.GREEN,
    Outcome.WARN: typer.colors.YELLOW,
    Outcome.FAIL: typer.colors.RED,
}


@app.callback()
def main() -> None:
    """Operate one Hostaway account safely: every write is a dry run until applied."""


@app.command()
def version() -> None:
    """Print the installed hsctl version."""
    typer.echo(f"hsctl {package_version('hostaway-cli')}")


@app.command()
def doctor() -> None:
    """Check the environment and configuration offline; call Hostaway not at all."""
    checks = run_checks()
    for check in checks:
        typer.secho(check.line(), fg=OUTCOME_COLOURS[check.outcome])
    failed = [check.name for check in checks if check.outcome is Outcome.FAIL]
    if failed:
        typer.secho(
            f"doctor: {len(failed)} of {len(checks)} checks failed: {', '.join(failed)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=SETUP_EXIT_CODE)


@app.command()
def listings(
    limit: int = typer.Option(200, "--limit", help="Most listings to fetch in one page."),
) -> None:
    """List the account's listings: ID, name, internal name and channel status."""

    async def run(session: HostawaySession) -> None:
        page, total = await session.list_listings(limit=limit, offset=0)
        typer.echo(_total_line(total, shown=len(page), noun="listings"))
        typer.echo(_row("ID", "NAME", "INTERNAL", "CHANNEL"))
        for listing in page:
            typer.echo(
                _row(
                    # An ID is never shortened: a truncated one names another listing.
                    _cell(listing.get("id"), None),
                    _cell(listing.get("name"), NAME_WIDTH),
                    _cell(listing.get("internalListingName"), INTERNAL_WIDTH),
                    _cell(listing.get("airbnbExportStatus"), None),
                )
            )

    _with_session(run)


@app.command()
def get(listing_id: int = typer.Argument(..., help="Hostaway listing ID.")) -> None:
    """Print one listing in full, as JSON."""

    async def run(session: HostawaySession) -> None:
        listing = await session.get_listing(listing_id)
        typer.echo(json.dumps(listing, indent=2, ensure_ascii=False))

    _with_session(run)


@app.command()
def calendar(
    listing_id: int = typer.Argument(..., help="Hostaway listing ID."),
    start: str = typer.Option(..., "--start", help="First date to show, YYYY-MM-DD."),
    end: str = typer.Option(..., "--end", help="Last date to show, YYYY-MM-DD."),
) -> None:
    """Show a listing's calendar days across an inclusive date range."""

    async def run(session: HostawaySession) -> None:
        days = await session.get_listing_availability(listing_id, start, end)
        typer.echo(f"{len(days)} days {start}..{end}")
        typer.echo(_calendar_row("DATE", "AVAIL", "PRICE", "MIN", "MAX", "CLOSED", "NOTE"))
        for day in days:
            typer.echo(
                _calendar_row(
                    _cell(day.get("date"), None),
                    _flag(day.get("isAvailable")),
                    _cell(day.get("price"), None),
                    _cell(day.get("minimumStay"), None),
                    _cell(day.get("maximumStay"), None),
                    _closures(day),
                    _cell(day.get("note"), None),
                )
            )

    _with_session(run)


@app.command()
def amenities(
    search: str = typer.Option("", "--search", help="Only amenities whose name contains this."),
) -> None:
    """List the account's amenity catalog: the names amenity IDs stand for."""

    async def run(session: HostawaySession) -> None:
        catalog = await session.get_amenities()
        term = search.casefold()
        rows = [row for row in catalog if term in str(row.get("name", "")).casefold()]
        typer.echo(_total_line(len(catalog), shown=len(rows), noun="amenities"))
        typer.echo(_amenity_row("ID", "NAME"))
        for row in rows:
            typer.echo(_amenity_row(_cell(row.get("id"), None), _cell(row.get("name"), None)))

    _with_session(run)


@app.command("listing-amenities")
def listing_amenities(listing_id: int = typer.Argument(..., help="Hostaway listing ID.")) -> None:
    """Show one listing's current amenities, resolved to their catalog names."""

    async def run(session: HostawaySession) -> None:
        catalog = await session.get_amenities()
        # Every catalog row is validated by the session, so both keys are there.
        names = {row["id"]: row["name"] for row in catalog}
        listing = await session.get_listing(listing_id)
        amenity_ids = _listing_amenity_ids(listing)
        typer.echo(f"{len(amenity_ids)} amenities on listing {listing_id}")
        typer.echo(_amenity_row("ID", "NAME"))
        for amenity_id in amenity_ids:
            typer.echo(_amenity_row(str(amenity_id), str(names.get(amenity_id, UNNAMED))))

    _with_session(run)


@app.command("reservation-lookup")
def reservation_lookup(
    departure_start: str = typer.Option(
        ..., "--departure-start", help="First check-out date to include, YYYY-MM-DD."
    ),
    departure_end: str = typer.Option(
        ..., "--departure-end", help="Last check-out date to include, YYYY-MM-DD."
    ),
    listing_id: int | None = typer.Option(
        None, "--listing", help="Only this listing's reservations."
    ),
    reservation_ids: list[str] = typer.Option(
        [],
        "--reservation-id",
        help="Only this reservation, by Hostaway or channel ID; repeatable.",
    ),
) -> None:
    """Find reservations by check-out window and print only the safe fields."""
    _checked_window(departure_start, departure_end)
    requested = list(dict.fromkeys(reservation_ids))
    if len(requested) > MAX_RESERVATION_IDS:
        raise typer.BadParameter(f"Name at most {MAX_RESERVATION_IDS} reservations in one lookup.")

    async def run(session: HostawaySession) -> None:
        found = await _reservations_in_window(
            session,
            listing_id=listing_id,
            departure_start=departure_start,
            departure_end=departure_end,
            wanted=set(requested),
        )
        typer.echo(
            json.dumps(
                [safe_reservation(b) for b in _selected(found, requested)],
                indent=2,
                ensure_ascii=False,
            )
        )

    _with_session(run)


async def _reservations_in_window(
    session: HostawaySession,
    *,
    listing_id: int | None,
    departure_start: str,
    departure_end: str,
    wanted: set[str],
) -> list[dict[str, Any]]:
    """Every reservation checking out inside the window, a page at a time.

    ``wanted`` is what the operator named, and the walk stops as soon as all of
    it has been seen: a lookup for one reservation should not read the season.
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    for _ in range(MAX_RESERVATION_PAGES):
        page = await session.search_bookings(
            listing_id=listing_id,
            check_out_from=departure_start,
            check_out_to=departure_end,
            limit=RESERVATION_PAGE_SIZE,
            offset=offset,
        )
        found.extend(page)
        for booking in page:
            seen |= reservation_identities(booking) & wanted
        if seen == wanted and wanted:
            break
        # A short page is the end of the window; a full one may have more behind it.
        if len(page) < RESERVATION_PAGE_SIZE:
            break
        offset += len(page)
    else:
        raise typer.BadParameter(
            f"More than {MAX_RESERVATION_PAGES * RESERVATION_PAGE_SIZE} reservations "
            "check out in that window. Narrow it and look again."
        )
    return found


def _selected(found: list[dict[str, Any]], requested: list[str]) -> list[dict[str, Any]]:
    """The reservations the operator named, in the order they named them.

    With nothing named, the window itself is the answer.  With something named
    and not found, the answer is a refusal: a lookup that silently returns fewer
    rows than it was asked for is how a reconciliation goes quietly wrong.
    """
    if not requested:
        return found
    by_identity: dict[str, dict[str, Any]] = {}
    for booking in found:
        for identity in reservation_identities(booking) & set(requested):
            by_identity.setdefault(identity, booking)
    missing = [identity for identity in requested if identity not in by_identity]
    if missing:
        raise typer.BadParameter(
            "No reservation checking out in that window is " + ", ".join(missing) + "."
        )
    return [by_identity[identity] for identity in requested]


def _checked_window(start: str, end: str) -> None:
    """Refuse a check-out window that cannot bound a search, before anything is sent."""
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as error:
        raise typer.BadParameter("Departure bounds must be ISO dates (YYYY-MM-DD).") from error
    if last < first:
        raise typer.BadParameter("The departure window must end on or after it starts.")
    if (last - first).days > MAX_WINDOW_DAYS:
        raise typer.BadParameter(
            f"The departure window must be no wider than {MAX_WINDOW_DAYS} days."
        )


@app.command("set")
def set_fields(
    listing_id: int = typer.Argument(..., help="Hostaway listing ID."),
    name: str = typer.Option(None, "--name", help="Listing name."),
    description: str = typer.Option(None, "--description", help="Listing description."),
    bedrooms: int = typer.Option(None, "--bedrooms", help="Number of bedrooms."),
    bathrooms: float = typer.Option(None, "--bathrooms", help="Number of bathrooms."),
    max_guests: int = typer.Option(None, "--max-guests", help="Maximum guests."),
    address: str = typer.Option(None, "--address", help="Street address."),
    city: str = typer.Option(None, "--city", help="City."),
    state: str = typer.Option(None, "--state", help="State or province."),
    country: str = typer.Option(None, "--country", help="Country."),
    zip_code: str = typer.Option(None, "--zip", help="Postal code."),
    lat: float = typer.Option(None, "--lat", help="Latitude."),
    lng: float = typer.Option(None, "--lng", help="Longitude."),
    cancellation_policy: str = typer.Option(
        None, "--cancellation-policy", help="Cancellation policy name Hostaway validates."
    ),
    field: list[str] = typer.Option(
        [], "--field", help="Any other Hostaway field as KEY=VALUE. Repeatable."
    ),
    door_code: bool = typer.Option(
        False, "--door-code", help=f"Write doorSecurityCode from the {DOOR_CODE_ENV} variable."
    ),
    apply: bool = typer.Option(False, "--apply", help="Send the change (default: dry run)."),
    allow_protected: bool = typer.Option(
        False, "--allow-protected", help="Also send a change that touches a protected field."
    ),
    export: bool = typer.Option(False, "--export", help=EXPORT_HELP),
) -> None:
    """Set listing fields. Dry run unless --apply.

    The named options cover the fields an operator sets by hand; ``--field`` reaches
    any other field under Hostaway's own wire key. Money and availability are reachable
    that way too, and the gate is what stands in front of them (docs/adr/0001).

    A save does not reach a channel. ``--export`` exports the listing once the write
    has been read back, so the change is visible where guests read it.
    """
    named = {
        key: value
        for key, value in {
            "name": name,
            "description": description,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "max_guests": max_guests,
            "address": address,
            "city": city,
            "state": state,
            "country": country,
            "zip_code": zip_code,
            "latitude": lat,
            "longitude": lng,
            "cancellation_policy": cancellation_policy,
        }.items()
        if value is not None
    }
    raw = _parse_fields(field)
    for key, owner in REPLACE_SEMANTICS_FIELDS.items():
        if key in raw:
            raise typer.BadParameter(
                f"{key} replaces the whole set — a value here deletes the rest ({owner})."
            )
    if secrets := sorted(SECRET_FIELDS & set(raw)):
        raise typer.BadParameter(
            f"{', '.join(secrets)} must not be passed on the command line — "
            f"set {DOOR_CODE_ENV} and pass --door-code."
        )
    if door_code:
        secret = os.environ.get(DOOR_CODE_ENV, "")
        if not secret.strip():
            raise typer.BadParameter(f"--door-code needs {DOOR_CODE_ENV} set to a non-blank value.")
        raw["doorSecurityCode"] = secret
    if twice := sorted({LISTING_FIELD_WIRE_NAMES[key] for key in named} & set(raw)):
        raise typer.BadParameter(
            f"Named twice, once as an option and once as --field: {', '.join(twice)}."
        )
    if not named and not raw:
        raise typer.BadParameter("Name at least one field to set.")

    async def run(session: HostawaySession) -> None:
        current = await session.get_listing(listing_id)
        changes = [
            Change(
                field=LISTING_FIELD_WIRE_NAMES[key],
                before=current.get(LISTING_FIELD_WIRE_NAMES[key]),
                after=value,
                label=key,
            )
            for key, value in named.items()
        ] + [
            Change(field=key, before=current.get(key), after=value, secret=key in SECRET_FIELDS)
            for key, value in raw.items()
        ]
        typer.echo(f"Listing {listing_id} — changing {_plural(len(changes), 'field')}:")
        for line in render(changes):
            typer.echo(line)
        _export_intent_notice(listing_id, export=export)
        if not _gate(changes, apply=apply, allow_protected=allow_protected):
            return
        await session.update_listing(
            listing_id, fields={change.field: change.after for change in changes}
        )
        read_back = await session.get_listing(listing_id)
        _report_readback([(change, read_back.get(change.field)) for change in changes])
        await _maybe_export(session, listing_id, export=export)

    _with_session(run)


@app.command()
def create(
    draft_path: Path = typer.Argument(..., exists=True, readable=True, help="Listing draft YAML."),
    apply: bool = typer.Option(False, "--apply", help="Send the change (default: dry run)."),
    allow_protected: bool = typer.Option(
        False, "--allow-protected", help="Also send a change that touches a protected field."
    ),
) -> None:
    """Create a listing from a YAML draft. Dry run unless --apply.

    The draft is the property's own facts; the house defaults come from the
    configuration and fill only what the draft does not say (docs/adr/0002). The
    catalog names in the draft — its property type, bed types, amenities and the
    custom field carrying the map link — are resolved against this account's own
    catalogs, because an ID means nothing outside the account that published it.

    The whole payload is printed before anything is sent, and an applied create is
    read back field by field. Every create carries a price, a currency, a cleaning
    fee and a deposit, so every create is a protected write and needs
    --allow-protected as well as --apply: the gate reads the fields in front of it
    and never the name of the command (docs/adr/0001). A create is also the one
    write that can be neither retried nor taken back, which is the last place to
    spend the second flag.
    """
    config = _configuration()
    draft = _draft(draft_path)

    async def run(session: HostawaySession) -> None:
        # Resolved and built before the account walk below: a draft that cannot become
        # a payload is refused for the price of the catalog reads, not of a scan of
        # every listing on the account.
        amenity_ids = (
            _resolve_catalog(
                await session.get_amenities(), draft["hostaway_amenities"], kind="amenity"
            )
            if draft.get("hostaway_amenities")
            else []
        )
        property_type_id = (
            _resolve_catalog(
                await session.get_property_types(), [draft["property_type"]], kind="property type"
            )[0]
            if draft.get("property_type")
            else None
        )
        bed_types = await _bed_type_ids(session, draft)
        map_link_custom_field_id = await _map_link_field_id(session, draft)
        try:
            payload = build_create_payload(
                draft,
                config,
                amenity_ids=amenity_ids,
                bed_types=bed_types,
                property_type_id=property_type_id,
                map_link_custom_field_id=map_link_custom_field_id,
            )
        except ValueError as error:
            # The builder refuses a draft it cannot map rather than guessing — a bed
            # with no room, a check-in time that is not an hour. An operator writes
            # drafts by hand, so that refusal is theirs to read, not a traceback.
            raise typer.BadParameter(f"{draft_path}: {error}") from error
        except (AttributeError, TypeError) as error:
            # A shape DRAFT_SHAPES does not name yet, met one layer down: a value
            # inside a mapping that is itself the wrong kind of thing. Still the
            # operator's to read. The named refusals above are where a shape belongs.
            raise typer.BadParameter(
                f"{draft_path} is not a shape a listing can be built from: {error}"
            ) from error
        await _refuse_duplicate_name(session, str(draft["title"]))
        changes = [Change(field=key, before=None, after=value) for key, value in payload.items()]
        typer.echo(f"New listing from {draft_path} — {_plural(len(payload), 'field')}:")
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        if missing := missing_for_complete(payload):
            raise typer.BadParameter(
                f"Hostaway cannot activate a listing without {', '.join(missing)}; "
                f"the draft leaves {_plural(len(missing), 'field')} unset."
            )
        typer.echo("Completeness: every field Hostaway needs to activate the listing is set.")
        if not _gate(changes, apply=apply, allow_protected=allow_protected):
            return
        body = await session.create_listing(payload)
        listing_id = int(body["result"]["id"])
        typer.secho(f"Created listing {listing_id}.", fg=typer.colors.GREEN, bold=True)
        read_back = await session.get_listing(listing_id)
        _report_readback(
            [(change, _as_sent(change.after, read_back.get(change.field))) for change in changes]
        )

    _with_session(run)


@app.command()
def backfill(
    listing_id: int = typer.Argument(..., help="Hostaway listing ID."),
    draft_path: Path = typer.Argument(
        None,
        exists=True,
        readable=True,
        help="Optional listing draft YAML: the property facts a create does not send.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Also write the fill-only-if-empty fields over the values the listing carries.",
    ),
    markups: bool = typer.Option(
        False, "--markups", help="Also write the configured channel markups."
    ),
    apply: bool = typer.Option(False, "--apply", help="Send the change (default: dry run)."),
    allow_protected: bool = typer.Option(
        False, "--allow-protected", help="Also send a change that touches a protected field."
    ),
    export: bool = typer.Option(False, "--export", help=EXPORT_HELP),
) -> None:
    """Write the configured house defaults onto a listing that exists. Dry run unless --apply.

    The values are the operator's own, from the configuration and nowhere else
    (docs/adr/0002). What reaches the listing is only what it does not already say:
    a field already carrying the configured value is not a change, and a
    fill-only-if-empty field carrying anything at all is left alone, because a house
    default is a convention and an operator's edit is a decision. ``--force`` writes
    those over the top.

    A draft adds the property's own facts the create path never sent — its headline,
    floor area, wifi network and bed configuration. Without one the backfill is the
    configuration alone, which is what ``hsctl backfill <id>`` means.

    ``--markups`` adds the configured channel multipliers. They are ordinary fields —
    a markup multiplies an amount rather than being one (docs/adr/0001) — so they need
    no second flag, and they are off by default because a multiplier that rides along
    with a content backfill is not one the operator chose.
    """
    config = _configuration()
    draft: Mapping[str, Any] = {} if draft_path is None else _draft(draft_path, required={})
    wifi_password = _wifi_password(draft, apply=apply)

    async def run(session: HostawaySession) -> None:
        _wifi_notice(draft, wifi_password)
        bed_types = await _bed_type_ids(session, draft)
        try:
            payload = build_backfill_payload(
                draft,
                config,
                bed_types=bed_types,
                wifi_password=wifi_password,
                markups=markups,
            )
        except ValueError as error:
            # Only a draft can make the builder refuse — a bed with no room, a
            # check-in time that is not an hour — so the path is always known here.
            raise typer.BadParameter(f"{draft_path}: {error}") from error
        current = await session.get_listing(listing_id)
        changes, held = _backfill_plan(payload, current, config, force=force)
        if changes:
            typer.echo(f"Listing {listing_id} — backfilling {_plural(len(changes), 'field')}:")
        else:
            typer.echo(f"Listing {listing_id} — nothing to backfill.")
        for line in render(changes):
            typer.echo(line)
        if held:
            typer.echo(f"  Left alone (already set; --force overwrites): {', '.join(held)}")
        # An empty write is not a no-op on the wire: Hostaway is asked nothing, so it
        # is not asked at all. Ending here also keeps --apply honest — there is no
        # read-back to report on a write that was never made.
        if not changes:
            return
        # Asked for and actually changing: a multiplier the listing already carries
        # is nothing to warn about, and a warning that fires anyway is one an
        # operator learns to scroll past.
        if quoted := sorted(set(config.markups.wire_fields()) & {c.field for c in changes}):
            typer.secho(
                f"Channel markups in this change: {', '.join(quoted)}. A markup is what "
                "a guest is quoted on that channel — read the multipliers above.",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        _export_intent_notice(listing_id, export=export)
        if not _gate(changes, apply=apply, allow_protected=allow_protected):
            return
        await session.update_listing(
            listing_id, fields={change.field: change.after for change in changes}
        )
        read_back = await session.get_listing(listing_id)
        _report_readback(
            [(change, _as_sent(change.after, read_back.get(change.field))) for change in changes]
        )
        await _maybe_export(session, listing_id, export=export)

    _with_session(run)


@app.command()
def captions(
    listing_id: int = typer.Argument(..., help="Hostaway listing ID."),
    plan_path: Path = typer.Argument(
        ..., exists=True, readable=True, help="Caption plan: JSON array of {id, caption}."
    ),
    apply: bool = typer.Option(False, "--apply", help="Send the change (default: dry run)."),
    allow_protected: bool = typer.Option(
        False, "--allow-protected", help="Also send a change that touches a protected field."
    ),
    export: bool = typer.Option(False, "--export", help=EXPORT_HELP),
) -> None:
    """Set per-photo captions from a plan file. Dry run unless --apply.

    One caption goes to all four fields Hostaway exposes: the channels have no reason
    to diverge. ``listingImages`` is replace-semantics — the array sent becomes the
    whole photo set — so the command rebuilds the full array from the live listing.
    A plan that omits a live photo is asking for that photo to be deleted, which is a
    protected change and needs --allow-protected as well as --apply. A caption is text
    a guest reads on the channel, and a save does not send it: ``--export`` does.
    """
    wanted = _caption_plan(plan_path)

    async def run(session: HostawaySession) -> None:
        live = sorted(await session.get_listing_photos(listing_id), key=_sort_order)
        if unknown := sorted(set(wanted) - {int(image["id"]) for image in live}):
            raise typer.BadParameter(
                f"Plan names photo ids listing {listing_id} does not carry: {unknown}"
            )
        kept = [image for image in live if int(image["id"]) in wanted]
        rows = [
            {
                "id": int(image["id"]),
                "url": image["url"],
                "sortOrder": image["sortOrder"],
                **dict.fromkeys(CAPTION_FIELDS, wanted[int(image["id"])]),
            }
            for image in kept
        ]
        # Each planned change stays paired with the photo it is about, because the
        # read-back has to look that photo up again by ID.
        planned = [
            (
                Change(
                    field="caption",
                    before=_captions_of(image),
                    after=dict.fromkeys(CAPTION_FIELDS, wanted[int(image["id"])]),
                    label=f"photo {image['sortOrder']}",
                ),
                int(image["id"]),
            )
            for image in kept
        ] + [
            (
                Change(
                    field=DELETES_IMAGE,
                    before=_captions_of(image),
                    after=None,
                    label=f"photo {image['sortOrder']}",
                ),
                int(image["id"]),
            )
            for image in live
            if int(image["id"]) not in wanted
        ]
        changes = [change for change, _ in planned]
        moving = [change for change in changes if change.before != change.after]
        typer.echo(f"Listing {listing_id} — {len(moving)} of {len(live)} photos change:")
        for change in moving:
            after = (
                "DELETED — the plan omits this photo"
                if change.after is None
                else repr(change.after["caption"])
            )
            typer.echo(f"  {change.name}: {change.before['caption']!r} -> {after}")
        if not moving:
            typer.secho("No change — nothing to send.", fg=typer.colors.YELLOW, bold=True)
            return
        typer.secho(
            f"Sending all {len(rows)} photos — the array replaces the whole photo set.",
            fg=typer.colors.YELLOW,
        )
        _export_intent_notice(listing_id, export=export)
        if not _gate(changes, apply=apply, allow_protected=allow_protected):
            return
        await session.update_listing(listing_id, fields={"listingImages": rows})
        read_back = {
            int(image["id"]): image for image in await session.get_listing_photos(listing_id)
        }
        _report_readback(
            [
                (change, _captions_of(read_back[image_id]) if image_id in read_back else None)
                for change, image_id in planned
            ]
        )
        await _maybe_export(session, listing_id, export=export)

    _with_session(run)


@app.command("calendar-set")
def calendar_set(
    listing_id: int = typer.Argument(..., help="Hostaway listing ID."),
    start: str = typer.Option(..., "--start", help="First date of the range, YYYY-MM-DD."),
    end: str = typer.Option(..., "--end", help="Last date of the range, YYYY-MM-DD."),
    available: bool = typer.Option(
        None, "--available/--blocked", help="Open or block the range. Protected."
    ),
    min_stay: int = typer.Option(None, "--min-stay", help="Minimum nights."),
    max_stay: int = typer.Option(None, "--max-stay", help="Maximum nights."),
    closed_arrival: bool = typer.Option(
        None, "--closed-arrival/--open-arrival", help="Whether guests may arrive."
    ),
    closed_departure: bool = typer.Option(
        None, "--closed-departure/--open-departure", help="Whether guests may depart."
    ),
    note: str = typer.Option(None, "--note", help="Calendar note for the range."),
    apply: bool = typer.Option(False, "--apply", help="Send the change (default: dry run)."),
    allow_protected: bool = typer.Option(
        False, "--allow-protected", help="Also send a change that touches a protected field."
    ),
) -> None:
    """Set calendar days across an inclusive date range. Dry run unless --apply.

    Availability is a protected field and needs --allow-protected as well as --apply;
    stays, closures and the note are ordinary writes (docs/adr/0001). Per-day price is
    reachable through no flag here.
    """
    named = {
        key: value
        for key, value in {
            "is_available": available,
            "minimum_stay": min_stay,
            "maximum_stay": max_stay,
            "closed_on_arrival": closed_arrival,
            "closed_on_departure": closed_departure,
            "note": note,
        }.items()
        if value is not None
    }
    if not named:
        raise typer.BadParameter("Name at least one calendar field to set.")

    async def run(session: HostawaySession) -> None:
        days = await session.get_listing_availability(listing_id, start, end)
        changes = [
            Change(
                field=CALENDAR_WIRE_NAMES[key],
                before=_values_across(days, CALENDAR_WIRE_NAMES[key]),
                after=int(value) if isinstance(value, bool) else value,
                label=CALENDAR_LABELS[key],
            )
            for key, value in named.items()
        ]
        typer.echo(f"Listing {listing_id} calendar {start}..{end} ({len(days)} days) — set:")
        for line in render(changes):
            typer.echo(line)
        if not _gate(changes, apply=apply, allow_protected=allow_protected):
            return
        # Every field is named, and the payload builder drops the ones left unset.
        await session.update_listing_availability(
            listing_id,
            start,
            end,
            is_available=available,
            minimum_stay=min_stay,
            maximum_stay=max_stay,
            closed_on_arrival=closed_arrival,
            closed_on_departure=closed_departure,
            note=note,
        )
        read_back = await session.get_listing_availability(listing_id, start, end)
        _report_readback(
            [(change, day.get(change.field)) for change in changes for day in read_back]
        )

    _with_session(run)


@app.command("amenities-set")
def amenities_set(
    listing_id: int = typer.Argument(..., help="Hostaway listing ID."),
    add: list[str] = typer.Option(
        [], "--add", help="Amenity ID or catalog name to add. Repeatable."
    ),
    remove: list[str] = typer.Option(
        [], "--remove", help="Amenity ID or catalog name to remove. Repeatable."
    ),
    apply: bool = typer.Option(False, "--apply", help="Send the change (default: dry run)."),
    export: bool = typer.Option(False, "--export", help=EXPORT_HELP),
) -> None:
    """Add or remove amenities, merged against the listing's current set.

    Hostaway replaces the whole amenity set on every write, so this command always
    sends the complete set: the listing's own amenities, plus the ones added, less
    the ones removed. Dry run unless --apply.

    Amenities do not reach a channel on a save; ``--export`` exports the listing
    once the merged set has been read back.
    """
    if not add and not remove:
        raise typer.BadParameter("Name at least one amenity to --add or --remove.")

    async def run(session: HostawaySession) -> None:
        catalog = await session.get_amenities()
        names = {int(row["id"]): str(row["name"]) for row in catalog}
        added = _resolve_catalog(catalog, add, kind="amenity")
        removed = _resolve_catalog(catalog, remove, kind="amenity")
        listing = await session.get_listing(listing_id)
        current = _amenity_ids(listing, listing_id)
        merged = sorted((set(current) | set(added)) - set(removed))

        typer.echo(f"Listing {listing_id} — amenities:")
        for line in _amenity_lines(current, merged, added, removed, names):
            typer.echo(line)
        for notice in _amenity_notices(current, added, removed, names):
            typer.secho(notice, fg=typer.colors.YELLOW)
        if merged == current:
            typer.secho("No change — nothing to send.", fg=typer.colors.YELLOW, bold=True)
            return

        change = Change(field="listingAmenities", before=current, after=merged, label="amenities")
        _export_intent_notice(listing_id, export=export)
        if not _gate([change], apply=apply, allow_protected=False):
            return
        await session.update_listing_amenities(listing_id, merged)
        read_back = await session.get_listing(listing_id)
        _report_readback([(change, _amenity_ids(read_back, listing_id))])
        await _maybe_export(session, listing_id, export=export)

    _with_session(run)


@app.command()
def export(
    listing_id: int = typer.Argument(..., help="Hostaway listing ID."),
    channel: Channel = typer.Option(
        Channel.AIRBNB, "--channel", help="Channel to push the listing to."
    ),
    apply: bool = typer.Option(False, "--apply", help="Send the export (default: dry run)."),
) -> None:
    """Push a listing's saved content to a channel. Dry run unless --apply.

    Hostaway saves an edit without sending it onward: only booking settings reach a
    channel on their own, so content, amenities and captions stay invisible to guests
    until they are exported. This is the one hsctl command whose effect is on the
    channel rather than on Hostaway, which is why it previews first like any write.
    """

    async def run(session: HostawaySession) -> None:
        _channel_facing_notice(listing_id, channel)
        if not apply:
            _dry_run_notice()
            return
        if not await export_listing_to_airbnb(session, listing_id):
            typer.secho(
                f"Export to {channel.value} FAILED — nothing reached the channel.",
                fg=typer.colors.RED,
                bold=True,
                err=True,
            )
            raise typer.Exit(code=HOSTAWAY_EXIT_CODE)
        _export_triggered_notice(channel)

    _with_session(run)


# --- the write gate --------------------------------------------------------


def _gate(changes: Sequence[Change], *, apply: bool, allow_protected: bool) -> bool:
    """Judge a previewed write and say whether the caller may send it.

    The command has already shown the diff — an operator can always see what it
    would do. What is decided here is whether it goes: a change that touches a
    protected field says so, and asking to apply one without ``--allow-protected``
    stops the command dead, with nothing sent (docs/adr/0001).

    Every mutating command ends here, ``create`` included: what makes a write
    protected is a protected field in the change, never the name of the command that
    built it.
    """
    protected = protected_fields_in(changes)
    if protected:
        typer.secho(
            f"Protected fields in this change: {', '.join(protected)}.",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    if protected and apply and not allow_protected:
        typer.secho(
            f"Refusing: {', '.join(protected)} needs --allow-protected as well as "
            "--apply. Nothing sent.",
            fg=typer.colors.RED,
            bold=True,
            err=True,
        )
        raise typer.Exit(code=REFUSED_EXIT_CODE)
    if not apply:
        _dry_run_notice()
        return False
    return True


def _export_intent_notice(listing_id: int, *, export: bool) -> None:
    """Say that a write asked to go on to a channel, while the diff is still a preview.

    ``--export`` is the only thing that carries an ordinary save past Hostaway, so a
    run carrying it is channel-facing from the start. The operator hears that beside
    the diff, where --apply is still untyped, rather than after the export has gone.
    """
    if export:
        _channel_facing_notice(listing_id, Channel.AIRBNB)


async def _maybe_export(session: HostawaySession, listing_id: int, *, export: bool) -> None:
    """Export a listing whose write has just landed, when the operator asked for it.

    Only reached once the read-back agreed, so the write is not in question here: an
    export that fails leaves a listing that is right on Hostaway and stale on the
    channel. That is worth its own exit code and its own sentence — an operator told
    only "failed" re-runs the write, which repairs nothing.
    """
    if not export:
        return
    if await export_listing_to_airbnb(session, listing_id):
        _export_triggered_notice(Channel.AIRBNB)
        return
    typer.secho(
        f"Export to {Channel.AIRBNB.value} FAILED — but the write applied and was verified. "
        f"The listing is saved on Hostaway and stale on the channel; "
        f"re-run: hsctl export {listing_id} --apply",
        fg=typer.colors.RED,
        bold=True,
        err=True,
    )
    raise typer.Exit(code=EXPORT_EXIT_CODE)


def _channel_facing_notice(listing_id: int, channel: Channel) -> None:
    """Say what an export does, before it is previewed or sent.

    An operator reading a diff is looking at Hostaway; an export is the moment the
    listing reaches the place guests read it. The command says so every time rather
    than only when it is about to send, because the preview is where the decision is.
    """
    typer.secho(
        f"Channel-facing: this pushes listing {listing_id}'s saved content to "
        f"{channel.value}, where guests see it.",
        fg=typer.colors.YELLOW,
        bold=True,
    )


def _export_triggered_notice(channel: Channel) -> None:
    """Say that the export was accepted, and that the channel is not there yet.

    Hostaway queues the export and answers immediately, so "triggered" is the whole
    of what this command can promise: the channel catches up minutes later.
    """
    typer.secho(
        f"Export to {channel.value} triggered — the channel reflects it in a few minutes.",
        fg=typer.colors.GREEN,
        bold=True,
    )


def _dry_run_notice() -> None:
    """Say that a previewed write has not been sent."""
    typer.secho(
        "DRY RUN — nothing sent. Re-run with --apply to send it.",
        fg=typer.colors.YELLOW,
        bold=True,
    )


def _report_readback(observations: Sequence[Observation]) -> None:
    """Print what the listing carries after an applied write, and stop if a field is gone."""
    typer.echo("Applied. Read-back:")
    for line in render_readback(observations):
        typer.echo(line)
    missing = dropped(observations)
    if missing:
        typer.secho(f"Dropped by Hostaway: {', '.join(missing)}.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=HOSTAWAY_EXIT_CODE)
    typer.secho("Verified.", fg=typer.colors.GREEN, bold=True)


def _plural(count: int, noun: str) -> str:
    """``2 fields``, ``1 field`` — a count reads wrong without its noun agreeing."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


# --- what a command reads from its arguments and from the listing ----------


def _backfill_plan(
    payload: Mapping[str, Any],
    listing: Mapping[str, Any],
    config: Configuration,
    *,
    force: bool,
) -> tuple[list[Change], list[str]]:
    """Which configured values this listing still wants, and which it already answers.

    Two reasons a configured value is not written. A field already holding it is not a
    change at all. A fill-only-if-empty field holding anything else is a change the
    operator made on purpose, and a house default is a convention rather than a
    correction: it fills the gap and stops there (docs/adr/0002). ``force`` drops the
    second rule and writes the configured value over what is there.

    The second list is those held-back fields, so the diff can say what it did not do.
    """
    changes: list[Change] = []
    held: list[str] = []
    for field, value in payload.items():
        # Projected onto what a write sends: Hostaway hands every row of an array
        # field an ID and a back-reference of its own, and a bed configuration
        # compared whole would read as a change on a listing that already carries it.
        before = _as_sent(value, listing.get(field))
        if same_value(before, value):
            continue
        if not force and config.is_fill_only_if_empty(field) and not _is_empty(before):
            held.append(field)
            continue
        changes.append(
            Change(field=field, before=before, after=value, secret=field in SECRET_FIELDS)
        )
    return changes, held


def _is_empty(value: Any) -> bool:
    """Has the listing no value here yet?

    Absent, null, blank text and an empty array are gaps. A zero and a ``False`` are
    not: ``sameDayBookingLeadTime: 0`` is midnight, and a backfill that read it as
    silence would overwrite an answer with a convention.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | dict):
        return not value
    return False


def _wifi_password(draft: Mapping[str, Any], *, apply: bool) -> str | None:
    """The wifi password from the environment, and what to do when it is not there.

    A password is a secret, so it never lives in a draft that is committed to a
    repository and never arrives as an argument that survives in shell history: the
    environment is the only way in. Its absence stops a write and not a dry run —
    an operator who cannot see the diff cannot approve the write they are being
    asked to approve — so the refusal is here and the dry run's warning is in
    :func:`_wifi_notice`, which runs where the operator is reading the diff.

    Both are scoped to the draft, deliberately. A configuration whose house defaults
    name ``wifiUsername`` writes that network name on its own, because a house default
    is a standing choice the operator made for every listing on the account, while a
    draft is one property written down in one sitting by someone who may simply not
    have exported the password yet.
    """
    secret = os.environ.get(WIFI_PASSWORD_ENV, "")
    if secret.strip():
        return secret
    if apply and draft.get("wifi_ssid"):
        raise typer.BadParameter(
            f"The draft names a wifi network but {WIFI_PASSWORD_ENV} is unset. "
            "Refusing to publish a network name with no password."
        )
    return None


def _wifi_notice(draft: Mapping[str, Any], wifi_password: str | None) -> None:
    """Say that a network name in the diff is missing the password that belongs with it."""
    if draft.get("wifi_ssid") and wifi_password is None:
        typer.secho(
            f"{WIFI_PASSWORD_ENV} is unset, so wifiPassword is absent from this dry run. "
            "Set it before --apply, or the network name goes up without its password.",
            fg=typer.colors.YELLOW,
        )


def _parse_fields(assignments: Sequence[str]) -> dict[str, Any]:
    """Repeated ``--field KEY=VALUE`` options as wire keys and wire-typed values."""
    fields: dict[str, Any] = {}
    for assignment in assignments:
        key, separator, value = assignment.partition("=")
        if not separator or not key.strip():
            raise typer.BadParameter(f"--field wants KEY=VALUE, got {assignment!r}")
        fields[key.strip()] = _wire_value(value)
    return fields


def _wire_value(value: str) -> Any:
    """A command-line string as the type Hostaway stores it under.

    Hostaway reads numbers and flags back as numbers, so a quoted "23" would be sent
    as text and then reported dropped by the read-back on a write it accepted. Flags
    go as the integer enum 0/1: JSON true can be discarded outright. Anything that is
    not a JSON number or boolean stays a string — a villa name is not JSON.
    """
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    if isinstance(parsed, bool):
        return int(parsed)
    return parsed if isinstance(parsed, int | float) else value


def _caption_plan(plan_path: Path) -> dict[int, str]:
    """The plan file as photo ID to caption, or a refusal naming what is wrong with it."""
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise typer.BadParameter(f"Caption plan is not valid JSON: {error}") from error
    if not isinstance(plan, list) or not all(isinstance(row, dict) for row in plan):
        raise typer.BadParameter("Caption plan must be a JSON array of {id, caption} objects.")
    try:
        wanted = {int(row["id"]): str(row["caption"]) for row in plan}
    except (KeyError, TypeError, ValueError) as error:
        raise typer.BadParameter(f"Every caption plan row needs id and caption: {error}") from error
    if blank := sorted(image_id for image_id, text in wanted.items() if not text.strip()):
        raise typer.BadParameter(f"Blank caption for photo ids: {blank}")
    return wanted


def _captions_of(image: Mapping[str, Any]) -> dict[str, Any]:
    """The four captions one photo carries, which is what a caption write controls."""
    return {field: image.get(field) for field in CAPTION_FIELDS}


def _sort_order(image: Mapping[str, Any]) -> int:
    """Where a photo sits in the listing's own order."""
    order = image.get("sortOrder")
    return order if isinstance(order, int) else 0


def _values_across(days: Sequence[Mapping[str, Any]], field: str) -> list[Any]:
    """The distinct values a field holds across the range, so a diff shows what it hides."""
    seen: list[Any] = []
    for day in days:
        value = day.get(field)
        if value not in seen:
            seen.append(value)
    return sorted(seen, key=repr)


def _resolve_catalog(
    catalog: Sequence[Mapping[str, Any]], tokens: Sequence[Any], *, kind: str
) -> list[int]:
    """Catalog IDs for what the operator typed or wrote: a catalog name, or an ID.

    An ID the account's catalog does not publish is refused rather than sent: it is a
    valid number that stands for another row, or for none at all. Names match
    whatever their case; order is the caller's, because a bed configuration is read
    back positionally.
    """
    by_name = {str(row["name"]).lower(): int(row["id"]) for row in catalog}
    known = set(by_name.values())
    resolved: list[int] = []
    for token in tokens:
        text = str(token).strip()
        if text.isdigit() and int(text) in known:
            resolved.append(int(text))
        elif text.lower() in by_name:
            resolved.append(by_name[text.lower()])
        else:
            raise typer.BadParameter(f"Unknown {kind}: {token!r}")
    return resolved


def _draft(path: Path, *, required: Mapping[str, str] = REQUIRED_DRAFT_KEYS) -> dict[str, Any]:
    """The listing draft, or a refusal naming the key that is missing or misshapen.

    Read before a session exists, so a draft that cannot become a listing costs no
    Hostaway call: the whole point of the checks here is that nothing is sent — not
    even the catalog reads a create makes before it builds anything.

    ``required`` is the set of keys the caller cannot do without. A create needs a
    title; a backfill adds to a listing that
    already has all three, so it passes none.
    """
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise typer.BadParameter(f"{path} is not valid YAML: {error}") from error
    if not isinstance(document, dict):
        raise typer.BadParameter(f"{path} must be a YAML mapping describing one listing.")
    for key, purpose in required.items():
        if not document.get(key):
            raise typer.BadParameter(f"{path} has no {key}: {purpose}.")
    for key, (shape, expected) in DRAFT_SHAPES.items():
        value = document.get(key)
        if value is not None and not isinstance(value, shape):
            raise typer.BadParameter(f"{path}: {key} must be {expected}.")
    for index, bed in enumerate(document.get("bed_config") or []):
        if not isinstance(bed, Mapping):
            raise typer.BadParameter(
                f"{path}: bed_config[{index}] must be a mapping of room_id, bed_type "
                "and quantity, not one name on its own."
            )
    return document


async def _bed_type_ids(session: HostawaySession, draft: Mapping[str, Any]) -> dict[str, int]:
    """The draft's own bed labels mapped to this account's bed-type IDs."""
    labels = [str(bed.get("bed_type")) for bed in draft.get("bed_config") or []]
    if not labels:
        return {}
    ids = _resolve_catalog(await session.get_bed_types(), labels, kind="bed type")
    return dict(zip(labels, ids, strict=True))


async def _map_link_field_id(session: HostawaySession, draft: Mapping[str, Any]) -> int | None:
    """The custom-field ID the map link is written under, if the draft names one.

    A custom field ID belongs to the account that published it, so the draft names
    the field and the account's catalog answers with the number. A draft that names
    no field, or carries no link, writes no custom field at all.
    """
    field_name = draft.get("map_link_custom_field")
    address = draft.get("address") or {}
    if not field_name or not address.get("google_map_link"):
        return None
    catalog = await session.get_custom_fields()
    return _resolve_catalog(catalog, [field_name], kind="listing custom field")[0]


async def _refuse_duplicate_name(session: HostawaySession, title: str) -> None:
    """Stop if the account already has a listing of this name.

    A create cannot be retried and cannot be taken back, and two listings of the
    same name are indistinguishable in every table an operator reads afterwards.
    """
    offset = 0
    for _ in range(MAX_LISTING_PAGES):
        try:
            page = await session.list_listings_page(limit=LISTING_PAGE_SIZE, offset=offset)
        except HostawayPaginationError as error:
            # The strict seam names the contract Hostaway broke, which is the right
            # thing to keep and the wrong thing to hand an operator on its own.
            _stop(
                ValueError(
                    f"Hostaway did not answer a page this walk can trust ({error.code}), "
                    f"so a listing named {title!r} cannot be ruled out. Nothing sent."
                ),
                HOSTAWAY_EXIT_CODE,
            )
        if any(str(listing.get("name")) == title for listing in page.result):
            raise typer.BadParameter(
                f"A listing named {title!r} already exists on this account; "
                "refusing to create a second one."
            )
        offset = page.next_offset
        if offset >= page.count:
            return
    raise typer.BadParameter(
        f"Could not read the whole account within {MAX_LISTING_PAGES} pages, so a "
        "listing of this name cannot be ruled out. Nothing sent."
    )


def _as_sent(sent: Any, observed: Any) -> Any:
    """A read-back row projected onto the keys the write actually sent.

    Hostaway gives every row of a sub-resource array an ID of its own and a
    back-reference to the listing, neither of which a create sends, so comparing
    whole rows would report a field dropped on a write that landed perfectly.
    """
    if not isinstance(sent, list) or not isinstance(observed, list) or len(sent) != len(observed):
        return observed
    return [
        {key: row.get(key) for key in sent_row}
        if isinstance(sent_row, Mapping) and isinstance(row, Mapping)
        else row
        for sent_row, row in zip(sent, observed, strict=True)
    ]


def _amenity_ids(listing: Mapping[str, Any], listing_id: int) -> list[int]:
    """The same IDs ``listing-amenities`` reads, for a command that merges them.

    A read may print what it could resolve and stop there; a merge may not. An
    absent array is not an empty one, and a write sends the whole set, so a set
    computed from a guess would delete every amenity the listing actually has.
    """
    if not isinstance(listing.get("listingAmenities"), list):
        _stop(
            ValueError(
                f"Listing {listing_id} came back without a readable amenity set; "
                "refusing to compute a merge that could delete every amenity."
            ),
            HOSTAWAY_EXIT_CODE,
        )
    return _listing_amenity_ids(listing)


def _amenity_lines(
    current: Sequence[int],
    merged: Sequence[int],
    added: Sequence[int],
    removed: Sequence[int],
    names: Mapping[int, str],
) -> list[str]:
    """The amenity diff: the whole set before and after, and what moved."""
    return [
        f"  before ({len(current)}): {_named(current, names)}",
        f"  after  ({len(merged)}): {_named(merged, names)}",
        f"  + added:   {_named(sorted(set(added) - set(current)), names)}",
        f"  - removed: {_named(sorted(set(removed) & set(current)), names)}",
    ]


def _amenity_notices(
    current: Sequence[int],
    added: Sequence[int],
    removed: Sequence[int],
    names: Mapping[int, str],
) -> list[str]:
    """What was asked for that the listing's own set makes a no-op."""
    notices = []
    if absent := sorted(set(removed) - set(current)):
        notices.append(f"Not on the listing, so not removed: {_named(absent, names)}.")
    if present := sorted(set(added) & set(current)):
        notices.append(f"Already on the listing, so not added: {_named(present, names)}.")
    return notices


def _named(amenity_ids: Sequence[int], names: Mapping[int, str]) -> str:
    """Amenity IDs as ``id:name`` pairs, because an ID alone names nothing."""
    return ", ".join(f"{a}:{names.get(a, '?')}" for a in amenity_ids) or "(none)"


# --- session and rendering -------------------------------------------------


def _configuration() -> Configuration:
    """The operator's house defaults, or a refusal naming what to fix.

    A create merges the operator's own values into every payload and this package
    ships none of its own, so an absent or unreadable configuration stops the
    command before a session exists — nothing is sent (docs/adr/0002).
    """
    try:
        return load_config()
    except ConfigError as error:
        _refuse(error)


def _with_session(operation: Callable[[HostawaySession], Awaitable[None]]) -> None:
    """Run one operation against a freshly built session, then close it."""

    async def runner() -> None:
        session = _build_session()
        try:
            await operation(session)
        finally:
            await session.aclose()

    try:
        asyncio.run(runner())
    except HostawayError as error:
        _stop(error, HOSTAWAY_EXIT_CODE)


def _build_session() -> HostawaySession:
    """The session this command runs on, announced before it is used."""
    try:
        credentials = load_credentials()
    except CredentialsError as error:
        _refuse(error)
    _announce(credentials)
    try:
        return HostawaySession(
            account_id=credentials.account_id,
            secret_key=credentials.secret_key,
            base_url=credentials.base_url,
            token_cache=_token_cache(credentials),
        )
    except TokenCacheError as error:
        _refuse(error)


def _token_cache(credentials: Credentials) -> TokenCache | None:
    """The token cache this account is configured to use, if any."""
    if credentials.token_cache_path is None:
        return None
    return TokenCache(path=credentials.token_cache_path, account_id=credentials.account_id)


def _refuse(error: Exception) -> NoReturn:
    """Report a setup problem the operator has to fix, and stop."""
    _stop(error, SETUP_EXIT_CODE)


def _stop(error: Exception, code: int) -> NoReturn:
    """Say what went wrong on stderr, in one line, and exit with ``code``."""
    typer.secho(str(error), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=code)


def _announce(credentials: Credentials) -> None:
    """Say which account and which surface, on stderr, before anything is sent."""
    surface = credentials.surface
    typer.secho(
        f"hsctl {surface} | account {credentials.account_id} | {credentials.base_url}",
        fg=typer.colors.RED if surface is Surface.LIVE else typer.colors.CYAN,
        err=True,
    )


def _total_line(total: int, *, shown: int, noun: str) -> str:
    """How many rows are printed, and out of how many when that differs.

    Counts what is on the page first, because that is the one number this command
    can prove. The account total is Hostaway's, and a session that could not read
    it reports zero, which must never be mistaken for an empty account.
    """
    if shown < total:
        return f"{shown} of {total} {noun}"
    return f"{shown} {noun}"


def _row(listing_id: str, name: str, internal: str, channel: str) -> str:
    return (
        f"{listing_id:>{ID_WIDTH}}  {name:<{NAME_WIDTH}}  {internal:<{INTERNAL_WIDTH}}  {channel}"
    )


def _listing_amenity_ids(listing: Mapping[str, Any]) -> list[int]:
    """The amenity IDs a listing carries, in ascending order.

    A row's own ``id`` is the ID of the *attachment* of an amenity to this
    listing, not of the amenity: only ``amenityId`` names something the catalog
    can resolve, so a row without one is not counted rather than guessed at.
    """
    rows = listing.get("listingAmenities") or []
    ids = {
        row["amenityId"]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("amenityId"), int)
    }
    return sorted(ids)


def _amenity_row(amenity_id: str, name: str) -> str:
    return f"{amenity_id:>{ID_WIDTH}}  {name}"


def _calendar_row(
    day: str, available: str, price: str, minimum: str, maximum: str, closed: str, note: str
) -> str:
    return (
        f"{day:<{DATE_WIDTH}}  {available:<{AVAIL_WIDTH}}  {price:>{PRICE_WIDTH}}  "
        f"{minimum:>{STAY_WIDTH}}  {maximum:>{STAY_WIDTH}}  {closed:<{CLOSED_WIDTH}}  {note}"
    )


def _flag(value: Any) -> str:
    """Hostaway's 0/1 calendar flag as yes or no.

    Anything else is blank rather than guessed: a day whose availability this
    command could not read must not be printed as one that is closed.
    """
    if value is True or value == 1:
        return "yes"
    if value is False or value == 0:
        return "no"
    return BLANK


def _closures(day: dict[str, Any]) -> str:
    """Which ends of a stay this day is closed on, if either."""
    marks = [
        name
        for name, key in (("arrival", "closedOnArrival"), ("departure", "closedOnDeparture"))
        if day.get(key) is True or day.get(key) == 1
    ]
    return ", ".join(marks) if marks else BLANK


def _cell(value: Any, width: int | None) -> str:
    """One column's text: never empty, never wider than its column."""
    text = BLANK if value is None or value == "" else str(value)
    if width is not None and len(text) > width:
        return text[: width - 1] + "…"
    return text
