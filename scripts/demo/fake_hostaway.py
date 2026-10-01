"""A local stand-in for the Hostaway API, so the CLI can be demonstrated offline.

Nothing here is real. The account, the five villas, their IDs, prices, calendars
and reservations are invented, and a write mutates this process's memory only, so
a recording can show an applied write without a booking system hearing about it.

The surface banner reads SANDBOX in front of it, because the base URL is not
Hostaway's own and that is the only thing the banner consults (docs/adr/0004).

    uv run python scripts/demo/fake_hostaway.py 8765
    source scripts/demo/env.demo
    uv run hsctl listings

Each server owns its own copy of the account, so an applied write lasts as long
as the process and no longer. Restart it to get the seeded villas back.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_PORT = 8765

# The demo account. Invented, and no account Hostaway ever issued.
ACCOUNT_ID = "424242"

ACCESS_TOKEN = "demo-sandbox-token-not-a-credential"

WEEKEND_MARKUP = 1.15

# The account's amenity catalog: the names amenity IDs stand for. The last three
# are the "standing inclusions" the demo audit looks for, and two of the five
# villas are seeded without them so the audit has something to find.
AMENITIES: list[dict[str, Any]] = [
    {"id": 1, "name": "Wifi"},
    {"id": 2, "name": "Air conditioning"},
    {"id": 3, "name": "Private pool"},
    {"id": 4, "name": "Kitchen"},
    {"id": 5, "name": "Free parking"},
    {"id": 6, "name": "Hot tub"},
    {"id": 7, "name": "TV"},
    {"id": 8, "name": "Washing machine"},
    {"id": 9, "name": "Workspace"},
    {"id": 10, "name": "Baby cot"},
    {"id": 11, "name": "Pool towels"},
    {"id": 12, "name": "Yoga deck"},
    {"id": 13, "name": "Breakfast"},
    {"id": 14, "name": "Airport shuttle"},
    {"id": 15, "name": "Daily housekeeping"},
    {"id": 91, "name": "Smoke detector"},
    {"id": 92, "name": "First aid kit"},
    {"id": 93, "name": "Linens"},
]

STANDING_INCLUSIONS = (91, 92, 93)

# The rest of the account's catalogs. Small on purpose: they exist so a caller
# that reads them gets an answer, not so the demo can browse them.
BED_TYPES: list[dict[str, Any]] = [
    {"id": 1, "name": "King bed"},
    {"id": 2, "name": "Queen bed"},
    {"id": 3, "name": "Twin bed"},
    {"id": 4, "name": "Sofa bed"},
]

CUSTOM_FIELDS: list[dict[str, Any]] = [
    {"id": 501, "name": "Housekeeping notes", "objectType": "listing", "type": "text"},
    {"id": 502, "name": "Gate keypad location", "objectType": "listing", "type": "text"},
]

PROPERTY_TYPES: list[dict[str, Any]] = [
    {"id": 1, "name": "Villa"},
    {"id": 2, "name": "Apartment"},
    {"id": 3, "name": "Bungalow"},
]

# A policy ID means nothing outside the channel that published it, so each
# channel gets its own invented set.
CANCELLATION_POLICIES: dict[str, list[dict[str, Any]]] = {
    "native": [{"id": 601, "name": "Flexible"}, {"id": 602, "name": "Moderate"}],
    "airbnb": [{"id": 611, "name": "flexible"}, {"id": 612, "name": "moderate"}],
    "booking": [{"id": 621, "name": "Free cancellation"}],
    "vrbo": [{"id": 631, "name": "Relaxed"}],
    "marriott": [{"id": 641, "name": "Standard"}],
}

REVIEWS: list[dict[str, Any]] = [
    {
        "id": 8001,
        "listingMapId": 1001,
        "reservationId": 7001,
        "type": "guest-to-host",
        "status": "published",
        "rating": 5,
        "publicReview": "The pool at sunset is the whole holiday.",
        "departureDate": "2027-01-14",
    },
    {
        "id": 8002,
        "listingMapId": 1004,
        "reservationId": 7002,
        "type": "guest-to-host",
        "status": "published",
        "rating": 4,
        "publicReview": "Plenty of room for three families.",
        "departureDate": "2027-01-24",
    },
]

# Hostaway answers the consolidated report as CSV rather than its usual envelope.
CONSOLIDATED_REPORT_COLUMNS = ("listingName", "reservationId", "arrivalDate", "totalPrice")


def _listing(
    listing_id: int,
    name: str,
    city: str,
    *,
    bedrooms: int,
    guests: int,
    price: int,
    amenity_ids: Sequence[int],
    exported: bool = True,
) -> dict[str, Any]:
    """One invented listing, in the shape Hostaway returns it."""
    return {
        "id": listing_id,
        "name": name,
        "internalListingName": f"{name} (internal)",
        "externalListingName": name,
        "city": city,
        "state": "Example Province",
        "country": "Indonesia",
        "address": f"Jl. Contoh No. {listing_id % 90}, {city}",
        "price": price,
        "currencyCode": "USD",
        "cleaningFee": 45,
        "bedroomsNumber": bedrooms,
        "bathroomsNumber": bedrooms,
        "personCapacity": guests,
        "minNights": 2,
        "maxNights": 30,
        "checkInTimeStart": 14,
        "checkOutTime": 11,
        "cancellationPolicy": "moderate",
        "instantBookable": 1,
        "airbnbExportStatus": "exported" if exported else "not exported",
        "listingAmenities": [
            {"id": 9000 + amenity_id, "amenityId": amenity_id} for amenity_id in amenity_ids
        ],
        "listingImages": [
            {
                "id": listing_id * 10 + order,
                "url": f"https://images.example.invalid/{listing_id}-{order}.jpg",
                "sortOrder": order,
                "caption": caption,
                "airbnbCaption": caption,
                "vrboCaption": caption,
                "bookingEngineCaption": caption,
            }
            for order, caption in enumerate(("Pool at dusk", "Living pavilion"), start=1)
        ],
        "customFieldValues": [],
    }


SEED_LISTINGS: list[dict[str, Any]] = [
    _listing(
        1001,
        "Villa Saka",
        "Ubud",
        bedrooms=3,
        guests=6,
        price=240,
        amenity_ids=[1, 2, 3, 4, 5, 7, 91, 92, 93],
    ),
    _listing(
        1002,
        "Villa Nira",
        "Sanur",
        bedrooms=4,
        guests=8,
        price=410,
        amenity_ids=[1, 2, 3, 4, 6, 7, 15, 91, 92, 93],
    ),
    # Seeded short of a smoke detector and a first aid kit.
    _listing(
        1003,
        "Villa Anaya",
        "Amed",
        bedrooms=1,
        guests=2,
        price=95,
        amenity_ids=[1, 2, 4, 9, 93],
    ),
    _listing(
        1004,
        "Villa Sereno",
        "Lovina",
        bedrooms=5,
        guests=10,
        price=520,
        amenity_ids=[1, 2, 3, 4, 5, 7, 8, 10, 15, 91, 92, 93],
    ),
    # Seeded short of a smoke detector and linens.
    _listing(
        1005,
        "Villa Padma",
        "Tabanan",
        bedrooms=2,
        guests=4,
        price=160,
        amenity_ids=[1, 2, 4, 7, 92],
        exported=False,
    ),
]


def _reservation(
    reservation_id: int,
    *,
    listing_id: int,
    channel: str,
    channel_reference: str,
    arrival: str,
    departure: str,
    total: float,
    guest: str,
) -> dict[str, Any]:
    """One invented reservation, in the shape Hostaway returns it.

    The guest fields are here on purpose. ``hsctl reservation-lookup`` prints an
    allowlist rather than stripping a blocklist, and a demo of that proves nothing
    unless the reservation it filters actually carries the personal fields. The
    guest is made up and the contact details are reserved, unroutable examples.
    """
    return {
        "id": reservation_id,
        "reservationId": f"HA-{reservation_id}",
        "channelReservationId": channel_reference,
        "channelName": channel,
        "listingMapId": listing_id,
        "listingName": next(
            listing["name"] for listing in SEED_LISTINGS if listing["id"] == listing_id
        ),
        "arrivalDate": arrival,
        "departureDate": departure,
        "status": "new",
        "totalPrice": total,
        "currency": "USD",
        "currencyCode": "USD",
        "paymentStatus": "Paid",
        "guestName": guest,
        "guestFirstName": guest.split()[0],
        "guestEmail": f"{guest.split()[0].lower()}@example.invalid",
        "phone": "+15550000001",
        "guestAddress": "12 Imaginary Street",
    }


SEED_RESERVATIONS: list[dict[str, Any]] = [
    _reservation(
        7001,
        listing_id=1001,
        channel="airbnbOfficial",
        channel_reference="DEMOAIRBNB01",
        arrival="2027-01-09",
        departure="2027-01-14",
        total=1320.0,
        guest="Jamie Invented",
    ),
    _reservation(
        7002,
        listing_id=1004,
        channel="bookingcom",
        channel_reference="DEMOBOOKING02",
        arrival="2027-01-18",
        departure="2027-01-24",
        total=3140.0,
        guest="Robin Fictitious",
    ),
]


@dataclass
class DemoAccount:
    """One process's copy of the invented account, seeded and then mutable."""

    listings: dict[int, dict[str, Any]]
    reservations: list[dict[str, Any]]
    calendar: dict[int, dict[str, dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def seeded(cls) -> DemoAccount:
        """A fresh account, exactly as the demo expects to find it."""
        return cls(
            listings={listing["id"]: deepcopy(listing) for listing in SEED_LISTINGS},
            reservations=deepcopy(SEED_RESERVATIONS),
        )

    def booked(self, listing_id: int, on: str) -> bool:
        """Whether a reservation occupies that night.

        The night of the departure date is not one of them: a guest checking out
        that morning leaves the night free to sell.
        """
        return any(
            stay["listingMapId"] == listing_id and stay["arrivalDate"] <= on < stay["departureDate"]
            for stay in self.reservations
        )

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Add one listing to the account and answer with it, as Hostaway does.

        The defaults are the fields a listing has to carry to be read back and
        priced; the payload writes over them, except the ID, which the account
        issues and a payload does not get to choose.
        """
        listing_id = max(self.listings) + 1
        listing = {
            "internalListingName": f"{payload.get('name', 'Untitled')} (internal)",
            "airbnbExportStatus": "not exported",
            "price": 0,
            "listingAmenities": [],
            "listingImages": [],
            **payload,
        }
        listing["id"] = listing_id
        self.listings[listing_id] = listing
        return listing

    def add_images(self, listing_id: int, images: Sequence[dict[str, Any]]) -> int:
        """Add photos to a listing, in the row shape a read-back is judged on."""
        rows = self.listings[listing_id]["listingImages"]
        for offset, image in enumerate(images, start=1):
            rows.append({"id": listing_id * 10 + len(rows) + offset, **image})
        return len(images)

    def day(self, listing_id: int, on: str) -> dict[str, Any]:
        """One calendar day, generated the first time it is asked for.

        Generated rather than stored so any range answers, and deterministic so a
        recording made twice on the same dates shows the same nightly rates.
        """
        days = self.calendar.setdefault(listing_id, {})
        if on not in days:
            when = date.fromisoformat(on)
            nightly = self.listings[listing_id]["price"]
            days[on] = {
                "date": on,
                "isAvailable": 0 if self.booked(listing_id, on) else 1,
                "price": int(nightly * (WEEKEND_MARKUP if when.weekday() >= 4 else 1)),
                "minimumStay": 2,
                "maximumStay": 30,
                "closedOnArrival": 0,
                "closedOnDeparture": 0,
                "note": "",
            }
        return days[on]

    def days(self, listing_id: int, start: str, end: str) -> list[dict[str, Any]]:
        """Every calendar day across an inclusive date range."""
        return [self.day(listing_id, on) for on in _dates(start, end)]


def _dates(start: str, end: str) -> list[str]:
    """Every ISO date from ``start`` to ``end``, both included."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first + timedelta(days=step)).isoformat() for step in range((last - first).days + 1)]


class DemoServer(ThreadingHTTPServer):
    """The HTTP server one demo account is served from."""

    account: DemoAccount


class Handler(BaseHTTPRequestHandler):
    """One request against the demo account."""

    @property
    def account(self) -> DemoAccount:
        server = self.server
        assert isinstance(server, DemoServer)
        return server.account

    def log_message(self, format: str, *args: Any) -> None:
        """Log the route, not the query string, so a recording stays readable."""
        sys.stderr.write(f"  fake-hostaway  {self.command} {urlparse(self.path).path}\n")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path.endswith("/accessTokens"):
            self._send(
                {"token_type": "Bearer", "expires_in": 63072000, "access_token": ACCESS_TOKEN}
            )
            return
        if path.endswith("/finance/report/consolidated"):
            self._send_text(self._consolidated_report())
            return
        parts = [part for part in path.split("/") if part]
        if parts[-1:] == ["listings"]:
            self._ok(self.account.create(self._body()), status=201)
            return
        if parts[-2:-1] == ["export"] and len(parts) >= 3 and parts[-3].isdigit():
            # Hostaway queues the export and answers before the channel has it.
            self._ok({"queued": True, "channel": parts[-1]})
            return
        if parts[-1:] == ["images"] and parts[-2:-1] and parts[-2].isdigit():
            listing_id = int(parts[-2])
            if listing_id not in self.account.listings:
                self._not_found()
                return
            added = self.account.add_images(listing_id, self._body().get("images", []))
            self._ok({"added": added})
            return
        self._not_found()

    def _consolidated_report(self) -> str:
        """The demo account's reservations as the CSV Hostaway answers with."""
        rows = [",".join(CONSOLIDATED_REPORT_COLUMNS)]
        rows += [
            ",".join(str(stay[column]) for column in CONSOLIDATED_REPORT_COLUMNS)
            for stay in self.account.reservations
        ]
        return "\n".join(rows) + "\n"

    def do_GET(self) -> None:
        url = urlparse(self.path)
        parts = [part for part in url.path.split("/") if part]
        query = {key: value[0] for key, value in parse_qs(url.query).items()}
        if parts[-1:] == ["listings"]:
            self._listings_page(query)
            return
        if parts[-1:] == ["amenities"]:
            self._ok(AMENITIES)
            return
        if parts[-1:] == ["bedTypes"]:
            self._ok(BED_TYPES)
            return
        if parts[-1:] == ["customFields"]:
            wanted = query.get("objectType")
            self._ok([row for row in CUSTOM_FIELDS if wanted in (None, row["objectType"])])
            return
        if parts[-1:] == ["propertyTypes"]:
            self._ok(PROPERTY_TYPES)
            return
        if parts[-1:] == ["cancellationPolicies"]:
            self._ok(CANCELLATION_POLICIES["native"])
            return
        if parts[-2:-1] == ["cancellationPolicies"]:
            policies = CANCELLATION_POLICIES.get(parts[-1])
            if policies is None:
                self._not_found()
                return
            self._ok(policies)
            return
        if parts[-1:] == ["reviews"]:
            found = self._matching_reviews(query)
            self._ok(found, count=len(found))
            return
        if parts[-2:-1] == ["reviews"] and parts[-1].isdigit():
            reviews = [review for review in REVIEWS if review["id"] == int(parts[-1])]
            if not reviews:
                self._not_found()
                return
            self._ok(reviews[0])
            return
        if parts[-1:] == ["reservations"]:
            self._ok(self._matching_reservations(query))
            return
        if parts[-2:-1] == ["reservations"] and parts[-1].isdigit():
            stays = [stay for stay in self.account.reservations if stay["id"] == int(parts[-1])]
            if not stays:
                self._not_found()
                return
            self._ok(stays[0])
            return
        if parts[-2:-1] == ["listings"] and parts[-1].isdigit():
            listing = self.account.listings.get(int(parts[-1]))
            if listing is None:
                self._not_found()
                return
            self._ok(listing)
            return
        if parts[-1:] == ["calendar"] and parts[-2:-1] and parts[-2].isdigit():
            listing_id = int(parts[-2])
            if listing_id not in self.account.listings:
                self._not_found()
                return
            self._ok(self.account.days(listing_id, query["startDate"], query["endDate"]))
            return
        self._not_found()

    def do_PUT(self) -> None:
        parts = [part for part in urlparse(self.path).path.split("/") if part]
        body = self._body()
        if parts[-1:] == ["calendar"] and parts[-2:-1] and parts[-2].isdigit():
            listing_id = int(parts[-2])
            if listing_id not in self.account.listings:
                self._not_found()
                return
            fields = {
                key: value for key, value in body.items() if key not in ("startDate", "endDate")
            }
            for day in self.account.days(listing_id, body["startDate"], body["endDate"]):
                day.update(fields)
            self._ok({"updated": True})
            return
        if parts[-2:-1] == ["listings"] and parts[-1].isdigit():
            listing = self.account.listings.get(int(parts[-1]))
            if listing is None:
                self._not_found()
                return
            # Hostaway takes the amenity IDs and answers with rows of its own, so
            # a write that reads its own answer back has to see the same shape.
            if "listingAmenities" in body:
                body["listingAmenities"] = [
                    {"id": 9000 + row["amenityId"], "amenityId": row["amenityId"]}
                    for row in body["listingAmenities"]
                ]
            listing.update(body)
            self._ok(listing)
            return
        self._not_found()

    def _body(self) -> dict[str, Any]:
        """The JSON object this request carries, or an empty one."""
        length = int(self.headers.get("Content-Length") or 0)
        parsed = json.loads(self.rfile.read(length) or b"{}")
        return parsed if isinstance(parsed, dict) else {}

    def _listings_page(self, query: dict[str, str]) -> None:
        """One page of listings, and the account total, as Hostaway answers it.

        The pagination is honoured rather than ignored, and echoed back: a caller
        walking the account refuses a page wider than the one it asked for, so a
        stand-in that always answers the lot cannot be walked at all.
        """
        listings = list(self.account.listings.values())
        offset = int(query.get("offset", 0))
        limit = int(query.get("limit", len(listings)))
        self._ok(
            listings[offset : offset + limit],
            count=len(listings),
            limit=limit,
            offset=offset,
        )

    def _matching_reviews(self, query: dict[str, str]) -> list[dict[str, Any]]:
        """The reviews one query asks for, narrowed by listing when it names any.

        Hostaway reads the listing filter as indexed keys — ``listingMapIds[0]`` —
        and a repeated or joined key matches nothing, so the stand-in reads them
        the same way rather than being more forgiving than the thing it stands in for.
        """
        wanted = {int(value) for key, value in query.items() if key.startswith("listingMapIds[")}
        if not wanted:
            return REVIEWS
        return [review for review in REVIEWS if review["listingMapId"] in wanted]

    def _matching_reservations(self, query: dict[str, str]) -> list[dict[str, Any]]:
        """The page of reservations one query asks for.

        Only the filters hsctl sends are honoured; a filter this stand-in does not
        know is ignored rather than guessed at, and the demo never sends one.
        """
        first = query.get("departureStartDate", "0000-01-01")
        last = query.get("departureEndDate", "9999-12-31")
        listing = query.get("listingId")
        found = [
            stay
            for stay in self.account.reservations
            if first <= stay["departureDate"] <= last
            and (listing is None or stay["listingMapId"] == int(listing))
        ]
        offset = int(query.get("offset", 0))
        limit = int(query.get("limit", len(found)))
        return found[offset : offset + limit]

    def _ok(self, result: Any, *, status: int = 200, **extra: Any) -> None:
        self._send({"status": "success", "result": result, **extra}, status=status)

    def _not_found(self) -> None:
        self._send({"status": "fail", "message": "no such route on the demo server"}, status=404)

    def _send_text(self, body: str, status: int = 200) -> None:
        self._write(body.encode("utf-8"), status=status, content_type="text/csv")

    def _send(self, body: dict[str, Any], status: int = 200) -> None:
        self._write(json.dumps(body).encode("utf-8"), status=status)

    def _write(self, raw: bytes, *, status: int, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def make_server(port: int = DEFAULT_PORT) -> DemoServer:
    """A demo server bound to ``port`` on loopback. Port 0 takes a free one."""
    server = DemoServer(("127.0.0.1", port), Handler)
    server.account = DemoAccount.seeded()
    return server


def base_url(server: DemoServer) -> str:
    """The base URL to point ``HOSTAWAY_API_BASE_URL`` at for ``server``."""
    return f"http://127.0.0.1:{server.server_port}/v1"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = make_server(port)
    sys.stderr.write(f"fake Hostaway on {base_url(server)} — synthetic data, nothing is real\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
