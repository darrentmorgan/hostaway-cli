# hostaway-cli

A terminal and Python client for operating one Hostaway account safely: read listings, reservations and catalogs, and make gated writes that are previewed before they land and read back after.

## Language

### Account and session

**Account**:
One Hostaway customer account, identified by its numeric account ID. A session is bound to exactly one account.
_Avoid_: client, profile, org

**Session**:
The authenticated client for one account. Every read and write goes through it.
_Avoid_: client, connection

**Transport**:
The layer beneath the session that owns authentication, retry, rate limiting and error mapping. Resource code never touches HTTP directly.

**Token cache**:
An optional owner-only local file holding the bearer token and its expiry for one account, so repeated commands do not re-authenticate. It refuses to load for a different account.

**Surface**:
Where a session is pointed: LIVE when the base URL is Hostaway's, SANDBOX for any other base URL such as the demo server. The banner always names it.
_Avoid_: environment, mode

### Listings

**Listing**:
One property page on Hostaway, identified by its numeric listing ID.
_Avoid_: property, villa, unit

**Channel-connected listing**:
A listing exported to at least one external channel such as Airbnb or Booking.com. Writes to it may propagate outward.
_Avoid_: live listing, published listing

**Export**:
Asking Hostaway to push a listing's current content to a channel. A saved edit is not visible on a channel until exported.
_Avoid_: publish, sync

**Amenity merge**:
The rule that amenity writes are computed against the listing's current amenity set, because Hostaway replaces the whole set on every write.

**Caption**:
The per-channel text attached to a listing photo.

**Calendar day**:
One date on a listing's availability calendar, carrying availability, minimum and maximum stay, arrival and departure closures, and a note.

### Catalogs and conventions

**Catalog**:
An account-scoped reference list published by Hostaway: amenities, bed types, custom fields, property types, cancellation policies.

**House defaults**:
Operator-chosen values applied to every new or backfilled listing on an account, such as cancellation policy IDs and the contact block. Supplied by configuration, never built in.
_Avoid_: account conventions, defaults, constants

**Fill-only-if-empty field**:
A house default that is written only where the listing currently has no value, so an operator's deliberate edit is never overwritten.
_Avoid_: soft default

**Markup**:
The per-channel price multiplier a listing carries, such as the Airbnb official listing markup. Part of house defaults and a channel-facing write.

**Configuration**:
The operator's file of house defaults, fill-only-if-empty fields and markups for one account, located through the environment.
_Avoid_: profile, settings

### Safety

**Dry run**:
The default outcome of any write command: the before and after diff is printed and nothing is sent.
_Avoid_: preview, plan, simulate

**Apply**:
Running a write command with the explicit apply flag so the change is sent to Hostaway.
_Avoid_: live, execute, commit, yes

**Protected field**:
A listing field whose change moves money or bookings: price and currency, cleaning fee, damage deposit, commission or payout formula, calendar availability, and deletion of a listing or image. Markups, minimum and maximum stay, closures and notes are not protected. Writing a protected field requires the protected-write flag in addition to apply.
_Avoid_: tier 3, tier, money field, dangerous field

**Read-back**:
Fetching the listing again after an applied write and comparing it with what was sent, because Hostaway can accept a write and silently discard fields.
_Avoid_: verification, confirm

**Safe reservation fields**:
The fixed allowlist of reservation fields the CLI prints. Guest name, email and phone are never in it.
_Avoid_: PII filter, redaction

**Doctor**:
The offline check that the environment and configuration are complete and consistent, performed without any Hostaway call.
