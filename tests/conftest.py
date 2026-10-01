"""Shared pytest configuration.

Live tests: mark a test ``@pytest.mark.live`` when it reaches a real Hostaway account.
Such tests are skipped unless ``HOSTAWAY_LIVE_TESTS=1`` is set in the environment,
and CI never sets it.
"""

from __future__ import annotations

import os

import pytest

pytest_plugins = ["pytester"]

LIVE_MARKER = "live"
LIVE_ENV_FLAG = "HOSTAWAY_LIVE_TESTS"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{LIVE_MARKER}: reaches a real Hostaway account; runs only when {LIVE_ENV_FLAG}=1",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(LIVE_ENV_FLAG) == "1":
        return
    skip_live = pytest.mark.skip(reason=f"live test; set {LIVE_ENV_FLAG}=1 to run")
    for item in items:
        if item.get_closest_marker(LIVE_MARKER) is not None:
            item.add_marker(skip_live)
