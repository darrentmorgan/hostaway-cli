"""The demo kit's tapes and documents stay in step with the CLI they record.

A tape is a script a contributor runs months later, and a stale one fails on
camera: a flag the CLI has since renamed, a villa the demo server no longer
serves, a path left behind by the repository the kit came from. Nothing here
opens a socket — these read the kit as text and check it against the CLI's own
help and the demo account's own seed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import typer.main
from typer.core import TyperGroup
from typer.testing import CliRunner

import fake_hostaway
from hostaway_cli.cli import app
from hostaway_mocks import plain

runner = CliRunner()

KIT = Path(__file__).resolve().parents[1] / "scripts" / "demo"

# Wide, so an option name in the help never wraps mid-word before it is read back.
WIDE = {"COLUMNS": "200", "TERM": "dumb"}


def registry() -> TyperGroup:
    """The CLI's own command registry, which is what the kit is read against."""
    group = typer.main.get_command(app)
    assert isinstance(group, TyperGroup)
    return group


def published_commands() -> frozenset[str]:
    """Every command name ``hsctl`` currently registers, read off the CLI itself."""
    return frozenset(registry().commands)


def commands_taking_a_listing() -> frozenset[str]:
    """Every command whose first argument is a listing ID, read off the CLI itself.

    An *option* named for a listing is not one of these: what the kit's listing
    check reads is the bare number typed straight after the command name.
    """
    return frozenset(
        name
        for name, command in registry().commands.items()
        if next(
            (param.name for param in command.params if param.param_type_name == "argument"),
            None,
        )
        == "listing_id"
    )


# The commands hsctl publishes. A token after ``hsctl`` that is not one of these
# is prose — the agent tape types English at an agent, not only shell at a shell.
# Taken from the CLI rather than listed here: a list would go stale the next time
# hsctl grows a command, and it would go stale in silence.
COMMANDS = published_commands()

# One invocation: the command, and everything typed after it. A tape types a
# command line inside double quotes and a shell ends one at a pipe, so the run
# stops there and nowhere else — a quoted argument is part of the command line,
# and stopping at it is how a stale flag hides behind an amenity name.
INVOCATION = re.compile(r"hsctl\s+([a-z][a-z-]*)([^\"|\n]*)")
LONG_OPTION = re.compile(r"--[a-z][a-z-]*")
# A listing argument is a bare number. Prose after a command name is not one,
# and a command line that has lost its listing ID is a different failure.
FIRST_ARGUMENT = re.compile(r"\s+(\d+)")

# The commands whose first argument is a listing ID — taken from the CLI for the
# same reason as COMMANDS above.
TAKES_A_LISTING = commands_taking_a_listing()

# Every path the kit points at is a path in this repository.
REPO_PATH = re.compile(r"\b(?:scripts|src|tests|docs)/[\w./-]+")


def kit_files() -> list[Path]:
    """Every document and script in the kit, the fake server excepted.

    The server is the thing these are checked against, so it is not one of the
    things checked; it has a test file of its own.
    """
    return sorted(
        path for path in KIT.iterdir() if path.is_file() and path.name != "fake_hostaway.py"
    )


def kit_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in kit_files())


def invocations(text: str) -> list[tuple[str, str]]:
    """Every ``hsctl`` command line in the kit, as its command and the rest of it.

    A token after ``hsctl`` that is not a command is prose: the agent tape types
    English at an agent as well as shell at a shell.
    """
    return [(command, rest) for command, rest in INVOCATION.findall(text) if command in COMMANDS]


def options_of(command: str) -> str:
    """One command's help, as an operator reads it."""
    result = runner.invoke(app, [command, "--help"], env=WIDE)
    assert result.exit_code == 0, result.output
    return plain(result.output)


def test_the_kit_is_the_whole_set_of_files_a_recording_needs() -> None:
    assert [path.name for path in kit_files()] == [
        "NARRATION.md",
        "README.md",
        "agent-session.tape",
        "agent-shell.sh",
        "env.demo",
        "hostaway-demo.tape",
        "record-voiceover.sh",
    ]


@pytest.mark.parametrize("command", sorted(published_commands()))
def test_every_command_hsctl_publishes_is_one_the_kit_guards_can_see(command: str) -> None:
    """A command the guards have never heard of is read as prose and checked by nothing.

    That failure is silent, which is the danger: the kit keeps passing while a whole
    command line in it goes unread, and its flags, listings and amenities go unchecked.
    """
    assert invocations(f"hsctl {command} --not-an-option 1001") == [
        (command, " --not-an-option 1001")
    ]


@pytest.mark.parametrize("command", sorted(published_commands()))
def test_the_kit_expects_a_listing_argument_wherever_the_help_shows_one(command: str) -> None:
    """The listing check reads the first argument, so it has to know which commands take one.

    The usage line an operator reads is the independent witness here: a command that
    prints ``{listing_id}`` in it and is missing below has its listings unchecked.
    """
    assert (command in TAKES_A_LISTING) == ("{listing_id}" in options_of(command))


def test_every_option_the_kit_types_is_one_that_command_still_has() -> None:
    """The kit was written against a CLI whose confirm flag was called something else."""
    typed = invocations(kit_text())

    assert typed, "the kit types no hsctl command at all"
    stale = [
        f"hsctl {command} {option}"
        for command, rest in typed
        for option in LONG_OPTION.findall(rest)
        if option not in options_of(command)
    ]
    assert not stale, "options the kit types that hsctl no longer has:\n" + "\n".join(stale)


def test_the_kit_demonstrates_both_halves_of_the_write_gate() -> None:
    """A demo of this tool that never shows --allow-protected is missing the point."""
    text = kit_text()

    assert "--apply" in text
    assert "--allow-protected" in text


@pytest.mark.parametrize("path", kit_files(), ids=lambda path: str(path.name))
def test_no_kit_file_points_outside_this_repository(path: Path) -> None:
    """The kit moved here from another repository, which is where its paths pointed."""
    text = path.read_text(encoding="utf-8")

    named = {found for found in REPO_PATH.findall(text) if not found.startswith("scripts/demo/out")}
    missing = sorted(found for found in named if not (KIT.parents[1] / found).exists())
    assert not missing, f"{path.name} names paths this repository does not have: {missing}"
    assert "~/" not in text, f"{path.name} points at a path outside the repository"


def test_every_listing_the_kit_names_is_one_the_demo_server_serves() -> None:
    """A tape that opens on a listing the server has not got fails on camera."""
    served = {str(listing["id"]) for listing in fake_hostaway.SEED_LISTINGS}
    named = [
        (command, argument.group(1))
        for command, rest in invocations(kit_text())
        if command in TAKES_A_LISTING and (argument := FIRST_ARGUMENT.match(rest))
    ]

    assert named, "the kit names no listing at all"
    unserved = sorted({f"hsctl {command} {arg}" for command, arg in named if arg not in served})
    assert not unserved, "listings the demo server does not serve: " + ", ".join(unserved)


def test_every_amenity_the_kit_names_is_one_the_demo_catalog_publishes() -> None:
    published = {str(row["name"]) for row in fake_hostaway.AMENITIES}
    quoted = set(re.findall(r"--add '([^']+)'|--remove '([^']+)'", kit_text()))
    named = {name for pair in quoted for name in pair if name}

    assert named, "the kit adds or removes no amenity by name"
    assert named <= published, f"amenities the catalog has not got: {sorted(named - published)}"
