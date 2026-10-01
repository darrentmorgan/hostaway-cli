"""The demo kit's fake Hostaway server, met by the CLI a contributor will point at it.

Seam 1: the command as an operator types it, through the CLI test runner. What is
swapped out is Hostaway itself, and only Hostaway — the transport, the token fetch
and the HTTP are all real, over a loopback socket to ``scripts/demo/fake_hostaway.py``.
That is the point of this file: the kit's README tells a contributor to start that
server and run ``hsctl listings``, and these tests are what keep the instruction true.

The server is started on port 0, so the tests never collide with a demo the developer
already has running on the kit's own port.
"""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

import fake_hostaway
from hostaway_cli.cli import app
from hostaway_cli.session import HostawaySession
from hostaway_mocks import ACCOUNT_ID, cli_env

runner = CliRunner()


@pytest.fixture
def sandbox() -> Iterator[str]:
    """The demo server running on a free port, as its base URL."""
    server = fake_hostaway.make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake_hostaway.base_url(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_listings_over_the_demo_server_names_the_sandbox_and_the_five_villas(
    sandbox: str,
) -> None:
    result = runner.invoke(app, ["listings"], env=cli_env(HOSTAWAY_API_BASE_URL=sandbox))

    assert result.exit_code == 0, result.output
    assert result.stderr.splitlines()[0] == f"hsctl SANDBOX | account {ACCOUNT_ID} | {sandbox}"
    lines = result.stdout.splitlines()
    assert lines[0] == "5 listings"
    assert [line.split()[0] for line in lines[2:]] == ["1001", "1002", "1003", "1004", "1005"]


def test_listing_amenities_resolves_the_demo_account_catalog_into_names(sandbox: str) -> None:
    """The audit the demo tells: two villas are short of the standing inclusions."""
    result = runner.invoke(
        app, ["listing-amenities", "1003"], env=cli_env(HOSTAWAY_API_BASE_URL=sandbox)
    )

    assert result.exit_code == 0, result.output
    named = dict(row.split(maxsplit=1) for row in result.stdout.splitlines()[2:])
    assert "Smoke detector" not in named.values()
    assert "First aid kit" not in named.values()
    assert "Linens" in named.values()


def test_calendar_answers_a_day_for_every_date_in_the_range(sandbox: str) -> None:
    result = runner.invoke(
        app,
        ["calendar", "1001", "--start", "2027-01-04", "--end", "2027-01-06"],
        env=cli_env(HOSTAWAY_API_BASE_URL=sandbox),
    )

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "3 days 2027-01-04..2027-01-06"
    assert [line.split()[0] for line in lines[2:]] == ["2027-01-04", "2027-01-05", "2027-01-06"]


def test_an_applied_amenity_write_lands_on_the_demo_account_and_reads_back(
    sandbox: str,
) -> None:
    """The beat the demo is about: apply, then re-read rather than trust the answer."""
    env = cli_env(HOSTAWAY_API_BASE_URL=sandbox)
    added = ["--add", "Smoke detector", "--add", "First aid kit"]

    applied = runner.invoke(app, ["amenities-set", "1003", *added, "--apply"], env=env)

    assert applied.exit_code == 0, applied.output
    assert "Verified." in applied.output
    after = runner.invoke(app, ["listing-amenities", "1003"], env=env)
    assert "Smoke detector" in after.stdout
    assert "First aid kit" in after.stdout


def test_a_dry_run_amenity_write_leaves_the_demo_account_alone(sandbox: str) -> None:
    env = cli_env(HOSTAWAY_API_BASE_URL=sandbox)

    previewed = runner.invoke(app, ["amenities-set", "1003", "--add", "Smoke detector"], env=env)

    assert previewed.exit_code == 0, previewed.output
    assert "DRY RUN" in previewed.output
    assert "Smoke detector" not in runner.invoke(app, ["listing-amenities", "1003"], env=env).stdout


def test_a_protected_calendar_write_needs_both_flags_and_then_blocks_the_range(
    sandbox: str,
) -> None:
    """Availability is protected, so the demo shows the refusal before the write."""
    env = cli_env(HOSTAWAY_API_BASE_URL=sandbox)
    window = ["--start", "2027-01-04", "--end", "2027-01-06"]

    refused = runner.invoke(app, ["calendar-set", "1001", *window, "--blocked", "--apply"], env=env)
    applied = runner.invoke(
        app,
        [
            "calendar-set",
            "1001",
            *window,
            "--blocked",
            "--min-stay",
            "5",
            "--apply",
            "--allow-protected",
        ],
        env=env,
    )

    assert refused.exit_code != 0
    assert "Nothing sent" in refused.output
    assert applied.exit_code == 0, applied.output
    assert "Verified." in applied.output
    days = runner.invoke(app, ["calendar", "1001", *window], env=env).stdout.splitlines()[2:]
    assert [line.split()[1] for line in days] == ["no", "no", "no"]
    assert [line.split()[3] for line in days] == ["5", "5", "5"]


def test_reservation_lookup_prints_the_safe_fields_of_the_demo_stays(sandbox: str) -> None:
    result = runner.invoke(
        app,
        [
            "reservation-lookup",
            "--departure-start",
            "2027-01-01",
            "--departure-end",
            "2027-01-31",
        ],
        env=cli_env(HOSTAWAY_API_BASE_URL=sandbox),
    )

    assert result.exit_code == 0, result.output
    stays = json.loads(result.stdout)
    assert [stay["listingMapId"] for stay in stays] == [1001, 1004]
    assert all("guestName" not in stay for stay in stays)
    assert "@" not in result.stdout


def test_the_demo_calendar_shows_the_nights_a_demo_reservation_occupies(sandbox: str) -> None:
    """A stay an operator can look up is a stay they can see on the calendar."""
    result = runner.invoke(
        app,
        ["calendar", "1001", "--start", "2027-01-08", "--end", "2027-01-15"],
        env=cli_env(HOSTAWAY_API_BASE_URL=sandbox),
    )

    assert result.exit_code == 0, result.output
    availability = [line.split()[1] for line in result.stdout.splitlines()[2:]]
    assert availability == ["yes", "no", "no", "no", "no", "no", "yes", "yes"]


@pytest.fixture
async def session(sandbox: str) -> AsyncIterator[HostawaySession]:
    """A session pointed at the demo server, as a library caller builds one."""
    built = HostawaySession(account_id=ACCOUNT_ID, secret_key="demo-not-a-secret", base_url=sandbox)
    try:
        yield built
    finally:
        await built.aclose()


async def test_the_demo_server_publishes_every_catalog_the_session_reads(
    session: HostawaySession,
) -> None:
    """A catalog a caller can ask for is one the demo account has to publish."""
    catalogs = {
        "amenities": await session.get_amenities(),
        "bed types": await session.get_bed_types(),
        "custom fields": await session.get_custom_fields(),
        "property types": await session.get_property_types(),
        "native policies": await session.get_cancellation_policies("native"),
        "airbnb policies": await session.get_cancellation_policies("airbnb"),
    }

    assert all(rows for rows in catalogs.values()), catalogs


async def test_the_demo_server_answers_the_review_and_finance_reads(
    session: HostawaySession,
) -> None:
    reviews, total = await session.get_reviews(listing_map_ids=[1001])
    report = await session.get_consolidated_report(start_date="2027-01-01", end_date="2027-01-31")

    assert [review["listingMapId"] for review in reviews] == [1001]
    assert total == len(reviews)
    assert report.splitlines()[0].startswith("listingName,")


async def test_a_listing_created_against_the_demo_server_joins_the_account(
    session: HostawaySession,
) -> None:
    created = await session.create_listing({"name": "Villa Kenari", "city": "Amed"})

    listing_id = created["result"]["id"]
    assert listing_id > 0
    page, total = await session.list_listings()
    assert total == 6
    assert (await session.get_listing(listing_id))["name"] == "Villa Kenari"
    assert [listing["id"] for listing in page][-1] == listing_id


async def test_an_export_is_accepted_by_the_demo_server(session: HostawaySession) -> None:
    """The demo can show the channel-facing step without a channel hearing about it."""
    assert await session.export_to_airbnb(1001) is not None


async def test_an_uploaded_image_appears_on_the_demo_listing(session: HostawaySession) -> None:
    listing = await session.upload_listing_image(
        1003,
        {"url": "https://images.example.invalid/1003-new.jpg", "caption": "Bale by the water"},
        readback_interval_seconds=0,
    )

    captions = [image["caption"] for image in listing["listingImages"]]
    assert "Bale by the water" in captions


def test_setting_an_ordinary_listing_field_lands_and_reads_back(sandbox: str) -> None:
    env = cli_env(HOSTAWAY_API_BASE_URL=sandbox)

    applied = runner.invoke(app, ["set", "1002", "--max-guests", "9", "--apply"], env=env)

    assert applied.exit_code == 0, applied.output
    assert "Verified." in applied.output
    listing = json.loads(runner.invoke(app, ["get", "1002"], env=env).stdout)
    assert listing["personCapacity"] == 9


def test_captions_reads_the_photos_the_demo_listings_carry(sandbox: str, tmp_path: Path) -> None:
    """``listingImages`` is replace-semantics, so the demo listings need photos on them."""
    env = cli_env(HOSTAWAY_API_BASE_URL=sandbox)
    photos = json.loads(runner.invoke(app, ["get", "1002"], env=env).stdout)["listingImages"]
    plan = tmp_path / "captions.json"
    plan.write_text(
        json.dumps([{"id": photo["id"], "caption": "Pool at dawn"} for photo in photos]),
        encoding="utf-8",
    )

    applied = runner.invoke(app, ["captions", "1002", str(plan), "--apply"], env=env)

    assert applied.exit_code == 0, applied.output
    assert "Verified." in applied.output
    after = json.loads(runner.invoke(app, ["get", "1002"], env=env).stdout)["listingImages"]
    assert [photo["airbnbCaption"] for photo in after] == ["Pool at dawn"] * len(photos)


def test_exporting_a_demo_listing_previews_first_and_then_reaches_the_channel_step(
    sandbox: str,
) -> None:
    """The one command whose effect lands past Hostaway, run where no channel hears it.

    That is what the demo server is for: an export is the beat an operator cannot
    rehearse on a live account, because a rehearsal there is a real push to Airbnb.
    """
    env = cli_env(HOSTAWAY_API_BASE_URL=sandbox)

    previewed = runner.invoke(app, ["export", "1001"], env=env)
    applied = runner.invoke(app, ["export", "1001", "--apply"], env=env)

    assert previewed.exit_code == 0, previewed.output
    assert "DRY RUN" in previewed.output
    assert applied.exit_code == 0, applied.output
    assert "Channel-facing" in applied.output
    assert "Export to airbnb triggered" in applied.output


def test_a_write_that_asks_to_export_lands_on_the_demo_account_and_then_exports(
    sandbox: str,
) -> None:
    """``--export`` is the other way a command reaches a channel, and it goes last."""
    env = cli_env(HOSTAWAY_API_BASE_URL=sandbox)

    applied = runner.invoke(
        app, ["set", "1002", "--max-guests", "8", "--apply", "--export"], env=env
    )

    assert applied.exit_code == 0, applied.output
    assert "Verified." in applied.output
    assert "Export to airbnb triggered" in applied.output
    assert json.loads(runner.invoke(app, ["get", "1002"], env=env).stdout)["personCapacity"] == 8


async def test_the_demo_account_can_be_walked_a_page_at_a_time(session: HostawaySession) -> None:
    """``list_listings_page`` refuses a page wider than it asked for, so the
    stand-in has to page as Hostaway does rather than answer the lot every time."""
    walked: list[int] = []
    offset = 0
    while True:
        page = await session.list_listings_page(limit=2, offset=offset)
        walked.extend(page.listing_ids)
        if page.next_offset >= page.count:
            break
        offset = page.next_offset

    assert walked == [1001, 1002, 1003, 1004, 1005]
