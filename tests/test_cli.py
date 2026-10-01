"""The ``hsctl`` entry point, driven through the CLI test runner (seam 1)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from hostaway_cli.cli import app

runner = CliRunner()


def test_help_lists_the_command_set() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "Commands" in result.output
    for command in (
        "version",
        "listings",
        "get",
        "reservation-lookup",
        "calendar",
        "amenities",
        "listing-amenities",
        "set",
        "amenities-set",
        "calendar-set",
        "captions",
    ):
        assert command in result.output


def test_version_command_prints_the_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0, result.output
    assert re.search(r"^hsctl \d+\.\d+\.\d+", result.output.strip())


def test_hsctl_console_script_is_installed() -> None:
    script = Path(sys.executable).with_name("hsctl")

    completed = subprocess.run([str(script), "--help"], capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr
    assert "version" in completed.stdout
