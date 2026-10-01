"""``hsctl calendar-set``: stays and closures are ordinary, availability is not.

The gate is evaluated on the change rather than on the command, and this is the
command where that distinction is visible: the same command is an ordinary write
or a protected one depending on which fields the operator named.
"""

from __future__ import annotations

import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import (
    calendar_day,
    cli_env,
    mock_access_tokens,
    mock_endpoint,
    ok,
    plain,
    sent_body,
)

runner = CliRunner()

RANGE = ["--start", "2026-08-01", "--end", "2026-08-02"]


def test_setting_only_a_minimum_stay_is_an_ordinary_write(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001/calendar",
        steps=[
            ok([calendar_day("2026-08-01", minimum_stay=2), calendar_day("2026-08-02")]),
            ok(
                [
                    calendar_day("2026-08-01", minimum_stay=3),
                    calendar_day("2026-08-02", minimum_stay=3),
                ]
            ),
        ],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001/calendar", steps=[ok({})])

    result = runner.invoke(
        app, ["calendar-set", "1001", *RANGE, "--min-stay", "3", "--apply"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert sent_body(put) == {
        "minimumStay": 3,
        "startDate": "2026-08-01",
        "endDate": "2026-08-02",
    }
    assert "minimum stay: stored" in plain(result.stdout)


def test_setting_availability_is_protected(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001/calendar",
        steps=[ok([calendar_day("2026-08-01"), calendar_day("2026-08-02")])],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001/calendar", steps=[ok({})])

    result = runner.invoke(
        app, ["calendar-set", "1001", *RANGE, "--blocked", "--apply"], env=cli_env()
    )

    assert result.exit_code != 0, result.output
    assert "calendar availability" in plain(result.output)
    assert "--allow-protected" in plain(result.output)
    assert not put.called


def test_availability_is_sent_once_the_protected_flag_is_given(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001/calendar",
        steps=[
            ok([calendar_day("2026-08-01"), calendar_day("2026-08-02")]),
            ok(
                [
                    calendar_day("2026-08-01", is_available=0),
                    calendar_day("2026-08-02", is_available=0),
                ]
            ),
        ],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001/calendar", steps=[ok({})])

    result = runner.invoke(
        app,
        ["calendar-set", "1001", *RANGE, "--blocked", "--apply", "--allow-protected"],
        env=cli_env(),
    )

    assert result.exit_code == 0, result.output
    assert sent_body(put) == {
        "isAvailable": 0,
        "startDate": "2026-08-01",
        "endDate": "2026-08-02",
    }
    assert "availability: stored" in plain(result.stdout)


def test_a_dry_run_shows_what_the_range_currently_holds_and_sends_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    """A range write overwrites days the operator cannot see; it has to show them."""
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001/calendar",
        steps=[
            ok(
                [
                    calendar_day("2026-08-01", minimum_stay=2),
                    calendar_day("2026-08-02", minimum_stay=5),
                ]
            )
        ],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001/calendar", steps=[ok({})])

    result = runner.invoke(app, ["calendar-set", "1001", *RANGE, "--min-stay", "3"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert "2026-08-01..2026-08-02 (2 days)" in plain(result.stdout)
    assert "minimum stay: [2, 5] -> 3" in plain(result.stdout)
    assert "DRY RUN" in plain(result.stdout)
    assert not put.called
