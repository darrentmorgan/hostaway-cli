# Changelog

Notable changes to `hostaway-cli`, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Nothing has been released yet. `v0.1.0` will be the first tag, and it means the whole of
the list below is true.

## [Unreleased]

### Added

- `hsctl`, a terminal client for one Hostaway account: `doctor`, `listings`, `get`,
  `calendar`, `amenities`, `listing-amenities`, `reservation-lookup`, `set`, `create`,
  `backfill`, `captions`, `calendar-set`, `amenities-set`, `export` and `version`.
- `HostawaySession`, a public async client for the same account, with typed errors, a
  transport that owns authentication, retry and rate limiting, and reads for listings,
  reservations, catalogs, reviews, finances and images.
- The write gate: every mutating command prints a diff and sends nothing until `--apply`,
  and a change touching a protected field needs `--allow-protected` as well
  (`docs/adr/0001`).
- A read-back after every applied write, naming any field Hostaway accepted and did not
  store.
- The surface banner: every command says which account it is on and whether the surface is
  LIVE or SANDBOX, judged from the base URL alone (`docs/adr/0004`).
- Credentials from the environment only, and an optional owner-only token cache that
  refuses to load for a different account (`docs/adr/0003`).
- House defaults, fill-only-if-empty fields and channel markups as operator configuration,
  with an example file shipped and no built-in values (`docs/adr/0002`).
- `reservation-lookup` prints a fixed allowlist of reservation fields; guest name, email
  and phone are never in it.
- A local fake Hostaway server, tapes and narration under `scripts/demo/`, so the tool can
  be tried with invented data and no account.
- An offline test suite, a scrub test that fails on any denylisted real-account string, and
  CI running lint, format, types and tests on Python 3.11 and 3.13.
