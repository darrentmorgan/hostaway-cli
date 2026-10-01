"""respx routes and synthetic fixtures for the Hostaway API.

Test support only: every route built here is a respx mock, so nothing in this
module reaches the network.  It exists so a test can describe a *sequence* of
Hostaway responses (401 then 200, 500 three times, a timeout then 200) without
re-stating the token stub in every module.

All data is invented: the account, the villas and their IDs are made up for
these tests and correspond to no real account.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import respx

BASE_URL = "https://api.hostaway.test/v1"
ACCESS_TOKEN_PATH = "/accessTokens"

ACCOUNT_ID = "424242"
SECRET_KEY = "sk-not-a-real-secret"

# Two distinguishable tokens so a forced refresh is visible in the bearer header
# the second request carries.  Hostaway tokens are long; these are padded to
# clear the model's minimum length.
FIRST_TOKEN = "tok-first-padded-1234567890"
REFRESHED_TOKEN = "tok-refreshed-padded-1234567890"

# A respx step is either a response to return or an exception to raise.
Step = httpx.Response | Exception

# A handler answers one request, and may be async when the test needs to watch
# what happens while the request is in flight.
Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


def token_response(access_token: str) -> httpx.Response:
    """One Hostaway ``/accessTokens`` success body carrying ``access_token``."""
    return httpx.Response(
        200,
        json={"token_type": "Bearer", "expires_in": 63072000, "access_token": access_token},
    )


def mock_access_tokens(
    router: respx.MockRouter,
    *,
    tokens: Sequence[str] = (FIRST_TOKEN, REFRESHED_TOKEN),
    base_url: str = BASE_URL,
) -> respx.Route:
    """Mock ``POST /accessTokens``, handing out ``tokens`` in call order.

    The last token repeats once the sequence is exhausted, so a test only has to
    name the tokens whose identity it actually asserts on.
    """
    return mock_endpoint(
        router,
        "POST",
        ACCESS_TOKEN_PATH,
        steps=[token_response(t) for t in tokens],
        base_url=base_url,
    )


def mock_endpoint(
    router: respx.MockRouter,
    method: str,
    path: str,
    *,
    steps: Sequence[Step],
    base_url: str = BASE_URL,
) -> respx.Route:
    """Mock one Hostaway endpoint with a fixed response/exception sequence.

    ``steps`` are consumed in call order; the final step repeats for every
    further call, which is what "keeps failing" looks like on the wire.
    """
    if not steps:
        raise ValueError("steps must contain at least one response or exception")
    remaining = list(steps)

    def handler(request: httpx.Request) -> httpx.Response:
        step = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(step, Exception):
            raise step
        return step

    return mock_handler(router, method, path, handler, base_url=base_url)


def mock_handler(
    router: respx.MockRouter,
    method: str,
    path: str,
    handler: Handler,
    *,
    base_url: str = BASE_URL,
) -> respx.Route:
    """Mock one Hostaway endpoint with a caller-supplied handler.

    ``mock_endpoint`` covers a fixed sequence of answers; this is for a test that
    has to watch *when* a request arrives, or what is happening while it is in
    flight, rather than only that it arrived.
    """
    return router.request(method, f"{base_url}{path}").mock(side_effect=handler)


def ok(result: Any, **extra: Any) -> httpx.Response:
    """A Hostaway 200 wrapping ``result`` in its usual envelope."""
    return httpx.Response(200, json={"status": "success", "result": result, **extra})


def bearer_tokens(route: respx.Route) -> list[str]:
    """The bearer values ``route`` was called with, in call order."""
    return [
        str(call.request.headers.get("Authorization", "")).removeprefix("Bearer ")
        for call in route.calls
    ]


def sent_bodies(route: respx.Route) -> list[Any]:
    """The decoded JSON bodies ``route`` was called with, in call order."""
    return [json.loads(call.request.content) for call in route.calls]


def sent_body(route: respx.Route) -> Any:
    """The decoded JSON body of the single request ``route`` received."""
    bodies = sent_bodies(route)
    if len(bodies) != 1:
        raise AssertionError(f"expected exactly one request, got {len(bodies)}")
    return bodies[0]


ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """CLI output with the terminal's colour codes removed.

    A coloured terminal is what CI gives the runner, and rich styles an option name
    one dash at a time, so ``--door-code`` is not a contiguous string in the output
    an assertion sees. Reading it back plain is how the operator reads it.
    """
    return ANSI_CODES.sub("", text)


BOX_CHARS = re.compile(r"[\u256d\u256e\u2570\u256f\u2502\u2500]")


def squashed(text: str) -> str:
    """CLI output as one line: colour gone, rich's box gone, wrapping undone.

    A refusal longer than the terminal is drawn inside a box and broken across
    lines, so the sentence the operator actually reads is not a contiguous string
    anywhere in the output. This is that sentence.
    """
    return " ".join(BOX_CHARS.sub(" ", plain(text)).split())


# --- synthetic listings ----------------------------------------------------

VILLA_ID = 1001


def villa(
    listing_id: int = VILLA_ID,
    *,
    name: str = "Villa Saka",
    amenity_ids: Sequence[int] = (1, 2, 3),
    **overrides: Any,
) -> dict[str, Any]:
    """One invented listing in the shape Hostaway returns it."""
    listing: dict[str, Any] = {
        "id": listing_id,
        "name": name,
        "internalListingName": f"{name} (internal)",
        "city": "Ubud",
        "country": "Indonesia",
        "bedroomsNumber": 3,
        "bathroomsNumber": 2,
        "personCapacity": 6,
        "airbnbExportStatus": "exported",
        "listingAmenities": [{"id": 9000 + a, "amenityId": a} for a in amenity_ids],
    }
    listing.update(overrides)
    return listing


def photo(image_id: int, sort_order: int, caption: str = "") -> dict[str, Any]:
    """One invented listing photo, carrying the four captions Hostaway exposes."""
    return {
        "id": image_id,
        "url": f"https://images.hostaway.test/{image_id}.jpg",
        "sortOrder": sort_order,
        "caption": caption,
        "airbnbCaption": caption,
        "vrboCaption": caption,
        "bookingEngineCaption": caption,
    }


def villas() -> list[dict[str, Any]]:
    """The five invented listings the CLI tests and the demo kit render."""
    return [
        villa(1001, name="Villa Saka", city="Ubud"),
        villa(1002, name="Villa Nira", city="Sanur"),
        villa(1003, name="Villa Anaya", city="Amed"),
        villa(1004, name="Villa Sereno", city="Lovina"),
        villa(1005, name="Villa Padma", city="Tabanan", airbnbExportStatus="not exported"),
    ]


# --- CLI environment -------------------------------------------------------


# Every optional variable is named here, empty, so a test runs the same whatever
# the developer happens to have exported.
def cli_env(**overrides: str | None) -> dict[str, str | None]:
    """The environment a CLI test runs under, pointed at the mocked base URL.

    Credentials come from the environment and nowhere else, so a CLI test that
    wants a missing or wrong one overrides it here rather than reaching inside
    the command.  ``None`` removes a variable outright.
    """
    env: dict[str, str | None] = {
        "HOSTAWAY_ACCOUNT_ID": ACCOUNT_ID,
        "HOSTAWAY_SECRET_KEY": SECRET_KEY,
        "HOSTAWAY_API_BASE_URL": BASE_URL,
        "HSCTL_TOKEN_CACHE": "",
        "HSCTL_CONFIG": "",
        "HSCTL_DOOR_CODE": "",
        "HSCTL_WIFI_PASSWORD": "",
    }
    env.update(overrides)
    return env


# --- synthetic reservations ------------------------------------------------

RESERVATION_ID = 5001


def reservation(
    reservation_id: int = RESERVATION_ID,
    *,
    listing_id: int = VILLA_ID,
    listing_name: str = "Villa Saka",
    arrival_date: str = "2026-07-01",
    departure_date: str = "2026-07-05",
    **overrides: Any,
) -> dict[str, Any]:
    """One invented reservation in the shape Hostaway returns it.

    The guest fields are part of the fixture on purpose: a test that the CLI
    prints only the safe reservation fields proves nothing unless the response
    it filters actually carries the personal ones.  The guest here is invented
    and the contact details are reserved, unroutable examples.
    """
    booking: dict[str, Any] = {
        "id": reservation_id,
        "reservationId": f"HA-{reservation_id}",
        "channelReservationId": f"CH-{reservation_id}",
        "channelName": "airbnbOfficial",
        "listingMapId": listing_id,
        "listingName": listing_name,
        "arrivalDate": arrival_date,
        "departureDate": departure_date,
        "status": "new",
        "totalPrice": 1375.0,
        "currency": "AUD",
        "currencyCode": "AUD",
        "paymentStatus": "Paid",
        "guestName": "Jamie Invented",
        "guestFirstName": "Jamie",
        "guestEmail": "jamie@example.invalid",
        "phone": "+15550000001",
        "guestAddress": "12 Imaginary Street",
    }
    booking.update(overrides)
    return booking


# --- synthetic calendar days -----------------------------------------------


def calendar_day(
    date: str,
    *,
    is_available: int = 1,
    price: int | None = 275,
    minimum_stay: int = 2,
    maximum_stay: int = 30,
    closed_on_arrival: int = 0,
    closed_on_departure: int = 0,
    note: str = "",
    **overrides: Any,
) -> dict[str, Any]:
    """One invented calendar day, with Hostaway's integer flags rather than booleans."""
    day: dict[str, Any] = {
        "date": date,
        "isAvailable": is_available,
        "price": price,
        "minimumStay": minimum_stay,
        "maximumStay": maximum_stay,
        "closedOnArrival": closed_on_arrival,
        "closedOnDeparture": closed_on_departure,
        "note": note,
    }
    day.update(overrides)
    return day


# --- synthetic amenity catalog ---------------------------------------------


def amenity_catalog() -> list[dict[str, Any]]:
    """An invented amenity catalog, small enough for a test to assert on whole."""
    return [
        {"id": 1, "name": "Wifi"},
        {"id": 2, "name": "Private pool"},
        {"id": 3, "name": "Air conditioning"},
        {"id": 4, "name": "Pool towels"},
        {"id": 5, "name": "Kitchen"},
    ]


# --- the other synthetic catalogs ------------------------------------------


def bed_type_catalog() -> list[dict[str, Any]]:
    """An invented bed-type catalog, holding the beds the villa draft names."""
    return [
        {"id": 1101, "name": "King"},
        {"id": 1102, "name": "Queen"},
        {"id": 1103, "name": "Twin"},
        {"id": 1104, "name": "Sofa bed"},
    ]


def property_type_catalog() -> list[dict[str, Any]]:
    """An invented property-type catalog."""
    return [
        {"id": 41, "name": "Apartment"},
        {"id": 42, "name": "Villa"},
        {"id": 43, "name": "House"},
    ]


def custom_field_catalog() -> list[dict[str, Any]]:
    """An invented listing custom-field catalog."""
    return [
        {"id": 3301, "name": "Google map link"},
        {"id": 3302, "name": "Owner reference"},
    ]


def mock_catalogs(router: respx.MockRouter) -> None:
    """Mock every catalog a create resolves its draft against, in one call."""
    mock_endpoint(router, "GET", "/amenities", steps=[ok(amenity_catalog())])
    mock_endpoint(router, "GET", "/bedTypes", steps=[ok(bed_type_catalog())])
    mock_endpoint(router, "GET", "/propertyTypes", steps=[ok(property_type_catalog())])
    mock_endpoint(router, "GET", "/customFields", steps=[ok(custom_field_catalog())])


# --- token cache files -----------------------------------------------------

CACHED_TOKEN = "tok-cached-padded-1234567890"
FAR_FUTURE = "2099-01-01T00:00:00+00:00"
LONG_PAST = "2020-01-01T00:00:00+00:00"


def write_token_cache(
    path: Path,
    *,
    account_id: str = ACCOUNT_ID,
    access_token: str = CACHED_TOKEN,
    expires_at: str = FAR_FUTURE,
    mode: int = 0o600,
) -> Path:
    """One token cache file, as a previous command would have left it."""
    path.write_text(
        json.dumps(
            {"account_id": account_id, "access_token": access_token, "expires_at": expires_at}
        ),
        encoding="utf-8",
    )
    path.chmod(mode)
    return path
