"""``hsctl calendar``, driven through the CLI test runner (seam 1).

A calendar day carries availability, price, the stay bounds, the two closures
and a note, and every one of them is something an operator later writes back
with ``calendar-set``.  So the read prints all of them, and prints nothing it
cannot actually read: a blank is a blank, never a guessed ``no``.
"""

from __future__ import annotations

import re

import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import calendar_day, cli_env, mock_access_tokens, mock_endpoint, ok

runner = CliRunner()


def cells(line: str) -> list[str]:
    """One table row split back into its columns, on the two-space gutter."""
    return re.split(r"\s{2,}", line.strip())


def test_calendar_renders_one_row_for_every_day_hostaway_returns(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    days = [
        calendar_day("2026-07-01"),
        calendar_day("2026-07-02", is_available=0, note="Owner stay"),
    ]
    route = mock_endpoint(respx_mock, "GET", "/listings/1001/calendar", steps=[ok(days)])

    result = runner.invoke(
        app,
        ["calendar", "1001", "--start", "2026-07-01", "--end", "2026-07-02"],
        env=cli_env(),
    )

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "2 days 2026-07-01..2026-07-02"
    assert cells(lines[1]) == ["DATE", "AVAIL", "PRICE", "MIN", "MAX", "CLOSED", "NOTE"]
    assert cells(lines[2]) == ["2026-07-01", "yes", "275", "2", "30", "-", "-"]
    assert cells(lines[3]) == ["2026-07-02", "no", "275", "2", "30", "-", "Owner stay"]
    assert dict(route.calls[0].request.url.params) == {
        "startDate": "2026-07-01",
        "endDate": "2026-07-02",
    }


def test_calendar_names_the_end_of_a_stay_each_day_is_closed_on(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    days = [
        calendar_day("2026-07-01", closed_on_arrival=1),
        calendar_day("2026-07-02", closed_on_departure=1),
        calendar_day("2026-07-03", closed_on_arrival=1, closed_on_departure=1),
    ]
    mock_endpoint(respx_mock, "GET", "/listings/1001/calendar", steps=[ok(days)])

    result = runner.invoke(
        app,
        ["calendar", "1001", "--start", "2026-07-01", "--end", "2026-07-03"],
        env=cli_env(),
    )

    assert result.exit_code == 0, result.output
    closures = [cells(line)[5] for line in result.stdout.splitlines()[2:]]
    assert closures == ["arrival", "departure", "arrival, departure"]


def test_calendar_leaves_blank_what_hostaway_did_not_send(
    respx_mock: respx.MockRouter,
) -> None:
    """An availability this command cannot read is not a day that is closed."""
    mock_access_tokens(respx_mock)
    day = calendar_day("2026-07-01", isAvailable=None, price=None, maximumStay=None)
    mock_endpoint(respx_mock, "GET", "/listings/1001/calendar", steps=[ok([day])])

    result = runner.invoke(
        app,
        ["calendar", "1001", "--start", "2026-07-01", "--end", "2026-07-01"],
        env=cli_env(),
    )

    assert result.exit_code == 0, result.output
    assert cells(result.stdout.splitlines()[2]) == ["2026-07-01", "-", "-", "2", "-", "-", "-"]
