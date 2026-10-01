"""The CLI test environment neutralises every variable the package reads.

``cli_env`` in ``tests/hostaway_mocks.py`` names each optional variable, empty, so a
test runs the same whatever the developer happens to have exported.  A variable the
package reads but ``cli_env`` does not name is a hole: the suite passes on a clean
machine and fails on the machine of the operator who followed the README.
"""

from __future__ import annotations

import re
from pathlib import Path

from hostaway_mocks import cli_env

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "hostaway_cli"
ENV_NAME = re.compile(r'"((?:HSCTL|HOSTAWAY)_[A-Z0-9_]+)"')


def env_names_the_package_reads() -> set[str]:
    """Every ``HSCTL_``/``HOSTAWAY_`` variable named as a literal in the package."""
    return {
        match.group(1)
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        for match in ENV_NAME.finditer(path.read_text(encoding="utf-8"))
    }


def test_the_package_reads_variables() -> None:
    """The scan finds something, so an empty result cannot pass the guard below."""
    assert "HOSTAWAY_ACCOUNT_ID" in env_names_the_package_reads()


def test_cli_env_names_every_variable_the_package_reads() -> None:
    """A new variable is neutralised in ``cli_env`` before a test can depend on it."""
    unnamed = sorted(env_names_the_package_reads() - set(cli_env()))

    assert not unnamed, (
        f"{', '.join(unnamed)} reached the CLI from the developer's own shell. "
        "Name each one in cli_env() in tests/hostaway_mocks.py so the suite runs "
        "the same everywhere."
    )
