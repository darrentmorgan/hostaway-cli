"""The published documents stay in step with the repository and the CLI they describe.

A README is read months after it is written, by somebody who has no other source of
truth, and every claim in it that the tool has since outgrown is a stranger's dead end:
a path that moved, an option that was renamed, an environment variable nobody mentioned.
Nothing here opens a socket. These read the documents as text and check them against the
package directory, the CLI's own help and the workflow CI actually runs.

The seam is the same one ``test_demo_kit.py`` uses on the demo kit; the small regexes are
repeated rather than shared, so each file can be read on its own.
"""

from __future__ import annotations

import re
import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
import typer.main
import yaml
from typer.core import TyperGroup
from typer.testing import CliRunner

from conftest import LIVE_ENV_FLAG
from hostaway_cli.cli import app
from hostaway_mocks import plain

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "src" / "hostaway_cli"
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"
README = REPO_ROOT / "README.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ISSUE_TEMPLATES = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"

# Every path the documents point at, as a reader would follow it. A path is written
# with one of the repository's own top directories in front of it, or is one of the
# documents at the root.
REPO_PATH = re.compile(
    r"(?:\.github|docs|scripts|src|tests)/[\w./-]+"
    r"|\b(?:CONTEXT|README|CONTRIBUTING|SECURITY|CHANGELOG)\.md\b"
    r"|\bpyproject\.toml\b"
)
# An ADR is cited by its number alone — ``docs/adr/0001`` — in the modules and the
# documents alike, because its title is long and can be revised.
ADR_SHORTHAND = re.compile(r"^docs/adr/(\d{4})$")


def documentation_files() -> list[Path]:
    """Every document this repository publishes to a reader.

    The demo kit is not here: its documents are recording scripts, and
    ``test_demo_kit.py`` checks them against the demo server they run on.
    """
    github = REPO_ROOT / ".github"
    return sorted(
        {
            *REPO_ROOT.glob("*.md"),
            *(REPO_ROOT / "docs").rglob("*.md"),
            *github.glob("*.md"),
            *github.glob("ISSUE_TEMPLATE/*"),
        }
    )


def paths_named_in(text: str) -> set[str]:
    """Every repository path a document points a reader at."""
    return {found.rstrip("./") for found in REPO_PATH.findall(text)}


def exists(named: str) -> bool:
    if (REPO_ROOT / named).exists():
        return True
    shorthand = ADR_SHORTHAND.match(named)
    if shorthand is None:
        return False
    return any((REPO_ROOT / "docs" / "adr").glob(f"{shorthand.group(1)}-*.md"))


def package_modules() -> list[str]:
    return sorted(path.name for path in PACKAGE.glob("*.py"))


@pytest.mark.parametrize("path", documentation_files(), ids=lambda path: path.name)
def test_every_repository_path_the_documentation_names_exists(path: Path) -> None:
    """A document that points at a file which is not there sends a reader nowhere."""
    named = paths_named_in(path.read_text(encoding="utf-8"))

    missing = sorted(found for found in named if not exists(found))
    assert not missing, f"{path.name} names paths this repository has not got: {missing}"


def test_the_architecture_document_places_every_module_in_a_layer() -> None:
    """A module the architecture doc never mentions is a layer nobody wrote down.

    The package directory is the witness: a new module has to be placed, and an
    architecture doc that has quietly fallen a module behind fails here rather than
    misleading the next reader.
    """
    text = ARCHITECTURE.read_text(encoding="utf-8")
    modules = package_modules()

    assert modules, "the package has no modules to place"
    unplaced = [module for module in modules if module not in text]
    assert not unplaced, f"modules docs/architecture.md does not place: {unplaced}"


def workflow_commands() -> list[str]:
    """Every shell command CI runs, read off the workflow itself."""
    workflow: Any = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [
        step["run"].strip()
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "run" in step
    ]


def test_contributing_documents_the_live_test_opt_in() -> None:
    """A contributor has to be told the flag by name, or the live tests are unreachable."""
    assert LIVE_ENV_FLAG in CONTRIBUTING.read_text(encoding="utf-8")


def test_ci_never_sets_the_live_test_flag() -> None:
    """The claim CONTRIBUTING makes, checked against the workflow that would break it.

    Live tests reach a real Hostaway account with a real secret. CI has neither, and a
    workflow that set the flag would turn every pull request into a live run.
    """
    assert LIVE_ENV_FLAG not in WORKFLOW.read_text(encoding="utf-8")


def test_contributing_names_every_check_ci_runs() -> None:
    """A check a contributor cannot run locally is one they first meet as a red build."""
    text = CONTRIBUTING.read_text(encoding="utf-8")
    commands = [command for command in workflow_commands() if command.startswith("uv ")]

    assert commands, "the workflow runs no uv command at all"
    undocumented = [command for command in commands if command not in text]
    assert not undocumented, f"checks CI runs that CONTRIBUTING.md does not: {undocumented}"


def test_the_changelog_opens_at_unreleased() -> None:
    """Nothing is released yet, so the first section a reader meets is the next release.

    The package version is the witness: while it carries a pre-release suffix there is no
    tagged version for the changelog to have a section about.
    """
    headings = [
        line.strip()
        for line in CHANGELOG.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]

    assert version("hostaway-cli").endswith(".dev0"), "a released version needs its own section"
    assert headings, "the changelog has no sections at all"
    assert "Unreleased" in headings[0], f"the changelog opens at {headings[0]!r}"


# The whole of what a reader is owed, whatever else the repository grows. ADRs are not
# listed one by one: a new decision is a new file, and adding one must not fail a test
# about the documentation set.
PUBLISHED = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "CONTEXT.md",
    "docs/architecture.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/config.yml",
)

# The element types GitHub's form schema defines. A form using anything else silently
# fails to render, and the first anybody hears of it is a stranger who cannot file a bug.
FORM_ELEMENTS = frozenset({"markdown", "textarea", "input", "dropdown", "checkboxes", "upload"})


def issue_forms() -> list[Path]:
    """The issue forms, which is every file in the chooser except the chooser's own config."""
    return sorted(path for path in ISSUE_TEMPLATES.glob("*.yml") if path.name != "config.yml")


@pytest.mark.parametrize("relative", PUBLISHED)
def test_the_repository_publishes_the_whole_documentation_set(relative: str) -> None:
    assert (REPO_ROOT / relative).is_file()


def test_there_is_an_issue_form_to_choose() -> None:
    assert issue_forms(), "the chooser offers nothing but its config"


@pytest.mark.parametrize("form", issue_forms(), ids=lambda path: path.name)
def test_every_issue_form_is_one_github_can_render(form: Path) -> None:
    """A form GitHub cannot parse is one nobody can file an issue through."""
    definition: Any = yaml.safe_load(form.read_text(encoding="utf-8"))

    assert {"name", "description", "body"} <= set(definition), "a form needs all three keys"
    assert definition["body"], "a form with no body asks nothing"
    unknown = [
        element.get("type")
        for element in definition["body"]
        if element.get("type") not in FORM_ELEMENTS
    ]
    assert not unknown, f"{form.name} uses element types GitHub has not got: {unknown}"


def test_the_issue_chooser_sends_a_vulnerability_to_the_security_policy() -> None:
    """A vulnerability filed as a public issue is a vulnerability published.

    The chooser is where somebody decides, so it has to offer the private route there
    rather than leaving them to find SECURITY.md on their own.
    """
    config: Any = yaml.safe_load((ISSUE_TEMPLATES / "config.yml").read_text(encoding="utf-8"))

    links = config.get("contact_links", [])
    assert any(str(link.get("url", "")).endswith("SECURITY.md") for link in links), (
        "the issue chooser offers no link to the security policy"
    )


# One invocation in a document: the command, and everything typed after it up to a quote,
# a pipe or the end of the line. Same shape as the demo kit's, and same reason: a quoted
# argument is part of the command line, and stopping at it is how a stale flag hides.
INVOCATION = re.compile(r"hsctl\s+([a-z][a-z-]*)([^\"|\n]*)")
LONG_OPTION = re.compile(r"--[a-z][a-z-]*")
# An environment variable the package reads. It is named as a string where it is read,
# which is the only place that is true of.
ENV_VAR = re.compile(r"\"((?:HOSTAWAY|HSCTL)_[A-Z_]+)\"")

# Wide, so an option name in the help never wraps mid-word before it is read back.
WIDE = {"COLUMNS": "200", "TERM": "dumb"}


def published_commands() -> frozenset[str]:
    """Every command name ``hsctl`` registers, read off the CLI itself."""
    group = typer.main.get_command(app)
    assert isinstance(group, TyperGroup)
    return frozenset(group.commands)


def options_of(command: str) -> str:
    """One command's help, as an operator reads it."""
    result = CliRunner().invoke(app, [command, "--help"], env=WIDE)
    assert result.exit_code == 0, result.output
    return plain(result.output)


def invocations(text: str) -> list[tuple[str, str]]:
    """Every ``hsctl`` command line in a document, as its command and the rest of it."""
    commands = published_commands()
    return [(command, rest) for command, rest in INVOCATION.findall(text) if command in commands]


def environment_variables() -> set[str]:
    """Every environment variable the package reads, taken from the package."""
    return {
        name
        for path in PACKAGE.glob("*.py")
        for name in ENV_VAR.findall(path.read_text(encoding="utf-8"))
    }


def test_every_command_hsctl_publishes_is_shown_in_the_readme() -> None:
    """A command the README never mentions is one a stranger never finds."""
    text = README.read_text(encoding="utf-8")

    unshown = sorted(command for command in published_commands() if f"hsctl {command}" not in text)
    assert not unshown, f"commands the README does not show: {unshown}"


def test_every_environment_variable_the_package_reads_is_documented_in_the_readme() -> None:
    """An undocumented variable is a setting only the source code knows about."""
    text = README.read_text(encoding="utf-8")
    named = environment_variables()

    assert named, "the package reads no environment variable at all"
    undocumented = sorted(name for name in named if name not in text)
    assert not undocumented, f"variables the README does not document: {undocumented}"


@pytest.mark.parametrize("path", documentation_files(), ids=lambda path: path.name)
def test_every_option_the_documentation_types_is_one_that_command_still_has(path: Path) -> None:
    """The old CLI's apply flag was called something else; a renamed flag rots in prose."""
    stale = [
        f"hsctl {command} {option}"
        for command, rest in invocations(path.read_text(encoding="utf-8"))
        for option in LONG_OPTION.findall(rest)
        if option not in options_of(command)
    ]

    assert not stale, f"{path.name} types options hsctl has not got:\n" + "\n".join(stale)


def test_the_readme_installs_from_the_repository_this_package_declares() -> None:
    """An install line pointing at the wrong repository installs somebody else's tool.

    ``pyproject.toml`` is the witness: it is what a published package carries, so the
    URL a reader is told to install from is checked against it rather than against
    itself.
    """
    metadata: Any = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    repository = metadata["project"]["urls"]["Repository"]

    assert f"git+{repository}" in README.read_text(encoding="utf-8")


# Words CONTEXT.md rules out, and what to say instead. The old CLI called the apply flag
# something else and sorted fields into numbered tiers, and a document that keeps either
# word teaches an operator a vocabulary the tool no longer has.
RETIRED = {
    "preview": "dry run",
    "previews": "dry run",
    "previewed": "dry run",
    "tier": "protected field",
    "tiers": "protected field",
    "--confirm": "--apply",
}


def uses(word: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, re.IGNORECASE) is not None


@pytest.mark.parametrize(
    "path",
    # CONTEXT.md is the dictionary: it is the one document that spells a retired word,
    # in the Avoid line that retires it.
    [path for path in documentation_files() if path.name != "CONTEXT.md"],
    ids=lambda path: path.name,
)
def test_the_documentation_speaks_the_vocabulary_context_settles(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    kept = {word: instead for word, instead in RETIRED.items() if uses(word, text)}
    assert not kept, f"{path.name} uses words CONTEXT.md retired: {kept}"
