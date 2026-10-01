"""What an operator sees when Hostaway refuses, rather than a Python traceback.

A read command fails for two quite different reasons, and they exit differently:
the environment is wrong and the operator has to fix it before trying again, or
Hostaway itself refused this request.  Neither should arrive as a stack trace.
"""

from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_mocks import cli_env, mock_access_tokens, mock_endpoint

runner = CliRunner()


def test_a_listing_hostaway_does_not_have_is_reported_not_raised(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", "/listings/9999", steps=[httpx.Response(404, json={})])

    result = runner.invoke(app, ["get", "9999"], env=cli_env())

    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "/listings/9999" in result.stderr
    assert "Traceback" not in result.output


def test_credentials_hostaway_rejects_are_reported_not_raised(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock, "GET", "/listings", steps=[httpx.Response(401, json={"status": "fail"})]
    )

    result = runner.invoke(app, ["listings"], env=cli_env())

    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "credentials" in result.stderr
    assert "Traceback" not in result.output
