"""The example configuration shipped with the package.

It is the file an operator copies, so it has to load, and every key in it has to
say what it is for. Its values are invented: they are a shape to edit, never
somebody else's house defaults.
"""

from __future__ import annotations

import re

from hostaway_cli.config import EXAMPLE_FILENAME, example_config_path, load_config

KEY = re.compile(r"^(?P<indent>\s*)(?P<name>[A-Za-z_][A-Za-z0-9_]*):")


def lines() -> list[str]:
    return example_config_path().read_text(encoding="utf-8").splitlines()


def test_the_example_ships_inside_the_package() -> None:
    path = example_config_path()

    assert path.is_file()
    assert path.name == EXAMPLE_FILENAME


def test_the_example_loads_as_a_valid_configuration() -> None:
    config = load_config(example_config_path())

    assert config.house_defaults
    assert config.fill_only_if_empty
    # Markups and same-day booking are commented out so a copy applies neither.
    assert not config.markups.wire_fields()
    assert "allowSameDayBooking" not in config.house_defaults


def test_every_fill_only_if_empty_field_in_the_example_is_a_house_default() -> None:
    config = load_config(example_config_path())

    assert all(field in config.house_defaults for field in config.fill_only_if_empty)


def test_every_key_in_the_example_is_documented_by_the_comment_above_it() -> None:
    undocumented = []
    previous = ""
    for line in lines():
        match = KEY.match(line)
        if match and not previous.lstrip().startswith("#"):
            undocumented.append(match.group("name"))
        if line.strip():
            previous = line
    assert not undocumented, f"Keys with no comment above them: {undocumented}"


def test_the_example_tells_the_operator_how_to_use_it() -> None:
    header = "\n".join(lines()[:20])

    assert "HSCTL_CONFIG" in header
    assert "invented" in header
