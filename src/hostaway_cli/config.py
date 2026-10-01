"""The operator's configuration: house defaults, fill-only-if-empty fields, markups.

One account's house defaults live in a YAML file located through ``HSCTL_CONFIG``.
The package ships ``config.example.yaml`` and holds no operator values of its own: a
command that needs house defaults and cannot find the file fails rather than falling
back to somebody else's (docs/adr/0002).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.functional_validators import AfterValidator

CONFIG_ENV_VAR = "HSCTL_CONFIG"
EXAMPLE_FILENAME = "config.example.yaml"

# Hostaway names one markup field per channel. The channel key an operator writes in
# the configuration is the readable half of that pair; this table is the only place
# the wire spelling appears, so a new channel is one line here.
CHANNEL_WIRE_FIELDS = {
    "airbnb": "airbnbOfficialListingMarkup",
    "booking_engine": "bookingEngineMarkup",
    "homeaway": "homeawayApiMarkup",
    "marriott": "marriottListingMarkup",
}

_SCALAR_MESSAGE = "expected a string, number or true/false"

# Pydantic's own wording moves between releases and leaks its type names into an
# operator's terminal. Every shape this file can be got wrong is spelled out here
# instead, so the message an operator reads is part of the contract the tests pin.
# The keys are exactly the error types the model above can raise — a field added
# there needs its type added here, or its wrong-type message falls back to
# pydantic's. Named in YAML terms, not Python ones: fill_only_if_empty is a list on
# the page whatever the model calls it once loaded.
_TYPE_MESSAGES = {
    "extra_forbidden": "unknown key",
    "missing": "required key is missing",
    "dict_type": "expected a mapping",
    "model_type": "expected a mapping",
    "tuple_type": "expected a list",
    "string_type": "expected a string",
    "float_type": "expected a number",
    "float_parsing": "expected a number",
}


class ConfigError(Exception):
    """The configuration is absent, unreadable or does not describe an account."""


def _scalar(value: Any) -> Any:
    """Reject anything that cannot travel to Hostaway as a single field value."""
    if isinstance(value, bool | int | float | str):
        return value
    raise ValueError(_SCALAR_MESSAGE)


WireValue = Annotated[Any, AfterValidator(_scalar)]


class Markups(BaseModel):
    """Per-channel price multipliers, keyed by channel rather than by wire field."""

    model_config = ConfigDict(extra="forbid")

    airbnb: float | None = None
    booking_engine: float | None = None
    homeaway: float | None = None
    marriott: float | None = None

    def wire_fields(self) -> dict[str, float]:
        """The configured multipliers under the field names Hostaway expects."""
        return {
            CHANNEL_WIRE_FIELDS[channel]: value
            for channel in CHANNEL_WIRE_FIELDS
            if (value := getattr(self, channel)) is not None
        }


class Configuration(BaseModel):
    """One account's house defaults, fill-only-if-empty fields and markups."""

    model_config = ConfigDict(extra="forbid")

    house_defaults: dict[str, WireValue]
    fill_only_if_empty: tuple[str, ...] = ()
    markups: Markups = Markups()
    listing_name_template: str | None = None

    def model_post_init(self, context: Any, /) -> None:
        unknown = [field for field in self.fill_only_if_empty if field not in self.house_defaults]
        if unknown:
            raise ValueError(
                "fill_only_if_empty: "
                + ", ".join(f"{field!r} is not one of the house_defaults keys" for field in unknown)
            )

    def is_fill_only_if_empty(self, field: str) -> bool:
        """Is this house default written only where the listing has no value yet?"""
        return field in self.fill_only_if_empty


def example_config_path() -> Path:
    """The example configuration shipped with the package."""
    return Path(str(resources.files("hostaway_cli").joinpath(EXAMPLE_FILENAME)))


def load_config(
    path: str | Path | None = None, *, env: Mapping[str, str] | None = None
) -> Configuration:
    """Load and validate the configuration file, reporting every problem at once.

    ``path`` defaults to whatever ``HSCTL_CONFIG`` points at. Absence is an error;
    there is no built-in fallback.
    """
    resolved = _resolve_path(path, env)
    if not resolved.is_file():
        raise ConfigError(
            f"Configuration file not found: {resolved}. "
            f"Copy {EXAMPLE_FILENAME} to that path and edit it."
        )
    try:
        document = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigError(f"Configuration error in {resolved}: invalid YAML: {error}") from error
    if not isinstance(document, dict):
        raise ConfigError(
            f"Configuration error in {resolved}: the file must be a YAML mapping "
            "with a house_defaults key."
        )
    try:
        return Configuration.model_validate(document)
    except ValidationError as error:
        raise ConfigError(_render(resolved, error)) from error


def _resolve_path(path: str | Path | None, env: Mapping[str, str] | None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    source = os.environ if env is None else env
    configured = source.get(CONFIG_ENV_VAR)
    if not configured:
        raise ConfigError(
            f"{CONFIG_ENV_VAR} is not set. Point it at your configuration file; "
            f"copy {EXAMPLE_FILENAME} to start."
        )
    return Path(configured).expanduser()


def _render(path: Path, error: ValidationError) -> str:
    lines = sorted({f"  {_where(item)}{_why(item)}" for item in error.errors()})
    return "\n".join([f"Configuration error in {path}:", *lines])


def _where(item: Any) -> str:
    """``section.key: `` for a located problem; nothing for a whole-file one."""
    # A key that fails its own validation carries pydantic's ``[key]`` marker at the
    # end of its location. The operator wrote the key, not the marker: name the key.
    location = ".".join(str(part) for part in item["loc"] if part != "[key]")
    return f"{location}: " if location else ""


def _why(item: Any) -> str:
    message = _TYPE_MESSAGES.get(item["type"])
    if message is not None:
        return message
    # A validator this module raised itself: its ValueError text is already the
    # operator-facing sentence, wearing pydantic's "Value error, " prefix.
    return str(item["msg"]).removeprefix("Value error, ")
