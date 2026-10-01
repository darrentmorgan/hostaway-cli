"""``hsctl reservation-lookup``, driven through the CLI test runner (seam 1).

The headline behaviour is what is *not* printed: every mocked reservation here
carries a guest name, a guest email and a phone number, so an assertion that
none of them reaches the terminal is a real assertion rather than a hope.
"""

from __future__ import annotations

import json

import pytest
import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import cli_env, mock_access_tokens, mock_endpoint, ok, reservation

runner = CliRunner()

WINDOW = ["--departure-start", "2026-07-01", "--departure-end", "2026-07-31"]


def personal_values(booking: dict[str, object]) -> list[str]:
    """The planted guest details that must never appear in the output."""
    return [str(booking[key]) for key in ("guestName", "guestEmail", "phone", "guestAddress")]


def test_reservation_lookup_prints_only_the_safe_reservation_fields(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    booking = reservation()
    mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok([booking])])

    result = runner.invoke(app, ["reservation-lookup", *WINDOW], env=cli_env())

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {
            "id": 5001,
            "reservationId": "HA-5001",
            "channelReservationId": "CH-5001",
            "channelName": "airbnbOfficial",
            "listingMapId": 1001,
            "listingName": "Villa Saka",
            "arrivalDate": "2026-07-01",
            "departureDate": "2026-07-05",
            "status": "new",
            "totalPrice": 1375.0,
            "currency": "AUD",
            "currencyCode": "AUD",
            "paymentStatus": "Paid",
        }
    ]
    for planted in personal_values(booking):
        assert planted not in result.stdout
        assert planted not in result.stderr


def test_reservation_lookup_asks_hostaway_for_one_listing_when_given_one(
    respx_mock: respx.MockRouter,
) -> None:
    """The window is the bound; a listing narrows it, and both go to Hostaway."""
    mock_access_tokens(respx_mock)
    booking = reservation(listing_id=1002, listing_name="Villa Nira")
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok([booking])])

    result = runner.invoke(app, ["reservation-lookup", *WINDOW, "--listing", "1002"], env=cli_env())

    assert result.exit_code == 0, result.output
    query = dict(route.calls[0].request.url.params)
    assert query["listingId"] == "1002"
    assert query["departureStartDate"] == "2026-07-01"
    assert query["departureEndDate"] == "2026-07-31"
    assert json.loads(result.stdout)[0]["listingName"] == "Villa Nira"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        pytest.param("2026-07-31", "2026-07-01", id="ends_before_it_starts"),
        pytest.param("last tuesday", "2026-07-31", id="not_a_date"),
        pytest.param("2026-01-01", "2027-06-01", id="wider_than_a_year"),
    ],
)
def test_reservation_lookup_refuses_a_window_it_cannot_bound(
    respx_mock: respx.MockRouter, start: str, end: str
) -> None:
    """The window bounds the search, so an unbounded one is refused before sending."""
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok([reservation()])])

    result = runner.invoke(
        app,
        ["reservation-lookup", "--departure-start", start, "--departure-end", end],
        env=cli_env(),
    )

    assert result.exit_code == 2, result.output
    assert not route.called


def test_reservation_lookup_walks_on_while_hostaway_keeps_filling_the_page(
    respx_mock: respx.MockRouter,
) -> None:
    """A full page means there may be more; a short one means the window is exhausted."""
    mock_access_tokens(respx_mock)
    full_page = [reservation(5000 + n) for n in range(100)]
    last_page = [reservation(5100)]
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok(full_page), ok(last_page)])

    result = runner.invoke(app, ["reservation-lookup", *WINDOW], env=cli_env())

    assert result.exit_code == 0, result.output
    printed = json.loads(result.stdout)
    assert len(printed) == 101
    assert printed[-1]["id"] == 5100
    assert [dict(call.request.url.params)["offset"] for call in route.calls] == ["0", "100"]


def test_reservation_lookup_stops_rather_than_crawl_a_window_without_an_end(
    respx_mock: respx.MockRouter,
) -> None:
    """Every page comes back full: the command gives up and says how to fix it."""
    mock_access_tokens(respx_mock)
    full_page = [reservation(5000 + n) for n in range(100)]
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok(full_page)])

    result = runner.invoke(app, ["reservation-lookup", *WINDOW], env=cli_env())

    assert result.exit_code == 2, result.output
    assert len(route.calls) == 20
    assert "narrow" in result.stderr.lower()
    assert result.stdout.strip() == ""


def test_reservation_lookup_narrows_to_the_reservations_it_was_asked_for(
    respx_mock: respx.MockRouter,
) -> None:
    """A reservation is named by its Hostaway ID or by either channel ID it carries."""
    mock_access_tokens(respx_mock)
    page = [reservation(5001), reservation(5002), reservation(5003)]
    mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok(page)])

    result = runner.invoke(
        app,
        [
            "reservation-lookup",
            *WINDOW,
            "--reservation-id",
            "CH-5003",
            "--reservation-id",
            "5001",
        ],
        env=cli_env(),
    )

    assert result.exit_code == 0, result.output
    assert [booking["id"] for booking in json.loads(result.stdout)] == [5003, 5001]


def test_reservation_lookup_names_what_the_window_does_not_hold(
    respx_mock: respx.MockRouter,
) -> None:
    """Printing three rows where four were asked for is how a reconciliation goes wrong."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok([reservation(5001)])])

    result = runner.invoke(
        app,
        [
            "reservation-lookup",
            *WINDOW,
            "--reservation-id",
            "HA-5001",
            "--reservation-id",
            "CH-9999",
        ],
        env=cli_env(),
    )

    assert result.exit_code == 2, result.output
    assert "CH-9999" in result.stderr
    assert result.stdout.strip() == ""


def test_reservation_lookup_stops_reading_once_it_has_what_it_was_asked_for(
    respx_mock: respx.MockRouter,
) -> None:
    """A full first page holds the named reservation, so the second is never fetched."""
    mock_access_tokens(respx_mock)
    full_page = [reservation(5000 + n) for n in range(100)]
    route = mock_endpoint(
        respx_mock, "GET", "/reservations", steps=[ok(full_page), ok([reservation(5200)])]
    )

    result = runner.invoke(
        app, ["reservation-lookup", *WINDOW, "--reservation-id", "HA-5007"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert [booking["id"] for booking in json.loads(result.stdout)] == [5007]
    assert len(route.calls) == 1


def test_reservation_lookup_refuses_more_reservation_ids_than_it_will_search_for(
    respx_mock: respx.MockRouter,
) -> None:
    """Fifty is a reconciliation; more than that is an export, and is refused."""
    mock_access_tokens(respx_mock)
    route = mock_endpoint(respx_mock, "GET", "/reservations", steps=[ok([reservation()])])
    named = [arg for n in range(51) for arg in ("--reservation-id", f"HA-{6000 + n}")]

    result = runner.invoke(app, ["reservation-lookup", *WINDOW, *named], env=cli_env())

    assert result.exit_code == 2, result.output
    assert not route.called
