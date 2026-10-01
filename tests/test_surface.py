"""LIVE or SANDBOX, judged from the base URL alone (docs/adr/0004).

The banner tests prove a command says it; these pin what "Hostaway's own host"
means at the edges, where a wrong answer in either direction is the whole risk.
"""

from __future__ import annotations

import pytest

from hostaway_cli.session import HOSTAWAY_API_BASE_URL
from hostaway_cli.surface import Surface, surface_of

LIVE_URLS = {
    "the default base URL": HOSTAWAY_API_BASE_URL,
    "no path": "https://api.hostaway.com",
    "a trailing slash": "https://api.hostaway.com/",
    "a host spelled in capitals": "https://API.HOSTAWAY.COM/v1",
    "an explicit port": "https://api.hostaway.com:443/v1",
    "a future API version": "https://api.hostaway.com/v2",
}

SANDBOX_URLS = {
    "a local demo server": "http://127.0.0.1:8080/v1",
    "a stand-in host": "https://api.hostaway.test/v1",
    "a host that only ends with Hostaway's": "https://not-api.hostaway.com/v1",
    "a host that only starts with Hostaway's": "https://api.hostaway.com.example.test/v1",
    "Hostaway's host in the path": "https://example.test/api.hostaway.com/v1",
    "Hostaway's host as a query": "https://example.test/v1?host=api.hostaway.com",
    "Hostaway's website rather than its API": "https://www.hostaway.com/v1",
    "no host at all": "api.hostaway.com/v1",
    "nothing": "",
}


@pytest.mark.parametrize("base_url", LIVE_URLS.values(), ids=LIVE_URLS)
def test_hostaways_own_host_is_live(base_url: str) -> None:
    assert surface_of(base_url) is Surface.LIVE


@pytest.mark.parametrize("base_url", SANDBOX_URLS.values(), ids=SANDBOX_URLS)
def test_every_other_base_url_is_sandbox(base_url: str) -> None:
    assert surface_of(base_url) is Surface.SANDBOX
