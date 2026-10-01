"""Credentials come from the environment and nowhere else (docs/adr/0003).

The command-level tests prove what an operator sees when the environment is
incomplete; the rest read ``load_credentials`` as the plain function it is, with
an explicit mapping, which is how an offline check reports on an environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from typer.testing import CliRunner

from hostaway_cli.cli import app
from hostaway_cli.credentials import Credentials, CredentialsError, load_credentials
from hostaway_cli.session import HOSTAWAY_API_BASE_URL
from hostaway_cli.surface import Surface
from hostaway_mocks import ACCOUNT_ID, BASE_URL, SECRET_KEY, cli_env

runner = CliRunner()


@pytest.mark.parametrize(
    ("removed", "named"),
    [
        pytest.param(
            {"HOSTAWAY_ACCOUNT_ID": None, "HOSTAWAY_SECRET_KEY": None},
            ("HOSTAWAY_ACCOUNT_ID", "HOSTAWAY_SECRET_KEY"),
            id="neither is set",
        ),
        pytest.param(
            {"HOSTAWAY_SECRET_KEY": None},
            ("HOSTAWAY_SECRET_KEY",),
            id="the secret alone is missing",
        ),
        pytest.param(
            {"HOSTAWAY_ACCOUNT_ID": None},
            ("HOSTAWAY_ACCOUNT_ID",),
            id="the account alone is missing",
        ),
    ],
)
def test_a_command_without_credentials_names_what_to_set_and_sends_nothing(
    respx_mock: respx.MockRouter, removed: dict[str, None], named: tuple[str, ...]
) -> None:
    result = runner.invoke(app, ["listings"], env=cli_env(**removed))

    assert result.exit_code == 2, result.output
    for variable in named:
        assert variable in result.stderr
    assert not respx_mock.calls


def test_the_base_url_defaults_to_hostaway_when_the_environment_names_none() -> None:
    credentials = load_credentials(
        {"HOSTAWAY_ACCOUNT_ID": ACCOUNT_ID, "HOSTAWAY_SECRET_KEY": SECRET_KEY}
    )

    assert credentials == Credentials(account_id=ACCOUNT_ID, secret_key=SECRET_KEY)
    assert credentials.base_url == HOSTAWAY_API_BASE_URL
    assert credentials.surface is Surface.LIVE
    assert credentials.token_cache_path is None


def test_a_configured_base_url_is_used_and_judged_on_its_own_merits() -> None:
    credentials = load_credentials(
        {
            "HOSTAWAY_ACCOUNT_ID": ACCOUNT_ID,
            "HOSTAWAY_SECRET_KEY": SECRET_KEY,
            "HOSTAWAY_API_BASE_URL": BASE_URL,
        }
    )

    assert credentials.base_url == BASE_URL
    assert credentials.surface is Surface.SANDBOX


def test_the_token_cache_path_is_expanded_from_the_home_shorthand() -> None:
    credentials = load_credentials(
        {
            "HOSTAWAY_ACCOUNT_ID": ACCOUNT_ID,
            "HOSTAWAY_SECRET_KEY": SECRET_KEY,
            "HSCTL_TOKEN_CACHE": "~/.cache/hsctl/token.json",
        }
    )

    assert credentials.token_cache_path == Path.home() / ".cache/hsctl/token.json"


def test_a_credentials_value_never_carries_its_secret_into_a_traceback() -> None:
    credentials = load_credentials(
        {"HOSTAWAY_ACCOUNT_ID": ACCOUNT_ID, "HOSTAWAY_SECRET_KEY": "sk-should-not-be-repeated"}
    )

    assert "sk-should-not-be-repeated" not in repr(credentials)


def test_an_empty_variable_counts_as_unset() -> None:
    with pytest.raises(CredentialsError, match="HOSTAWAY_SECRET_KEY"):
        load_credentials({"HOSTAWAY_ACCOUNT_ID": ACCOUNT_ID, "HOSTAWAY_SECRET_KEY": ""})


def test_the_package_never_shells_out_for_a_credential() -> None:
    """No password-manager code path exists: nothing here spawns a process.

    The original tool fell back to reading a specific password-manager item.
    That path is deleted rather than made optional (docs/adr/0003), and the way
    to keep it deleted is that the package launches nothing at all.
    """
    package = Path(__file__).resolve().parents[1] / "src" / "hostaway_cli"

    spawning = [
        module.name
        for module in sorted(package.rglob("*.py"))
        if any(
            token in module.read_text(encoding="utf-8")
            for token in ("subprocess", "os.system", "os.popen", "os.exec")
        )
    ]

    assert spawning == []
