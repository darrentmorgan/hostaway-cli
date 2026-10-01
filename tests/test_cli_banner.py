"""Every command says which account it is on and whether the surface is real.

The judgement is the base URL's alone (docs/adr/0004), so these drive the CLI
against a mocked Hostaway at each kind of base URL and read the banner back off
stderr, where it stays out of piped or redirected output.
"""

from __future__ import annotations

import pytest
import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_cli.session import HOSTAWAY_API_BASE_URL
from hostaway_mocks import ACCOUNT_ID, BASE_URL, cli_env, mock_access_tokens, mock_endpoint, ok

runner = CliRunner()


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        pytest.param(BASE_URL, "SANDBOX", id="a stand-in host is SANDBOX"),
        pytest.param(HOSTAWAY_API_BASE_URL, "LIVE", id="Hostaway's own host is LIVE"),
    ],
)
def test_the_banner_names_the_surface_from_the_base_url(
    respx_mock: respx.MockRouter, base_url: str, expected: str
) -> None:
    mock_access_tokens(respx_mock, base_url=base_url)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok([], count=0)], base_url=base_url)

    result = runner.invoke(app, ["listings"], env=cli_env(HOSTAWAY_API_BASE_URL=base_url))

    assert result.exit_code == 0, result.output
    assert result.stderr.splitlines()[0] == f"hsctl {expected} | account {ACCOUNT_ID} | {base_url}"


def test_a_look_alike_host_is_not_live(respx_mock: respx.MockRouter) -> None:
    """A host that merely contains Hostaway's own is a stand-in, and says so."""
    base_url = "https://api.hostaway.com.example.test/v1"
    mock_access_tokens(respx_mock, base_url=base_url)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok([], count=0)], base_url=base_url)

    result = runner.invoke(app, ["listings"], env=cli_env(HOSTAWAY_API_BASE_URL=base_url))

    assert result.exit_code == 0, result.output
    assert "SANDBOX" in result.stderr


def test_the_banner_is_on_stderr_so_it_never_lands_in_piped_output(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings", steps=[ok([], count=0)])

    result = runner.invoke(app, ["listings"], env=cli_env())

    assert "SANDBOX" not in result.stdout
    assert "SANDBOX" in result.stderr
