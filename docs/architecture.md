# Architecture

`hostaway-cli` is three layers and a handful of pure modules between them. Reading
downwards: the **command layer** decides what an operator is asking for and what they are
shown; the **session layer** turns that into Hostaway resource calls; the **transport
layer** owns everything about HTTP — authentication, retry, rate limiting and the mapping
of a failure onto a typed error.

Each layer talks only to the one below it. A command never builds a request; a resource
method never touches `httpx`; the transport knows nothing about a diff, a gate or a
terminal.

```text
      hsctl set 1001 --name "Villa Saka" --apply
              │
  command     ▼   cli.py — arguments, banner, diff, gate, read-back, exit codes
  layer           writes.py · payloads.py · listing_payload.py · config.py
              │   reservations.py · export.py · doctor.py
              ▼
  session         session.py — HostawaySession, one account, one base URL
  layer           _bookings · _catalog_reads · _financials · _images · _reviews
              │   models.py · catalogs.py · _envelope.py
              ▼
  transport       _transport.py — the only place httpx is used
  layer           _token.py · _retry.py · _rate_limit.py · errors.py
              │
              ▼
          api.hostaway.com  (or a sandbox base URL)
```

## The command layer

`src/hostaway_cli/cli.py` is the whole of the CLI: every `hsctl` command, its arguments,
and the order in which a write happens. It is one file on purpose — the safety sequence
(diff, gate, apply, read-back, export) is the same for every write, and splitting it
across files is how one command comes to skip a step.

Every command that talks to Hostaway goes through one helper that builds the session and
prints the surface banner before anything is sent, so no command can quietly skip saying
which account and which surface it is on (`docs/adr/0004`).

A write command runs the same six steps:

1. read the listing as it is now;
2. build the change as a list of `Change` — field, before, after;
3. print the diff, and any channel-facing notice, to stdout;
4. stop there unless `--apply`; stop with the protected fields named unless
   `--allow-protected` too (`docs/adr/0001`);
5. send it, then read the listing back and report any field Hostaway accepted and did not
   store;
6. export, if `--export` was typed and the read-back was clean.

Exit codes are part of the interface, because an operator's next move differs by failure:

| Code | Meaning |
| --- | --- |
| `0` | done, or a dry run that sent nothing |
| `1` | Hostaway refused or could not be reached |
| `2` | the environment or the configuration is wrong; nothing was sent |
| `3` | the write gate refused: a protected field without `--allow-protected` |
| `4` | the write landed and was read back, but the export did not |

### What the command layer leans on

These are plain modules: data in, data out, no HTTP and no terminal.

- `src/hostaway_cli/writes.py` — `Change`, the diff rendering, the `PROTECTED_FIELDS` set
  and the read-back comparison. The gate reads the fields in front of it, never the
  command's name: `calendar-set --min-stay 3` is an ordinary write and the same command
  with `--blocked` is a protected one (`docs/adr/0001`).
- `src/hostaway_cli/payloads.py` — pure builders for the listing, amenity and calendar
  write bodies, under Hostaway's own wire names.
- `src/hostaway_cli/listing_payload.py` — merges a YAML draft with the operator's
  configuration into a create or backfill payload, and names what a listing still needs
  before Hostaway will activate it.
- `src/hostaway_cli/config.py` — loads and validates the house defaults, fill-only-if-empty
  fields and markups from the file `HSCTL_CONFIG` names. It holds no operator values, and
  a missing file is an error rather than a fallback (`docs/adr/0002`).
- `src/hostaway_cli/reservations.py` — `SAFE_RESERVATION_FIELDS`, the allowlist of
  reservation fields a terminal is allowed to show. Guest name, email, phone and address
  are absent by design.
- `src/hostaway_cli/export.py` — the channel a listing can be pushed to, and the call that
  pushes it. A save is not an export.
- `src/hostaway_cli/doctor.py` — the offline checks behind `hsctl doctor`. Nothing here
  opens a socket: every check reads the environment, or a file the operator already named.

## The session layer

`src/hostaway_cli/session.py` holds `HostawaySession`, the authenticated client for one
account. It is bound to one account ID and one base URL, so pointing it at a sandbox is a
constructor argument and never a global switch. Listings — the reads, the writes and the
read-back — live in the session itself; each other resource family is a mixin, because
what makes them differ is the resource rather than the HTTP:

| Module | Resource |
| --- | --- |
| `src/hostaway_cli/_bookings.py` | reservation search and paging |
| `src/hostaway_cli/_catalog_reads.py` | amenities, bed types, property types, custom fields, cancellation policies |
| `src/hostaway_cli/_financials.py` | consolidated finance reports and per-reservation totals |
| `src/hostaway_cli/_images.py` | listing image upload and the read-back that proves it |
| `src/hostaway_cli/_reviews.py` | reviews, whose query dialect is its own |

Three modules serve the session rather than a layer of their own:

- `src/hostaway_cli/models.py` — the strict wire contracts, `HostawayListingPage` and
  `HostawayListingImage`, for the places where a nearly-right value is worse than a wrong
  one.
- `src/hostaway_cli/catalogs.py` — validation for catalog rows, the name-and-ID pairs a
  write depends on. Nothing is coerced: an ID that arrives as a string is refused.
- `src/hostaway_cli/_envelope.py` — the permissive readers for the `{status, result,
  count}` envelope every Hostaway page arrives in.

`src/hostaway_cli/__init__.py` is the public surface: `HostawaySession`, the typed errors,
`PROTECTED_FIELDS`, `SAFE_RESERVATION_FIELDS`, `Surface` and the credential and token-cache
types. A caller building its own tooling imports from there and from nowhere deeper.

## The transport layer

`src/hostaway_cli/_transport.py` is the only module that uses `httpx`. It owns the client,
the token, the limiter, the retry wrapping and the translation of every terminal outcome
into a typed error, so a caller never has to catch an HTTP exception to find out what
happened. It is package-private, and a session keeps no transport method on its public
surface.

- `src/hostaway_cli/_token.py` — the OAuth client-credentials lifecycle: one token per
  session, fetched lazily, refreshed before expiry, with concurrent callers serialised so a
  burst cannot start a stampede.
- `src/hostaway_cli/_retry.py` — three attempts, backoff of two then four seconds, and the
  fixed set of outcomes worth retrying.
- `src/hostaway_cli/_rate_limit.py` — the outbound limiter, sized to the two limits
  Hostaway publishes.
- `src/hostaway_cli/errors.py` — the typed error surface. `HostawayError` catches every way
  a call can fail.

## What every layer agrees on

Three facts are settled once, at the edges, and every layer above reads them rather than
deciding for itself.

- `src/hostaway_cli/credentials.py` — the account, secret and base URL, read from the
  environment and nowhere else. No password manager, no vault, no fallback
  (`docs/adr/0003`).
- `src/hostaway_cli/surface.py` — LIVE or SANDBOX, judged from the base URL's host alone.
  A flag can be set wrongly in either direction; the URL cannot be mislabelled
  (`docs/adr/0004`).
- `src/hostaway_cli/token_cache.py` — the optional owner-only file holding one account's
  token between commands. It refuses a file other users can read, refuses one written for
  a different account, and replaces it atomically (`docs/adr/0003`).

## Where the tests sit

Tests are written at three seams, highest first, and no new seam is introduced.

1. **The CLI, through the runner, with the transport's HTTP mocked.** Most tests are here,
   because it is where an operator's experience is: `tests/test_cli_set.py`,
   `tests/test_cli_backfill.py`, `tests/test_cli_export.py` and their neighbours assert on
   the printed diff, the exit code and the request the mocked route received.
2. **`HostawaySession` against mocked routes** — `tests/test_session_writes.py`,
   `tests/test_session_transport.py` and the other `test_session_*` files.
3. **The pure builders as plain functions** — `tests/test_writes.py`,
   `tests/test_listing_payload.py`.

Tests never reach into private helpers, every fixture is invented, and
`tests/test_scrub.py` fails if any denylisted string (generic patterns, plus a private list
a maintainer supplies) appears in a tracked file. `scripts/demo/fake_hostaway.py` serves five invented villas for the demo kit
and its own tests.
