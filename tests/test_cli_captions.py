"""``hsctl captions``: per-photo captions from a plan file.

``listingImages`` is replace-semantics — the array sent becomes the whole photo
set — so the command rebuilds the full array from the live listing. A plan that
omits a live photo is therefore asking for that photo to be deleted, and deleting
a photo is a protected change (docs/adr/0001).
"""

from __future__ import annotations

import json
from pathlib import Path

import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import (
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

LIVE = [photo(501, 1, "Pool at dusk"), photo(502, 2, "Kitchen")]


def plan_file(tmp_path: Path, rows: list[dict[str, object]]) -> str:
    path = tmp_path / "captions.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return str(path)


def test_a_dry_run_names_the_photos_that_change_and_sends_nothing(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, listingImages=LIVE))])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    plan = plan_file(
        tmp_path, [{"id": 501, "caption": "Pool at sunset"}, {"id": 502, "caption": "Kitchen"}]
    )

    result = runner.invoke(app, ["captions", "1001", plan], env=cli_env())

    assert result.exit_code == 0, result.output
    assert "1 of 2 photos change" in plain(result.stdout)
    assert "'Pool at dusk' -> 'Pool at sunset'" in plain(result.stdout)
    assert "DRY RUN" in plain(result.stdout)
    assert not put.called


def test_apply_sends_every_photo_with_all_four_captions(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """The array replaces the whole photo set, so every live photo goes back with it."""
    mock_access_tokens(respx_mock)
    stored = [photo(501, 1, "Pool at sunset"), photo(502, 2, "Kitchen")]
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001, listingImages=LIVE)), ok(villa(1001, listingImages=stored))],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    plan = plan_file(
        tmp_path, [{"id": 501, "caption": "Pool at sunset"}, {"id": 502, "caption": "Kitchen"}]
    )

    result = runner.invoke(app, ["captions", "1001", plan, "--apply"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert sent_body(put) == {
        "listingImages": [
            {
                "id": 501,
                "url": "https://images.hostaway.test/501.jpg",
                "sortOrder": 1,
                "caption": "Pool at sunset",
                "airbnbCaption": "Pool at sunset",
                "vrboCaption": "Pool at sunset",
                "bookingEngineCaption": "Pool at sunset",
            },
            {
                "id": 502,
                "url": "https://images.hostaway.test/502.jpg",
                "sortOrder": 2,
                "caption": "Kitchen",
                "airbnbCaption": "Kitchen",
                "vrboCaption": "Kitchen",
                "bookingEngineCaption": "Kitchen",
            },
        ]
    }
    assert "photo 1: stored" in plain(result.stdout)


def test_a_plan_that_omits_a_live_photo_is_a_protected_deletion(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, listingImages=LIVE))])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    plan = plan_file(tmp_path, [{"id": 501, "caption": "Pool at sunset"}])

    result = runner.invoke(app, ["captions", "1001", plan, "--apply"], env=cli_env())

    assert result.exit_code != 0, result.output
    assert "deletion of a listing photo" in plain(result.output)
    assert "--allow-protected" in plain(result.output)
    assert not put.called


def test_a_plan_naming_a_photo_the_listing_does_not_have_is_refused(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    """An unknown ID is a typo, not a decision, so no flag makes it sendable."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, listingImages=LIVE))])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    plan = plan_file(
        tmp_path,
        [
            {"id": 501, "caption": "Pool at sunset"},
            {"id": 502, "caption": "Kitchen"},
            {"id": 999, "caption": "Garden"},
        ],
    )

    result = runner.invoke(
        app, ["captions", "1001", plan, "--apply", "--allow-protected"], env=cli_env()
    )

    assert result.exit_code != 0, result.output
    assert "999" in plain(result.output)
    assert not put.called


def test_a_blank_caption_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    plan = plan_file(tmp_path, [{"id": 501, "caption": "   "}])

    result = runner.invoke(app, ["captions", "1001", plan, "--apply"], env=cli_env())

    assert result.exit_code != 0, result.output
    assert "501" in plain(result.output)


def test_a_caption_hostaway_did_not_store_is_reported(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    mock_access_tokens(respx_mock)
    # Hostaway answers success and stores the caption on its own field only.
    partial = [
        {**photo(501, 1, "Pool at sunset"), "airbnbCaption": "Pool at dusk"},
        photo(502, 2, "Kitchen"),
    ]
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001, listingImages=LIVE)), ok(villa(1001, listingImages=partial))],
    )
    mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])
    plan = plan_file(
        tmp_path, [{"id": 501, "caption": "Pool at sunset"}, {"id": 502, "caption": "Kitchen"}]
    )

    result = runner.invoke(app, ["captions", "1001", plan, "--apply"], env=cli_env())

    assert result.exit_code != 0, result.output
    assert "photo 1: dropped" in plain(result.stdout)
    assert "Dropped by Hostaway: photo 1." in plain(result.stdout)
