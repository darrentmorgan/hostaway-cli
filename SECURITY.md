# Security policy

`hostaway-cli` holds an API secret for a live booking account and can change prices,
availability and content on it. A defect in it is a defect in somebody's business, so
please report one privately and give us a chance to fix it first.

## Supported versions

Nothing is released yet. Until `v0.1.0` is tagged, the supported version is the current
`main` branch; after it, the latest tag. Older tags get no backports.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private vulnerability reporting: the
repository's **Security** tab, then **Report a vulnerability**. It is private to the
maintainers, and it gives you a place to attach details without publishing them.

If that form is not available to you, contact the maintainer through their GitHub profile
and ask for a security contact — a public issue asking "is there a security contact?" is
fine, a public issue containing the finding is not.

Please include what you would want if you were fixing it: what an attacker can do, the
version or commit you saw it on, and the smallest reproduction you have. Never include a
real account ID, a real secret, a real listing or a real guest's details — invent them, as
the test suite does.

Expect an acknowledgement within a week. If the report holds up we will agree a disclosure
timeline with you, credit you in the advisory unless you would rather we did not, and fix
it in the open once a release carrying the fix exists. There is no bug bounty.

### Not this repository

- **A vulnerability in Hostaway itself** — their API, their dashboard, their data — is
  theirs to receive, not ours. Report it to Hostaway.
- **A secret you have leaked** is an emergency for your account, not a defect here. Rotate
  the secret in Hostaway first, then delete any token cache file (`HSCTL_TOKEN_CACHE`
  names it), then tell us if you think this tool helped it escape.

## What this tool promises

These are the properties a report can be measured against. If you can break one, that is a
vulnerability:

- **Credentials come from the environment and nowhere else.** No password manager, no
  vault, no keychain, no fallback, and no credential is ever written to the repository or
  printed by a command (`docs/adr/0003`).
- **The token cache is owner-only, atomic and account-bound.** `hsctl` refuses to read a
  cache file other users can read, refuses one written for a different account, and
  replaces it atomically so a killed command cannot leave a torn token behind.
- **Secrets are never accepted on the command line**, where a shell history would keep
  them. A door code comes from `HSCTL_DOOR_CODE`, a wifi password from
  `HSCTL_WIFI_PASSWORD`, and both are shown as `***` in a diff.
- **A reservation shows an allowlist of fields.** Guest name, email address, phone number
  and address are not in `SAFE_RESERVATION_FIELDS` and a field Hostaway adds later is not
  printed until somebody puts it there deliberately.
- **No write reaches Hostaway without `--apply`**, and none touching a protected field
  reaches it without `--allow-protected` as well (`docs/adr/0001`).
- **The surface banner cannot lie.** LIVE is decided by the base URL's host alone, so no
  flag, environment variable or configuration key can make a live account read as a
  sandbox (`docs/adr/0004`).
- **The tree carries no operator's data.** Every fixture is invented, and
  `tests/test_scrub.py` fails the build if a real account, listing, property or contact
  string appears in a tracked file.

## What is not a vulnerability

- `hsctl` can change a listing, a price or a calendar. That is the tool, not a flaw. The
  guardrails are the dry run, the two flags and the read-back, and an operator who types
  both flags has decided.
- An applied write reached a channel. Content is exported deliberately, and the command
  says so before it does it.
- A dependency has a published advisory that this tool cannot reach: tell us anyway, but
  it goes in a normal issue.
