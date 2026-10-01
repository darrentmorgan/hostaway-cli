"""Tests marked ``live`` reach a real Hostaway account, so they run only on explicit opt-in.

The convention: set ``HOSTAWAY_LIVE_TESTS=1`` to run them; otherwise they are skipped.
CI never sets the flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CONFTEST_PATH = Path(__file__).with_name("conftest.py")
LIVE_TEST_MODULE = """
import pytest


@pytest.mark.live
def test_reaches_hostaway() -> None:
    pass
"""


def _run_live_marked_test(pytester: pytest.Pytester) -> pytest.RunResult:
    pytester.makeconftest(CONFTEST_PATH.read_text(encoding="utf-8"))
    pytester.makepyfile(LIVE_TEST_MODULE)
    return pytester.runpytest("--strict-markers", "-p", "no:cacheprovider", "-p", "no:asyncio")


def test_live_tests_are_skipped_without_opt_in(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOSTAWAY_LIVE_TESTS", raising=False)

    result = _run_live_marked_test(pytester)

    result.assert_outcomes(skipped=1)


def test_live_tests_run_when_opted_in(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOSTAWAY_LIVE_TESTS", "1")

    result = _run_live_marked_test(pytester)

    result.assert_outcomes(passed=1)
