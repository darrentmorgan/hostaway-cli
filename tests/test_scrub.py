"""No tracked file carries a denylisted string.

Two denylists apply. ``tests/scrub_denylist.example.txt`` is committed and holds generic
patterns only. The private list of real identifiers is never committed: it is read from the
path in ``HSCTL_SCRUB_DENYLIST``, falling back to the git-ignored
``tests/scrub_denylist.local.txt``; with neither present the real-identifier tests skip.
See the example file's header for the entry format.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).parent
EXAMPLE_DENYLIST_PATH = TESTS_DIR / "scrub_denylist.example.txt"
LOCAL_DENYLIST_PATH = TESTS_DIR / "scrub_denylist.local.txt"
DENYLIST_ENV = "HSCTL_SCRUB_DENYLIST"
SKIP_REASON = (
    f"no private denylist: set {DENYLIST_ENV} or create tests/scrub_denylist.local.txt "
    "to check for real identifiers"
)
WORD_PREFIX = "word:"
REGEX_PREFIX = "re:"


@dataclass(frozen=True)
class DenylistEntry:
    text: str
    pattern: re.Pattern[str]
    kind: str

    @classmethod
    def parse(cls, line: str) -> DenylistEntry:
        if line.startswith(WORD_PREFIX):
            token = line.removeprefix(WORD_PREFIX)
            escaped = re.escape(token)
            return cls(token, re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"), "word")
        if line.startswith(REGEX_PREFIX):
            source = line.removeprefix(REGEX_PREFIX)
            return cls(source, re.compile(source, re.IGNORECASE), "regex")
        return cls(line, re.compile(re.escape(line), re.IGNORECASE), "plain")


def private_denylist_path() -> Path | None:
    configured = os.environ.get(DENYLIST_ENV)
    candidate = Path(configured).expanduser() if configured else LOCAL_DENYLIST_PATH
    return candidate if candidate.is_file() else None


def parse_denylist(path: Path) -> list[DenylistEntry]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        DenylistEntry.parse(stripped)
        for stripped in (line.strip() for line in lines)
        if stripped and not stripped.startswith("#")
    ]


def load_example_denylist() -> list[DenylistEntry]:
    return parse_denylist(EXAMPLE_DENYLIST_PATH)


def load_denylist() -> list[DenylistEntry]:
    """The private denylist; skips the calling test when none is configured."""
    path = private_denylist_path()
    if path is None:
        pytest.skip(SKIP_REASON)
    return parse_denylist(path)


_DENYLIST_FILES = {EXAMPLE_DENYLIST_PATH, LOCAL_DENYLIST_PATH}


def find_hits(paths: Iterable[Path], entries: Sequence[DenylistEntry], root: Path) -> list[str]:
    """Report every ``path:line: 'string'`` where a denylisted string appears."""
    hits: list[str] = []
    for path in paths:
        if path in _DENYLIST_FILES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            hits.extend(
                f"{path.relative_to(root)}:{lineno}: {entry.text!r}"
                for entry in entries
                if entry.pattern.search(line)
            )
    return hits


def tracked_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [REPO_ROOT / name.decode("utf-8") for name in listing.split(b"\0") if name]


def entry_of_kind(kind: str) -> DenylistEntry:
    return next(entry for entry in load_denylist() if entry.kind == kind)


def plain_entry() -> DenylistEntry:
    return entry_of_kind("plain")


def word_entry() -> DenylistEntry:
    return entry_of_kind("word")


def plant(tmp_path: Path, body: str) -> Path:
    planted = tmp_path / "notes.md"
    planted.write_text(body, encoding="utf-8")
    return planted


def test_example_denylist_is_seeded() -> None:
    assert load_example_denylist()


def test_tracked_files_are_free_of_generic_patterns() -> None:
    hits = find_hits(tracked_files(), load_example_denylist(), root=REPO_ROOT)

    assert not hits, "Generic scrub patterns found in the tree:\n" + "\n".join(hits)


def test_private_denylist_is_seeded() -> None:
    assert len(load_denylist()) >= 20


def test_scan_names_the_file_line_and_string_of_a_planted_entry(tmp_path: Path) -> None:
    entry = plain_entry()
    planted = plant(tmp_path, f"first line\nInternal note: {entry.text}\n")

    hits = find_hits([planted], [entry], root=tmp_path)

    assert hits == [f"notes.md:2: {entry.text!r}"]


def test_tracked_files_are_free_of_denylisted_strings() -> None:
    hits = find_hits(tracked_files(), load_denylist(), root=REPO_ROOT)

    assert not hits, "Denylisted strings found in the tree:\n" + "\n".join(hits)


def test_scan_matches_a_plain_entry_whatever_its_case(tmp_path: Path) -> None:
    entry = next(e for e in load_denylist() if e.kind == "plain" and e.text.upper() != e.text)
    planted = plant(tmp_path, f"Owner: {entry.text.upper()}\n")

    hits = find_hits([planted], [entry], root=tmp_path)

    assert hits == [f"notes.md:1: {entry.text!r}"]


def test_scan_matches_a_word_entry_standing_alone(tmp_path: Path) -> None:
    entry = word_entry()
    planted = plant(tmp_path, f"handled by {entry.text} operations\n")

    hits = find_hits([planted], [entry], root=tmp_path)

    assert hits == [f"notes.md:1: {entry.text!r}"]


def test_scan_ignores_a_word_entry_buried_in_a_longer_token(tmp_path: Path) -> None:
    entry = word_entry()
    planted = plant(tmp_path, f"tumbling {entry.text.lower()}ford and TROU{entry.text}ER\n")

    assert find_hits([planted], [entry], root=tmp_path) == []


def test_scan_matches_a_word_entry_case_sensitively(tmp_path: Path) -> None:
    entry = word_entry()
    planted = plant(tmp_path, f"the {entry.text.swapcase()} team\n")

    assert find_hits([planted], [entry], root=tmp_path) == []


def test_a_value_that_identifies_only_beside_its_field_is_caught(tmp_path: Path) -> None:
    """A markup multiplier is a bare number until it sits next to a markup field."""
    field, multiplier = "airbnbOfficialListingMarkup", "1.17"
    planted = plant(tmp_path, f'    "{field}": {multiplier},  # house default\n')

    assert find_hits([planted], load_denylist(), root=tmp_path)


def test_the_same_value_in_a_version_string_is_not_a_hit(tmp_path: Path) -> None:
    planted = plant(
        tmp_path,
        'markupsafe = "1.17.0"\nairbnb-client = "1.11.3"\nrequires-python = ">=3.11"\n',
    )

    assert find_hits([planted], load_denylist(), root=tmp_path) == []
