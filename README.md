# hostaway-cli

`hsctl` is a terminal and Python client for operating one Hostaway account safely.
Every write is a dry run until you pass `--apply`; protected fields need `--allow-protected` as well;
every applied write is read back and compared.

Status: public, pre-release (v0.1, rough edges, feedback welcome). Nothing is tagged yet.
`CONTEXT.md` holds the vocabulary, `docs/adr/` the
decisions that shape it, and work is tracked in GitHub Issues.

## Install

There is no PyPI release yet, so `hsctl` installs from this repository with
[uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/darrentmorgan/hostaway-cli
hsctl version
```

That puts `hsctl` on your PATH in an environment of its own — nothing is added to a project
you are working on. To try it once without installing anything:

```sh
uvx --from git+https://github.com/darrentmorgan/hostaway-cli hsctl --help
```

Add `@` and a tag to pin a release once there is one
(`git+https://github.com/darrentmorgan/hostaway-cli@v0.1.0`), and
`uv tool upgrade hostaway-cli` to move up. Python 3.11 or newer is required; uv fetches one
if you have not got it.

The examples below type `hsctl` as an installed command. From a clone, prefix them with
`uv run` — see `CONTRIBUTING.md`.

## Credentials

`hsctl` reads your account ID and secret from the environment and nowhere else, so you can
keep them in any secret manager you like (`docs/adr/0003`). A `.env` file beside the project
is read too; an exported variable always wins over the file.

| Variable | | |
| --- | --- | --- |
| `HOSTAWAY_ACCOUNT_ID` | required | your numeric Hostaway account ID |
| `HOSTAWAY_SECRET_KEY` | required | that account's API secret |
| `HOSTAWAY_API_BASE_URL` | optional | defaults to `https://api.hostaway.com/v1` |
| `HSCTL_TOKEN_CACHE` | optional | path to the token cache file |
| `HSCTL_CONFIG` | optional | path to your configuration file; `create` and `backfill` refuse without it |
| `HSCTL_DOOR_CODE` | optional | the door code `hsctl set --door-code` writes |
| `HSCTL_WIFI_PASSWORD` | optional | the wifi password a `backfill` draft needs |

That is the whole list. The last two are secrets, so they are read from the environment
rather than taken on the command line, where a shell history would keep them.

```sh
export HOSTAWAY_ACCOUNT_ID=123456
export HOSTAWAY_SECRET_KEY=...
hsctl listings
hsctl get 100001
```

### The surface banner

Every command that talks to Hostaway prints one line to stderr before it sends anything:

```
hsctl LIVE | account 123456 | https://api.hostaway.com/v1
```

`LIVE` appears only when the base URL's host is `api.hostaway.com`; any other base URL — a
demo server, a stand-in, a proxy — is `SANDBOX`. The judgement is made from the URL alone,
never from a flag, because a flag can be set wrongly in either direction (`docs/adr/0004`).
The banner goes to stderr, so `hsctl get 100001 > listing.json` still gets clean JSON.

### The token cache

A Hostaway token is valid for years, so `HSCTL_TOKEN_CACHE` can point at a file where one
survives between commands:

```sh
export HSCTL_TOKEN_CACHE=~/.cache/hsctl/token.json
```

The file holds a live credential, so `hsctl` refuses to read it unless only its owner can
(mode `0600`), refuses it outright if it was written for a different account, and replaces
it atomically whenever it fetches a token. It is optional; without it every command
authenticates first. Give each account a file of its own.

## Configuration

House defaults, fill-only-if-empty fields and channel markups are yours, not the tool's.
`hsctl` reads them from a YAML file that `HSCTL_CONFIG` points at, and ships no built-in
values: a command that needs them and cannot find the file fails rather than applying
somebody else's house defaults (`docs/adr/0002`).

```sh
cp src/hostaway_cli/config.example.yaml ~/.config/hsctl/config.yaml
export HSCTL_CONFIG=~/.config/hsctl/config.yaml
```

The example documents every key. Its values are invented, so edit it against your own
account before you create or backfill a listing.

## Checking your setup

`hsctl doctor` looks at the whole setup at once and calls Hostaway not at all, so you can
find a missing secret or an unsafe token cache before a command that matters:

```
$ hsctl doctor
PASS  credentials    account 123456, secret key set, both from the environment
PASS  surface        LIVE | https://api.hostaway.com/v1
PASS  token cache    /home/you/.cache/hsctl/token.json is mode 0600 and holds a live token for account 123456
WARN  configuration  HSCTL_CONFIG is not set; reads are fine, but create and backfill will refuse without house defaults
```

Every check reports, whatever the ones before it found. `FAIL` means something is wrong and
`doctor` exits `2`; `WARN` means something optional is absent — no token cache, no
configuration — and does not. The report goes to stdout and the verdict to stderr.

## Reads

```sh
hsctl listings                              # ID, name, internal name, channel status
hsctl get 100001                            # one listing in full, as JSON
hsctl reservation-lookup --departure-start 2026-07-01 --departure-end 2026-07-31
hsctl calendar 100001 --start 2026-07-01 --end 2026-07-07
hsctl amenities --search wifi               # the account's amenity catalog
hsctl listing-amenities 100001              # one listing's amenities, resolved to names
```

`reservation-lookup` searches by check-out window, which is required and bounded; add
`--listing` to narrow it to one listing, or `--reservation-id` (repeatable) to name exact
reservations by their Hostaway or channel ID. It prints JSON to stdout, so it pipes.

### Safe reservation fields

A reservation carries somebody else's name, email address and phone number, and a terminal is
scrolled back, piped and logged. So `reservation-lookup` prints an allowlist rather than
stripping a blocklist: `SAFE_RESERVATION_FIELDS` in `src/hostaway_cli/reservations.py` is the
whole of what an operator sees, and a field Hostaway adds later stays unprinted until somebody
puts it there on purpose.

| | |
| --- | --- |
| Identity | `id`, `reservationId`, `channelReservationId`, `channelName` |
| Listing | `listingMapId`, `listingName` |
| Stay | `arrivalDate`, `departureDate`, `status` |
| Money | `totalPrice`, `currency`, `currencyCode`, `paymentStatus` |

Guest name, guest email, phone and guest address are deliberately absent and must not be added.
The constant is exported from the package, so tooling built on `HostawaySession` can print the
same set.

## Writes

Every mutating command prints the before-and-after diff and sends nothing. `--apply` sends
it. If the change touches a **protected field** — one whose change moves money or bookings —
the command also needs `--allow-protected`, and without it exits non-zero with the protected
fields named and nothing sent (`docs/adr/0001`).

```sh
hsctl set 1001 --name "Villa Saka"                   # diff only, nothing sent
hsctl set 1001 --name "Villa Saka" --apply           # sent, then read back
```

The protected fields are one constant, `hostaway_cli.PROTECTED_FIELDS`:

| Protected | Ordinary |
| --- | --- |
| price, currency | channel markups |
| cleaning fee, damage deposit | minimum and maximum stay |
| commission / payout formula | arrival and departure closures, calendar notes |
| calendar availability | listing content, amenities, captions |
| deletion of a listing or a photo | |

The gate reads the change, not the command: `calendar-set --min-stay 3` is an ordinary write,
and the same command with `--blocked` is a protected one.

Every applied write is read back and compared field by field, because Hostaway can accept a
write, answer success and silently store none of it. A field that did not land is named and
the command exits non-zero.

```
Applied. Read-back:
  name: stored
  city: dropped — Hostaway reported success and did not store it
Dropped by Hostaway: city.
```

### The commands

```sh
# Any listing field. The named options cover the common ones; --field reaches the rest
# under Hostaway's own wire key, protected fields included.
hsctl set 1001 --max-guests 8 --field externalListingName="Villa Saka" --apply
hsctl set 1001 --field price=575 --apply --allow-protected

# Amenities merge against the listing's current set, because a write replaces all of it.
hsctl amenities-set 1001 --add "Washing machine" --remove 11 --apply

# Stays, closures and notes are ordinary; availability is protected.
hsctl calendar-set 1001 --start 2026-08-01 --end 2026-08-31 --min-stay 3 --apply
hsctl calendar-set 1001 --start 2026-08-01 --end 2026-08-07 --blocked --apply --allow-protected

# Captions from a plan file: [{"id": 501, "caption": "Pool at dusk"}, ...]
hsctl captions 1001 captions.json --apply

# A new listing from a YAML draft, with the configured house defaults merged in.
# Every create carries a price, so every create is a protected write.
hsctl create draft.yaml --apply --allow-protected

# The same house defaults onto a listing that already exists, filling only what it
# does not already say.
hsctl backfill 1001 --apply
```

### Creating a listing

`hsctl create` builds a listing from a YAML draft and your own house defaults. The draft is
the property's facts; the configuration says what your account does with every listing. There
is no built-in fallback, so a create without `HSCTL_CONFIG` — or pointed at a file that is not
there — prints the error, exits `2` and sends nothing (`docs/adr/0002`).

```sh
export HSCTL_CONFIG=~/.config/hsctl/config.yaml
hsctl create draft.yaml                                     # the whole payload, nothing sent
hsctl create draft.yaml --apply --allow-protected           # POSTed once, then read back
```

The draft names catalog values rather than IDs, because an ID means nothing outside the
account that published it: `property_type`, each bed's `bed_type`, every entry in
`hostaway_amenities`, and `map_link_custom_field` are matched against your account's own
catalogs, whatever their case, and a numeric ID your catalog publishes is accepted too.
`property_type` and `hostaway_amenities` are optional; when absent the fields are left out of the payload.
`internalListingName` is the property name unless `listing_name_template` is set in the config (for example `"{portfolio}-{property_slug}"`).
`roomType` and `maxNights` are sent only if the draft (`room_type`, `max_stay`) or the config's `house_defaults` supplies them.
`tests/fixtures/villa-nira-draft.yaml` is a complete, invented example.

Before it sends, `create` reads the account and refuses a title a listing already carries: a
create cannot be retried or taken back, and two listings of one name read alike in every table
afterwards. It then prints the merged payload, names the money fields in it, and checks the
seven fields Hostaway needs to activate a listing. That completeness rule, including
`guestsIncluded` and `priceForExtraPerson`, is this tool's own opinion and is unverified against
Hostaway's API; supply them via `fees.extra_guest_after` and `fees.extra_guest_fee` in the draft.

Creating is a protected write. Every payload carries a price, a currency, a cleaning fee and a
deposit, and the gate reads the change rather than the command, so an applied create needs
`--allow-protected` as well as `--apply`. A create is also the one write that can be neither
retried nor taken back, which is the last place to make the second flag optional.

A draft the builder cannot map — a bed with no `room_id`, a `check_in` time that is not an
hour — is refused by name, exits `2` and sends nothing.

`create` takes no `--export`. A listing is exported once it is ready, with
`hsctl export <id> --apply`.

### Backfilling an existing listing

`hsctl backfill` writes the same house defaults onto a listing that is already there. It
reads the listing first and proposes only what the listing does not already say:

- a field already carrying the configured value is not a change, and never appears;
- a **fill-only-if-empty** field carrying anything at all is left alone and named, because a
  house default is a convention and an operator's edit is a decision. `--force` writes over
  them;
- empty means absent, `null`, blank text or an empty list. A `0` is an answer, not a gap.

```sh
hsctl backfill 1001                           # what it would write, nothing sent
hsctl backfill 1001 --apply                   # sent, then read back
hsctl backfill 1001 --force --apply           # the contact block too, over what is there
```

Like `create`, it refuses without `HSCTL_CONFIG`: there is no built-in house default to fall
back on (`docs/adr/0002`). A listing that already answers the whole configuration prints
`nothing to backfill` and makes no request, `--apply` or not.

`--markups` adds the configured channel multipliers. They are **ordinary** fields — a markup
multiplies an amount rather than being one — so they need no `--allow-protected`; they are off
by default because a multiplier that rides along with a content backfill is not one you chose.
A house default that *is* a protected field, a cleaning fee say, still stops the command
without `--allow-protected`: the gate reads the change, not the command.

An optional draft adds the property's own facts a create has no place for — its Vrbo headline,
floor area, wifi network and bed configuration:

```sh
export HSCTL_WIFI_PASSWORD='...'
hsctl backfill 1001 draft.yaml --apply --export
```

The wifi password comes from `HSCTL_WIFI_PASSWORD` and the diff shows `***`. Without it a
draft naming a network still gets its dry run — you cannot approve a diff you cannot see
— but `--apply` refuses rather than publishing a network name with no password. A draft describing
no beds writes no `listingBedTypes` at all: that field replaces the whole set, so an empty
array would delete every bed.

`listingImages` is replace-semantics: the array sent becomes the whole photo set. `captions`
therefore rebuilds it from the live listing, and a plan that omits a live photo is asking for
that photo to be deleted — a protected change. A door code or wifi password is never accepted
on the command line, where it would survive in shell history: `--door-code` reads it from
`HSCTL_DOOR_CODE`, `backfill` reads the network password from `HSCTL_WIFI_PASSWORD`, and the
diff shows `***`.

On a channel-connected listing, read the diff field by field before applying: a saved edit can
propagate to Airbnb or Booking.com, and some fields lock on the channel side after the first
export. That is operator practice, not something the tool enforces.

## Export

A save is not an export. Hostaway stores an edit, but only booking settings reach a channel
on their own: listing content, amenities and captions stay invisible to guests until the listing
is **exported**. `hsctl export` is the one command whose effect lands past Hostaway, so it says
so every time and, like a write, sends nothing until `--apply`:

```sh
hsctl export 1001                    # says what it would do, sends nothing
hsctl export 1001 --apply            # queued; the channel reflects it in a few minutes
hsctl export 1001 --channel airbnb --apply
```

`--channel` takes `airbnb`, which is the whole of what Hostaway exposes to this client today.
Any other value is refused before a request is built.

Writes that change content take `--export`, which fires the export once the write has been
applied **and** read back:

```sh
hsctl set 1001 --description "..." --apply --export
hsctl amenities-set 1001 --add "Washing machine" --apply --export
hsctl captions 1001 captions.json --apply --export
```

A run carrying `--export` is channel-facing, and says so beside the diff rather than after the
fact: the notice naming the channel prints in the dry run, where `--apply` is still untyped.

`--export` never fires in a dry run — there is nothing saved to export — and never fires after a
read-back that found a dropped field. `calendar-set` has no `--export`: availability, stays and
closures are booking settings, and those do reach a channel on their own.

If the write lands and the export then fails, the command says both, because the two ask for
different repairs — the listing is right on Hostaway and stale on the channel, and re-running the
write would fix nothing:

```
Applied. Read-back:
  description: stored
Verified.
Export to airbnb FAILED — but the write applied and was verified. The listing is saved on
Hostaway and stale on the channel; re-run: hsctl export 1001 --apply
```

That case exits `4`, its own code: `1` is Hostaway refusing, `2` is a setup problem, `3` is the
protected-field gate refusing to send.

## Trying it without a Hostaway account

`scripts/demo/` holds a local demo server with five invented villas, and the VHS tapes and
narration that record the CLI against it. Nothing there touches a real account, listing,
guest or price.

```sh
uv run python scripts/demo/fake_hostaway.py 8765 &
source scripts/demo/env.demo
uv run hsctl listings          # the banner must read "hsctl SANDBOX"
```

The base URL is what makes it a sandbox, so every command banners `SANDBOX` in front of
it. Two of the five villas are seeded short of one amenity (an invented example, not a recommended set), which is what the demo
audits and then fixes. See `scripts/demo/README.md`.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer (`.python-version` pins 3.13 for local work).

```sh
uv sync
uv run hsctl --help
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

The same four checks run in GitHub Actions on every pull request, on Python 3.11 and 3.13.

- Tests are offline. A test that reaches a real Hostaway account is marked `live` and is skipped
  unless `HOSTAWAY_LIVE_TESTS=1` is set; CI never sets it.
- `tests/test_scrub.py` fails if any string in a maintainer-supplied denylist (see
  `tests/scrub_denylist.example.txt`) appears in a tracked file, so real account details stay
  out of the tree. The real-identifier check skips when no denylist is configured.

`CONTRIBUTING.md` has the whole of it: the seams tests are written at, the live-test opt-in
and what a pull request is expected to carry.

## Further reading

| | |
| --- | --- |
| `CONTEXT.md` | the vocabulary: what a listing, a surface, a protected field and a read-back are |
| `docs/architecture.md` | the command, session and transport layers, and what each one owns |
| `docs/adr/` | the four decisions behind the safety model |
| `CONTRIBUTING.md` | toolchain, checks, test seams, live tests |
| `SECURITY.md` | reporting a vulnerability, and what this tool promises |
| `CHANGELOG.md` | what has changed |

## Licence

MIT. See `LICENSE`.
