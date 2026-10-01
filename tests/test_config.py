"""The operator's configuration file: house defaults, fill-only-if-empty, markups.

Seam: ``load_config`` and the ``Configuration`` it returns. Nothing here reaches
into a private helper. Every value in these fixtures is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hostaway_cli.config import CONFIG_ENV_VAR, ConfigError, Configuration, load_config

VALID = """
house_defaults:
  language: en
  allowSameDayBooking: 1
  cancellationPolicyId: 2001
  contactName: Guest
  contactEmail: stays@example.com
fill_only_if_empty:
  - contactName
  - contactEmail
markups:
  airbnb: 1.2
  booking_engine: 1.05
"""


def write(tmp_path: Path, body: str, name: str = "config.yaml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_valid_file_loads_its_three_sections(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, VALID))

    assert config.house_defaults == {
        "language": "en",
        "allowSameDayBooking": 1,
        "cancellationPolicyId": 2001,
        "contactName": "Guest",
        "contactEmail": "stays@example.com",
    }
    assert config.fill_only_if_empty == ("contactName", "contactEmail")
    assert config.markups.wire_fields() == {
        "airbnbOfficialListingMarkup": 1.2,
        "bookingEngineMarkup": 1.05,
    }


def test_configuration_names_its_fill_only_if_empty_fields(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, VALID))

    assert config.is_fill_only_if_empty("contactName")
    assert not config.is_fill_only_if_empty("language")


def test_the_path_comes_from_the_environment_when_none_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONFIG_ENV_VAR, str(write(tmp_path, VALID)))

    assert load_config().house_defaults["language"] == "en"


def test_an_unset_environment_variable_says_what_to_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)

    with pytest.raises(ConfigError) as caught:
        load_config()

    assert str(caught.value) == (
        "HSCTL_CONFIG is not set. Point it at your configuration file; "
        "copy config.example.yaml to start."
    )


def test_a_missing_file_names_the_path_it_looked_for(tmp_path: Path) -> None:
    absent = tmp_path / "nowhere.yaml"

    with pytest.raises(ConfigError) as caught:
        load_config(absent)

    assert str(caught.value) == (
        f"Configuration file not found: {absent}. "
        "Copy config.example.yaml to that path and edit it."
    )


def test_an_unknown_key_is_named_with_its_section(tmp_path: Path) -> None:
    path = write(tmp_path, VALID + "\nmarkupz:\n  airbnb: 1.2\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == f"Configuration error in {path}:\n  markupz: unknown key"


def test_an_unknown_channel_is_named_inside_markups(tmp_path: Path) -> None:
    path = write(tmp_path, VALID + "  tripadvisor: 1.3\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n  markups.tripadvisor: unknown key"
    )


def test_a_wrong_type_says_what_was_expected(tmp_path: Path) -> None:
    path = write(tmp_path, VALID.replace("  airbnb: 1.2", "  airbnb: high"))

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n  markups.airbnb: expected a number"
    )


def test_a_fill_only_if_empty_written_as_one_name_asks_for_a_list(tmp_path: Path) -> None:
    """One name written without its dash is an ordinary slip, and YAML says list."""
    path = write(
        tmp_path, "house_defaults:\n  contactName: Guest\nfill_only_if_empty: contactName\n"
    )

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n  fill_only_if_empty: expected a list"
    )


def test_a_house_default_key_that_is_not_a_string_names_that_key(tmp_path: Path) -> None:
    """The key is named as the operator wrote it, with no validator marker beside it."""
    path = write(tmp_path, "house_defaults:\n  123: en\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n  house_defaults.123: expected a string"
    )


def test_house_defaults_must_be_a_mapping(tmp_path: Path) -> None:
    path = write(tmp_path, "house_defaults:\n  - language\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n  house_defaults: expected a mapping"
    )


def test_a_nested_house_default_is_rejected_as_not_a_wire_value(tmp_path: Path) -> None:
    path = write(tmp_path, "house_defaults:\n  contact:\n    name: Guest\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n"
        "  house_defaults.contact: expected a string, number or true/false"
    )


def test_a_file_with_no_house_defaults_is_incomplete(tmp_path: Path) -> None:
    path = write(tmp_path, "markups:\n  airbnb: 1.2\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n  house_defaults: required key is missing"
    )


def test_every_error_in_the_file_is_reported_at_once(tmp_path: Path) -> None:
    path = write(tmp_path, "house_defaults: []\nmarkups:\n  airbnb: high\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n"
        "  house_defaults: expected a mapping\n"
        "  markups.airbnb: expected a number"
    )


def test_a_fill_only_if_empty_field_must_be_a_house_default(tmp_path: Path) -> None:
    path = write(tmp_path, VALID.replace("  - contactName", "  - contactPhone1"))

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}:\n"
        "  fill_only_if_empty: 'contactPhone1' is not one of the house_defaults keys"
    )


def test_an_empty_file_is_not_a_configuration(tmp_path: Path) -> None:
    path = write(tmp_path, "\n# nothing but a comment\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"Configuration error in {path}: the file must be a YAML mapping with a house_defaults key."
    )


def test_broken_yaml_names_the_file(tmp_path: Path) -> None:
    path = write(tmp_path, "house_defaults:\n  language: [en\n")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value).startswith(f"Configuration error in {path}: invalid YAML:")


def test_the_optional_sections_default_to_empty(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "house_defaults:\n  language: en\n"))

    assert config.fill_only_if_empty == ()
    assert config.markups.wire_fields() == {}


def test_a_configuration_can_be_built_in_memory_for_a_test() -> None:
    """The model is public: a caller can construct one without a file on disk."""
    config = Configuration(house_defaults={"language": "en"})

    assert config.house_defaults == {"language": "en"}


MALFORMED = [
    "house_defaults: []",
    "house_defaults:\n  language: en\nfill_only_if_empty: contactName",
    "house_defaults:\n  language: en\nfill_only_if_empty: 5",
    "house_defaults:\n  language: en\nfill_only_if_empty:\n  - 5",
    "house_defaults:\n  123: en",
    "house_defaults:\n  language: en\n  contact:\n    name: Guest",
    "house_defaults:\n  language: en\nmarkups: 1.2",
    "house_defaults:\n  language: en\nmarkups:\n  airbnb: high",
    "house_defaults:\n  language: en\nmarkups:\n  airbnb: [1.2]",
    "markups:\n  airbnb: 1.2",
]


@pytest.mark.parametrize("body", MALFORMED)
def test_no_message_repeats_the_validators_own_wording(tmp_path: Path, body: str) -> None:
    """Every shape this file can be got wrong is spelled out by this module, not pydantic.

    Pydantic's text moves between releases and names its own types; an operator reads
    only sentences from ``config.py``.
    """
    with pytest.raises(ConfigError) as caught:
        load_config(write(tmp_path, body))

    message = str(caught.value)
    for leak in ("Input should", "Value error", "[key]", "tuple", "pydantic"):
        assert leak not in message, message
