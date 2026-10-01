"""``hsctl export``: pushing a listing's saved content out to a channel (seam 1).

A saved edit is invisible to guests until it is exported, and an export is the
one thing hsctl does that reaches past Hostaway. Every test drives the command
as an operator does and asserts on what the operator sees and on whether the
export request actually left.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import (
    amenity_catalog,
    cli_env,
    mock_access_tokens,
    mock_endpoint,
    ok,
    photo,
    plain,
    sent_body,
    villa,
)

runner = CliRunner()

EXPORT = "/listings/1001/export/airbnb"


def test_export_sends_the_export_and_says_it_is_channel_facing(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[ok({"jobId": 77})])

    result = runner.invoke(app, ["export", "1001", "--apply"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert sent_body(export) == {}
    assert "Channel-facing" in plain(result.stdout)
    assert "airbnb" in plain(result.stdout)


def test_export_previews_and_sends_nothing_by_default(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[ok({"jobId": 77})])

    result = runner.invoke(app, ["export", "1001"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in plain(result.stdout)
    assert not export.called


def test_a_channel_hsctl_cannot_export_to_is_refused_before_anything_is_sent(
    respx_mock: respx.MockRouter,
) -> None:
    """Hostaway exposes one export endpoint per channel; this client carries Airbnb's."""
    mock_access_tokens(respx_mock)
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[ok({"jobId": 77})])

    result = runner.invoke(
        app, ["export", "1001", "--channel", "booking", "--apply"], env=cli_env()
    )

    assert result.exit_code != 0, result.output
    assert "booking" in plain(result.output)
    assert not export.called


def test_an_export_hostaway_refused_fails_the_command(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(404)])

    result = runner.invoke(app, ["export", "1001", "--apply"], env=cli_env())

    assert result.exit_code == 1, result.output
    assert "FAILED" in plain(result.output)


# --- --export on a write ----------------------------------------------------


def test_a_write_with_export_exports_once_the_write_is_read_back(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    renamed = villa(1001, name="Villa Saka Retreat")
    mock_endpoint(
        respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, name="Villa Saka")), ok(renamed)]
    )
    mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok(renamed)])
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    result = runner.invoke(
        app, ["set", "1001", "--name", "Villa Saka Retreat", "--apply", "--export"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert len(export.calls) == 1
    out = plain(result.stdout)
    assert out.index("Verified.") < out.index("Export to airbnb triggered")


def test_a_dry_run_never_exports(respx_mock: respx.MockRouter) -> None:
    """--export follows a write that landed; a dry run has nothing to export."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, name="Villa Saka"))])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    result = runner.invoke(
        app, ["set", "1001", "--name", "Villa Saka Retreat", "--export"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in plain(result.stdout)
    assert not put.called
    assert not export.called


def test_a_write_without_export_reaches_no_channel(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    renamed = villa(1001, name="Villa Saka Retreat")
    mock_endpoint(
        respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, name="Villa Saka")), ok(renamed)]
    )
    mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok(renamed)])
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    result = runner.invoke(
        app, ["set", "1001", "--name", "Villa Saka Retreat", "--apply"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert not export.called


def test_an_export_that_failed_after_a_write_still_reports_the_write_as_applied(
    respx_mock: respx.MockRouter,
) -> None:
    """The write landed. Saying only "failed" would send the operator to redo it."""
    mock_access_tokens(respx_mock)
    renamed = villa(1001, name="Villa Saka Retreat")
    mock_endpoint(
        respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, name="Villa Saka")), ok(renamed)]
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok(renamed)])
    mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(404)])

    result = runner.invoke(
        app, ["set", "1001", "--name", "Villa Saka Retreat", "--apply", "--export"], env=cli_env()
    )

    assert put.called
    assert "name: stored" in plain(result.stdout)
    assert "Verified." in plain(result.stdout)
    assert "Export to airbnb FAILED" in plain(result.output)
    assert "the write applied" in plain(result.output)
    # Its own exit code: nothing was rolled back, and nothing needs re-writing.
    assert result.exit_code == 4, result.output


def test_a_write_hostaway_did_not_store_is_never_exported(respx_mock: respx.MockRouter) -> None:
    """There is nothing worth pushing to a channel until the read-back agrees."""
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001, name="Villa Saka")), ok(villa(1001, name="Villa Saka"))],
    )
    mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    result = runner.invoke(
        app, ["set", "1001", "--name", "Villa Saka Retreat", "--apply", "--export"], env=cli_env()
    )

    assert result.exit_code == 1, result.output
    assert "Dropped by Hostaway: name." in plain(result.stdout)
    assert not export.called


def test_an_amenity_write_with_export_exports_the_merged_set(
    respx_mock: respx.MockRouter,
) -> None:
    """Amenities are content: a save leaves them invisible on the channel."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/amenities", steps=[ok(amenity_catalog())])
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001, amenity_ids=(1, 2, 3))), ok(villa(1001, amenity_ids=(1, 2, 3, 4)))],
    )
    mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    result = runner.invoke(
        app,
        ["amenities-set", "1001", "--add", "Pool towels", "--apply", "--export"],
        env=cli_env(),
    )

    assert result.exit_code == 0, result.output
    assert len(export.calls) == 1
    assert "Export to airbnb triggered" in plain(result.stdout)


def test_a_caption_write_with_export_exports_the_new_captions(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """A caption is the text under a photo on the channel, and a save does not send it."""
    mock_access_tokens(respx_mock)
    live = [photo(501, 1, "Pool at dusk")]
    stored = [photo(501, 1, "Pool at sunset")]
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001, listingImages=live)), ok(villa(1001, listingImages=stored))],
    )
    mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])
    plan = tmp_path / "captions.json"
    plan.write_text(json.dumps([{"id": 501, "caption": "Pool at sunset"}]), encoding="utf-8")

    result = runner.invoke(
        app, ["captions", "1001", str(plan), "--apply", "--export"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert len(export.calls) == 1
    assert "Export to airbnb triggered" in plain(result.stdout)


def test_a_dry_run_with_export_says_the_run_is_channel_facing(
    respx_mock: respx.MockRouter,
) -> None:
    """The preview is where the operator decides, so it has to name the channel."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, name="Villa Saka"))])
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    result = runner.invoke(
        app, ["set", "1001", "--name", "Villa Saka Retreat", "--export"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    out = plain(result.stdout)
    assert "Channel-facing" in out
    assert "airbnb" in out
    assert out.index("Channel-facing") < out.index("DRY RUN")
    assert not export.called


def test_a_write_with_export_says_it_is_channel_facing_before_the_export_leaves(
    respx_mock: respx.MockRouter,
) -> None:
    """Told only afterwards, the operator learns where the listing went too late."""
    mock_access_tokens(respx_mock)
    renamed = villa(1001, name="Villa Saka Retreat")
    mock_endpoint(
        respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, name="Villa Saka")), ok(renamed)]
    )
    mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok(renamed)])
    export = mock_endpoint(respx_mock, "POST", EXPORT, steps=[httpx.Response(204)])

    result = runner.invoke(
        app, ["set", "1001", "--name", "Villa Saka Retreat", "--apply", "--export"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert len(export.calls) == 1
    out = plain(result.stdout)
    # "Verified." is printed after the read-back and before the export request is
    # built, so the notice standing ahead of it stood ahead of the export.
    assert out.index("Channel-facing") < out.index("Verified.")


def test_a_write_without_export_says_nothing_about_a_channel(
    respx_mock: respx.MockRouter,
) -> None:
    """An ordinary save stops at Hostaway; a channel notice there would be a lie."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, name="Villa Saka"))])

    result = runner.invoke(app, ["set", "1001", "--name", "Villa Saka Retreat"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert "Channel-facing" not in plain(result.stdout)
