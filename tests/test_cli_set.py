"""``hsctl set``: the write gate over ordinary listing fields (seam 1).

Every test drives the command exactly as an operator does and asserts on what
the operator sees and on what reached the wire — a dry run is proved by the PUT
route never being called, not by inspecting the command.
"""

from __future__ import annotations

import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import cli_env, mock_access_tokens, mock_endpoint, ok, plain, sent_body, villa

runner = CliRunner()


def test_set_previews_the_change_and_sends_nothing(respx_mock: respx.MockRouter) -> None:
    """The default outcome of a write is a diff and an untouched listing."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, name="Villa Saka"))])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(app, ["set", "1001", "--name", "Villa Saka Retreat"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert "name: 'Villa Saka' -> 'Villa Saka Retreat'" in plain(result.stdout)
    assert "DRY RUN" in plain(result.stdout)
    assert not put.called


def test_apply_sends_the_change_and_reads_the_listing_back(respx_mock: respx.MockRouter) -> None:
    mock_access_tokens(respx_mock)
    renamed = villa(1001, name="Villa Saka Retreat")
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001, name="Villa Saka")), ok(renamed)],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok(renamed)])

    result = runner.invoke(
        app, ["set", "1001", "--name", "Villa Saka Retreat", "--apply"], env=cli_env()
    )

    assert result.exit_code == 0, result.output
    assert sent_body(put) == {"name": "Villa Saka Retreat"}
    assert "name: stored" in plain(result.stdout)
    assert "DRY RUN" not in plain(result.stdout)


def test_a_field_hostaway_discarded_is_named_and_the_command_fails(
    respx_mock: respx.MockRouter,
) -> None:
    """Hostaway answers success and stores only part of a write; the read-back says so."""
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[
            ok(villa(1001, name="Villa Saka", city="Ubud")),
            # The write landed on the name and was silently discarded on the city.
            ok(villa(1001, name="Villa Saka Retreat", city="Ubud")),
        ],
    )
    mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(
        app,
        ["set", "1001", "--name", "Villa Saka Retreat", "--city", "Sanur", "--apply"],
        env=cli_env(),
    )

    assert result.exit_code != 0, result.output
    assert "name: stored" in plain(result.stdout)
    assert "city: dropped" in plain(result.stdout)
    assert "Dropped by Hostaway: city." in plain(result.stdout)


def test_a_protected_field_is_refused_without_the_protected_flag(
    respx_mock: respx.MockRouter,
) -> None:
    """--apply is the operator's habit; moving money must take more than a habit."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, price=275))])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(app, ["set", "1001", "--field", "price=575", "--apply"], env=cli_env())

    assert result.exit_code != 0, result.output
    assert "price" in plain(result.output)
    assert "--allow-protected" in plain(result.output)
    assert not put.called


def test_a_protected_field_is_sent_once_the_protected_flag_is_given(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001, price=275)), ok(villa(1001, price=575))],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(
        app,
        ["set", "1001", "--field", "price=575", "--apply", "--allow-protected"],
        env=cli_env(),
    )

    assert result.exit_code == 0, result.output
    assert sent_body(put) == {"price": 575}
    assert "price: stored" in plain(result.stdout)


def test_a_protected_dry_run_names_the_protected_fields_and_sends_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    """An operator can still preview a price change; previewing sends nothing."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/1001", steps=[ok(villa(1001, price=275))])
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(app, ["set", "1001", "--field", "price=575"], env=cli_env())

    assert result.exit_code == 0, result.output
    assert "price: 275 -> 575" in plain(result.stdout)
    assert "protected" in plain(result.stdout).lower()
    assert not put.called


def test_set_needs_a_field_before_it_reaches_hostaway(respx_mock: respx.MockRouter) -> None:
    token = mock_access_tokens(respx_mock)

    result = runner.invoke(app, ["set", "1001"], env=cli_env())

    assert result.exit_code != 0, result.output
    assert not token.called


def test_a_whole_array_field_is_refused_and_points_at_the_command_that_rebuilds_it(
    respx_mock: respx.MockRouter,
) -> None:
    """A raw value here replaces the entire photo set, deleting every photo."""
    token = mock_access_tokens(respx_mock)

    result = runner.invoke(
        app, ["set", "1001", "--field", "listingImages=junk", "--apply"], env=cli_env()
    )

    assert result.exit_code != 0, result.output
    assert "captions" in plain(result.output)
    assert not token.called


def test_a_secret_passed_on_the_command_line_is_refused(respx_mock: respx.MockRouter) -> None:
    """argv survives in shell history and in every process listing on the machine."""
    token = mock_access_tokens(respx_mock)

    result = runner.invoke(
        app, ["set", "1001", "--field", "doorSecurityCode=8341", "--apply"], env=cli_env()
    )

    assert result.exit_code != 0, result.output
    assert "--door-code" in plain(result.output)
    assert not token.called


def test_the_door_code_is_sent_from_the_environment_and_never_printed(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[ok(villa(1001)), ok(villa(1001, doorSecurityCode="8341"))],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(
        app,
        ["set", "1001", "--door-code", "--apply"],
        env=cli_env(HSCTL_DOOR_CODE="8341"),
    )

    assert result.exit_code == 0, result.output
    assert sent_body(put) == {"doorSecurityCode": "8341"}
    assert "8341" not in plain(result.output)
    assert "doorSecurityCode: (unset) -> ***" in plain(result.stdout)


def test_the_door_code_option_refuses_a_blank_environment_variable(
    respx_mock: respx.MockRouter,
) -> None:
    token = mock_access_tokens(respx_mock)

    result = runner.invoke(
        app, ["set", "1001", "--door-code", "--apply"], env=cli_env(HSCTL_DOOR_CODE="   ")
    )

    assert result.exit_code != 0, result.output
    assert "HSCTL_DOOR_CODE" in plain(result.output)
    assert not token.called


def test_a_field_value_is_sent_as_the_type_hostaway_stores_it_under(
    respx_mock: respx.MockRouter,
) -> None:
    """A quoted "4" would be sent as text and then read back as a dropped field."""
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        "/listings/1001",
        steps=[
            ok(villa(1001)),
            ok(villa(1001, bedroomsNumber=4, instantBookable=1, externalListingName="Villa 4")),
        ],
    )
    put = mock_endpoint(respx_mock, "PUT", "/listings/1001", steps=[ok({"id": 1001})])

    result = runner.invoke(
        app,
        [
            "set",
            "1001",
            "--field",
            "bedroomsNumber=4",
            "--field",
            "instantBookable=true",
            "--field",
            "externalListingName=Villa 4",
            "--apply",
        ],
        env=cli_env(),
    )

    assert result.exit_code == 0, result.output
    assert sent_body(put) == {
        "bedroomsNumber": 4,
        "instantBookable": 1,
        "externalListingName": "Villa 4",
    }


def test_a_field_named_twice_is_refused_rather_than_resolved_silently(
    respx_mock: respx.MockRouter,
) -> None:
    """Two spellings of one field in one command is a mistake, not a precedence rule."""
    token = mock_access_tokens(respx_mock)

    result = runner.invoke(
        app,
        ["set", "1001", "--name", "Villa Saka", "--field", "name=Villa Nira", "--apply"],
        env=cli_env(),
    )

    assert result.exit_code != 0, result.output
    assert "name" in plain(result.output)
    assert not token.called
