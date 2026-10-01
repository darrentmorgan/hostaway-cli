"""What a write is about to change, and how that is shown to an operator.

Every mutating command builds a list of :class:`Change` before it sends anything.
The list is the diff the operator reads, and it is also what the gate judges: a
command is protected because of the fields in front of it, never because of its
name (docs/adr/0001).  Nothing here does I/O or knows about Hostaway's HTTP.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Any

# A secret is never printed, on a dry run no more than on an applied write: a diff
# scrolls into terminal history and screen shares.
REDACTED = "***"

UNSET = "(unset)"

# A deletion has no wire key of its own — the change is a row's absence — so it is
# named here and then reads like any other protected field in a diff or a refusal.
DELETES_LISTING = "delete:listing"
DELETES_IMAGE = "delete:image"

# The fields whose change moves money or bookings, and what a refusal calls each
# one (docs/adr/0001). This is the whole set, in one place, and the gate is asked
# about the change rather than the command: a calendar write carrying only a
# minimum stay is ordinary, the same write carrying availability is not. Channel
# markups, stays, closures and notes are ordinary writes and are absent by design.
PROTECTED_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "price": "price",
        "currencyCode": "currency",
        "cleaningFee": "cleaning fee",
        "refundableDamageDeposit": "damage deposit",
        "pmCommission": "commission/payout formula",
        "isAvailable": "calendar availability",
        DELETES_LISTING: "deletion of a listing",
        DELETES_IMAGE: "deletion of a listing photo",
    }
)


@dataclass(frozen=True)
class Change:
    """One field a write is about to change.

    ``field`` is the wire key Hostaway carries the value under, because that is
    what the gate and the read-back both match on. ``label`` is what the operator
    is shown when the wire key is not the word they used.
    """

    field: str
    before: Any
    after: Any
    label: str | None = None
    secret: bool = False

    @property
    def name(self) -> str:
        """What this change is called in a diff, a refusal or a read-back."""
        return self.label or self.field


def protected_fields_in(changes: Sequence[Change]) -> list[str]:
    """The protected fields this change actually touches, named as ADR 0001 names them."""
    names: list[str] = []
    for change in changes:
        label = PROTECTED_FIELDS.get(change.field)
        if label is not None and label not in names:
            names.append(label)
    return names


def render(changes: Sequence[Change]) -> list[str]:
    """The before-and-after diff, one indented line per field."""
    return [
        f"  {change.name}: {_shown(change, change.before)} -> {_shown(change, change.after)}"
        for change in changes
    ]


def _shown(change: Change, value: Any) -> str:
    """One side of one diff line, with a secret reduced to whether it is set."""
    if change.secret:
        return REDACTED if value not in (None, "") else UNSET
    return repr(value)


# One field of a write beside the value the listing carries when it is read back.
Observation = tuple[Change, Any]

STORED = "stored"
DROPPED = "dropped — Hostaway reported success and did not store it"


def render_readback(observations: Sequence[Observation]) -> list[str]:
    """The read-back, one line per field: what the listing now carries, or does not.

    A field written across a range or across a set of rows is observed once per row
    and reported once: it landed only if it landed everywhere.
    """
    verdicts: dict[str, bool] = {}
    for change, observed in observations:
        verdicts[change.name] = verdicts.get(change.name, True) and landed(change, observed)
    return [f"  {name}: {STORED if stored else DROPPED}" for name, stored in verdicts.items()]


def dropped(observations: Sequence[Observation]) -> list[str]:
    """The names of the fields the read-back does not show, in the order sent.

    Hostaway can accept a write, answer success and discard a field, so an applied
    write is not finished until the listing itself says so (docs/adr/0001).
    """
    names: list[str] = []
    for change, observed in observations:
        if not landed(change, observed) and change.name not in names:
            names.append(change.name)
    return names


def landed(change: Change, observed: Any) -> bool:
    """Whether a read-back value is the one the write sent."""
    return same_value(observed, change.after)


def same_value(observed: Any, sent: Any) -> bool:
    """Compare a stored value with a sent one, ignoring what a write never controls.

    Hostaway hands every row of a sub-resource array an ``id`` of its own that a
    write does not send, and answers a number in whatever width it likes, so a
    literal comparison would report a field dropped on every successful write.
    """
    if isinstance(observed, list) and isinstance(sent, list):
        return _without_row_ids(observed) == _without_row_ids(sent)
    if isinstance(observed, Real) and isinstance(sent, Real):
        return float(observed) == float(sent)
    return bool(observed == sent)


def _without_row_ids(rows: Sequence[Any]) -> list[Any]:
    return [
        {key: value for key, value in row.items() if key != "id"} if isinstance(row, dict) else row
        for row in rows
    ]
