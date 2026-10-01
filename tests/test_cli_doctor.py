"""``hsctl doctor``: the offline check on the environment and the configuration.

Seam: the ``doctor`` command through the CLI runner.  Doctor's whole promise is
that it answers before a single byte reaches Hostaway, so the promise is what is
enforced here: the ``offline`` fixture below fails any test in which anything
opens a connection or sends a request, and it is autouse, so a doctor test cannot
be written that forgets to check.
"""

from __future__ import annotations

import re
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
import respx
from typer.testing import CliRunner, Result

from hostaway_cli.cli import app
from hostaway_cli.session import HOSTAWAY_API_BASE_URL
from hostaway_mocks import ACCOUNT_ID, LONG_PAST, cli_env, write_token_cache

runner = CliRunner()

SENT_A_REQUEST = "a doctor test sent an HTTP request"
OPENED_A_CONNECTION = "a doctor test opened a network connection"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[respx.MockRouter]:
    """Fail the test if anything reaches for the network while doctor runs.

    Two layers, because each catches what the other cannot: a catch-all respx
    route turns any httpx request into a failure and records it, and a socket
    that refuses to connect catches a request made through anything else.
    """

    def refuse(*_: object, **__: object) -> NoReturn:
        raise AssertionError(OPENED_A_CONNECTION)

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=AssertionError(SENT_A_REQUEST))
        yield router
        assert not router.calls, SENT_A_REQUEST


CONFIG = """
house_defaults:
  language: en
  cancellationPolicyId: 2001
fill_only_if_empty:
  - language
markups:
  airbnb: 1.2
"""


def write_config(path: Path, body: str = CONFIG) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def report(result: Result) -> dict[str, tuple[str, str]]:
    """The printed report as ``{check name: (outcome, detail)}``."""
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    fields = [re.split(r"\s{2,}", line.strip(), maxsplit=2) for line in lines]
    return {name: (outcome, detail) for outcome, name, detail in fields}


def test_a_complete_environment_passes_every_check_and_sends_nothing(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(app, ["doctor"], env=cli_env(HSCTL_CONFIG=str(config)))

    assert result.exit_code == 0, result.output
    assert {name: outcome for name, (outcome, _) in report(result).items()} == {
        "credentials": "PASS",
        "surface": "PASS",
        "token cache": "PASS",
        "configuration": "PASS",
    }
    assert not offline.calls


def test_a_missing_secret_is_named_and_fails_the_check(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HOSTAWAY_SECRET_KEY=None, HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 2, result.output
    outcome, detail = report(result)["credentials"]
    assert outcome == "FAIL"
    assert "HOSTAWAY_SECRET_KEY" in detail
    assert not offline.calls


def test_a_failing_check_does_not_stop_the_others_from_reporting(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    """The whole setup is reported at once: doctor is not a first-error stopper."""
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HOSTAWAY_ACCOUNT_ID=None, HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 2, result.output
    assert set(report(result)) == {"credentials", "surface", "token cache", "configuration"}
    assert report(result)["configuration"][0] == "PASS"
    assert not offline.calls


def test_a_base_url_that_could_not_reach_anything_fails_the_check(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HOSTAWAY_API_BASE_URL="api.hostaway.test/v1", HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 2, result.output
    outcome, detail = report(result)["surface"]
    assert outcome == "FAIL"
    assert "HOSTAWAY_API_BASE_URL" in detail
    assert not offline.calls


def test_the_report_names_the_account_and_the_surface_it_would_be_spent_on(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    """Doctor makes no call, so it carries no banner; its own lines say both."""
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HOSTAWAY_API_BASE_URL=HOSTAWAY_API_BASE_URL, HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 0, result.output
    assert ACCOUNT_ID in report(result)["credentials"][1]
    assert report(result)["surface"][1] == f"LIVE | {HOSTAWAY_API_BASE_URL}"
    assert not offline.calls


def test_hostaways_own_api_is_the_surface_when_no_base_url_is_set(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HOSTAWAY_API_BASE_URL=None, HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 0, result.output
    assert report(result)["surface"] == ("PASS", f"LIVE | {HOSTAWAY_API_BASE_URL}")
    assert not offline.calls


def test_a_configured_cache_is_reported_by_path_and_account(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    cache = write_token_cache(tmp_path / "token.json")
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HSCTL_TOKEN_CACHE=str(cache), HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 0, result.output
    outcome, detail = report(result)["token cache"]
    assert outcome == "PASS"
    assert str(cache) in detail
    assert "0600" in detail
    assert ACCOUNT_ID in detail
    assert not offline.calls


def test_a_cache_other_users_can_read_fails_the_check(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    cache = write_token_cache(tmp_path / "token.json", mode=0o644)
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HSCTL_TOKEN_CACHE=str(cache), HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 2, result.output
    outcome, detail = report(result)["token cache"]
    assert outcome == "FAIL"
    assert f"chmod 0600 {cache}" in detail
    assert not offline.calls


def test_a_cache_holding_another_account_fails_the_check(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    cache = write_token_cache(tmp_path / "token.json", account_id="515151")
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HSCTL_TOKEN_CACHE=str(cache), HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 2, result.output
    outcome, detail = report(result)["token cache"]
    assert outcome == "FAIL"
    assert "515151" in detail
    assert ACCOUNT_ID in detail
    assert not offline.calls


def test_a_cache_that_is_not_a_token_fails_the_check_by_path(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    cache = tmp_path / "token.json"
    cache.write_text("{", encoding="utf-8")
    cache.chmod(0o600)
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HSCTL_TOKEN_CACHE=str(cache), HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 2, result.output
    outcome, detail = report(result)["token cache"]
    assert outcome == "FAIL"
    assert str(cache) in detail
    assert not offline.calls


def test_an_expired_cache_passes_and_says_it_will_be_replaced(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    """An expired token is not a setup problem: the next command fetches one."""
    cache = write_token_cache(tmp_path / "token.json", expires_at=LONG_PAST)
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HSCTL_TOKEN_CACHE=str(cache), HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 0, result.output
    outcome, detail = report(result)["token cache"]
    assert outcome == "PASS"
    assert "expired" in detail
    assert not offline.calls


def test_a_cache_path_that_does_not_exist_yet_passes(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    cache = tmp_path / "not-written-yet" / "token.json"
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HSCTL_TOKEN_CACHE=str(cache), HSCTL_CONFIG=str(config)),
    )

    assert result.exit_code == 0, result.output
    outcome, detail = report(result)["token cache"]
    assert outcome == "PASS"
    assert str(cache) in detail
    assert not cache.exists()
    assert not offline.calls


def test_no_cache_configured_passes_and_says_the_variable_that_would_set_one(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    """The cache is optional; not having one is a fact, not a fault."""
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(app, ["doctor"], env=cli_env(HSCTL_CONFIG=str(config)))

    assert result.exit_code == 0, result.output
    outcome, detail = report(result)["token cache"]
    assert outcome == "PASS"
    assert "HSCTL_TOKEN_CACHE" in detail
    assert not offline.calls


def test_a_valid_configuration_passes_and_counts_what_it_holds(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    config = write_config(tmp_path / "config.yaml")

    result = runner.invoke(app, ["doctor"], env=cli_env(HSCTL_CONFIG=str(config)))

    assert result.exit_code == 0, result.output
    assert report(result)["configuration"] == (
        "PASS",
        f"{config}: 2 house defaults, 1 fill-only-if-empty, 1 markups",
    )
    assert not offline.calls


def test_no_configuration_is_a_warning_the_reads_can_live_with(
    offline: respx.MockRouter,
) -> None:
    """Absence stops create and backfill, not doctor: reads need no house defaults."""
    result = runner.invoke(app, ["doctor"], env=cli_env())

    assert result.exit_code == 0, result.output
    outcome, detail = report(result)["configuration"]
    assert outcome == "WARN"
    assert "HSCTL_CONFIG" in detail
    assert "backfill" in detail
    assert not offline.calls


def test_a_configuration_file_that_is_not_where_it_is_pointed_fails_the_check(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    """Naming a file that is not there is a mistake, not an absence."""
    missing = tmp_path / "config.yaml"

    result = runner.invoke(app, ["doctor"], env=cli_env(HSCTL_CONFIG=str(missing)))

    assert result.exit_code == 2, result.output
    outcome, detail = report(result)["configuration"]
    assert outcome == "FAIL"
    assert str(missing) in detail
    assert not offline.calls


def test_a_configuration_that_does_not_parse_fails_on_one_line_naming_the_key(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    """A validation report runs to several lines; the check is still one line."""
    unknown_key = "house_defaults:\n  language: en\nmarkup: 1.2\n"
    config = write_config(tmp_path / "config.yaml", unknown_key)

    result = runner.invoke(app, ["doctor"], env=cli_env(HSCTL_CONFIG=str(config)))

    assert result.exit_code == 2, result.output
    outcome, detail = report(result)["configuration"]
    assert outcome == "FAIL"
    assert "markup: unknown key" in detail
    assert len([line for line in result.stdout.splitlines() if line.strip()]) == 4
    assert not offline.calls


def test_the_offline_guard_fails_a_test_that_reaches_the_network(
    offline: respx.MockRouter,
) -> None:
    """The guard every other test leans on, proved here so it cannot quietly rot."""
    with pytest.raises(AssertionError, match=SENT_A_REQUEST):
        httpx.get("https://api.hostaway.com/v1/listings")
    with pytest.raises(AssertionError, match=OPENED_A_CONNECTION):
        socket.socket().connect(("api.hostaway.com", 443))

    # The refused request above is the one call this module tolerates: forget it,
    # so the fixture's own check reads as it does for every other test.
    offline.calls.clear()


def test_the_report_is_on_stdout_and_the_verdict_names_what_failed_on_stderr(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    """The report can be piped or pasted; the verdict stays out of it."""
    cache = write_token_cache(tmp_path / "token.json", mode=0o644)

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HOSTAWAY_SECRET_KEY=None, HSCTL_TOKEN_CACHE=str(cache)),
    )

    assert result.exit_code == 2, result.output
    assert result.stderr.splitlines() == ["doctor: 2 of 4 checks failed: credentials, token cache"]
    assert "FAIL" not in result.stderr
    assert not offline.calls


def test_a_cache_cannot_be_matched_to_an_account_that_is_not_configured(
    offline: respx.MockRouter, tmp_path: Path
) -> None:
    """Without an account ID there is nothing to compare the cached one against."""
    cache = write_token_cache(tmp_path / "token.json")

    result = runner.invoke(
        app,
        ["doctor"],
        env=cli_env(HOSTAWAY_ACCOUNT_ID=None, HSCTL_TOKEN_CACHE=str(cache)),
    )

    assert result.exit_code == 2, result.output
    outcome, detail = report(result)["token cache"]
    assert outcome == "WARN"
    assert "HOSTAWAY_ACCOUNT_ID" in detail
    assert not offline.calls
