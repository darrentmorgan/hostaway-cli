# Contributing

Thanks for looking. `hostaway-cli` drives a production booking system, so the bar for a
change is a little higher than usual: a bug here can move somebody's money or somebody's
booking. Nothing below is ceremony — it is the set of habits that keep that from
happening.

## The toolchain

[uv](https://docs.astral.sh/uv/) and Python 3.11 or newer. `.python-version` pins 3.13 for
local work; CI runs 3.11 and 3.13. There is no `pip` path and no `requirements.txt`.

```sh
git clone https://github.com/darrentmorgan/hostaway-cli
cd hostaway-cli
uv sync --locked
uv run hsctl --help
```

`uv sync --locked` is what CI runs, so it fails rather than quietly re-resolving when
`uv.lock` has fallen behind `pyproject.toml`. If you change a dependency, run `uv sync` and
commit the updated `uv.lock` with it.

## The checks

Run all four before you push. They are the same four CI runs on every pull request, in the
same order, so a green run here is a green run there:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

`uv run ruff format .` writes the formatting the third-last line only checks. mypy is
`strict = true` over `src`, `tests` and `scripts/demo`: a new module arrives fully
annotated or not at all.

## Tests

The suite is offline. It never opens a socket to Hostaway, needs no secret, and must pass
on a laptop with no account at all — HTTP is mocked at the transport with `respx`, and
`scripts/demo/fake_hostaway.py` serves five invented villas for the demo kit's own tests.

Tests are written at three seams, and no new seam is introduced. Prefer the highest one
that can show the behaviour:

1. **The CLI through the test runner**, with the transport's HTTP mocked. Most tests are
   here, because it is where an operator's experience is. Assert on the printed diff, the
   exit code, or the request the mocked route received.
2. **`HostawaySession` against mocked routes**, for behaviour that belongs to the session
   or the transport rather than to a command.
3. **The pure builders as plain functions**, for payload and diff logic.

A test never reaches into a private helper: a leading-underscore function is free to change
shape, and a test that names one breaks on a refactor that changed no behaviour. See
`docs/architecture.md` for what lives at each seam.

Every fixture is invented — made-up villas, made-up IDs, made-up prices. Do not paste a
real listing, a real reservation or a real account ID into this repository, in a test, a
document or a commit message. `tests/test_scrub.py` scans tracked files for generic patterns from
`tests/scrub_denylist.example.txt`, and for any private denylist a maintainer points
`HSCTL_SCRUB_DENYLIST` at (or keeps in a git-ignored local file beside it named `scrub_denylist.local.txt`).
Never commit real identifiers, not even into a denylist.

### Live tests

A test that reaches a real Hostaway account is marked `@pytest.mark.live` and is skipped
unless you opt in:

```sh
HOSTAWAY_LIVE_TESTS=1 uv run pytest -m live
```

You need your own account, your own secret in the environment, and the knowledge that a
live test costs a request and can leave a mark. **CI never sets `HOSTAWAY_LIVE_TESTS`**,
so a live test can neither pass nor fail a pull request — which means a live test is never
the only proof a change works. Write the offline test too.

## The safety model is not optional

Four decisions shape every command, and a change that erodes one needs an ADR of its own
before it needs a pull request. They are `docs/adr/0001` to `docs/adr/0004`:

- every write is a dry run until `--apply`, and a protected field needs `--allow-protected`
  as well;
- the gate reads the fields in the change, never the command's name;
- every applied write is read back, and a field Hostaway silently dropped is reported;
- house defaults come from the operator's configuration, credentials come from the
  environment, and the surface banner is judged from the base URL.

If you add a command that writes, it does all of that, and it does it through the same
helpers in `src/hostaway_cli/writes.py` as everything else.

## Vocabulary

`CONTEXT.md` is the project's dictionary. The words it settles are the words to use in
code, tests, help text, commit messages and documents: a write is **applied**, an unapplied one is a **dry run**, a field
that moves money or bookings is a **protected field**, re-reading after a write is a
**read-back**, and LIVE or SANDBOX is the **surface**. Each entry lists the words it
displaces, and `tests/test_docs.py` fails a document that keeps one. If you find yourself
needing a word the dictionary has not got, add it there in the same change.

## Pull requests

- One change per pull request, with a conventional commit subject (`feat:`, `fix:`,
  `docs:`, `refactor:`, `test:`, `chore:`).
- Say what an operator can now do that they could not before, and what you did to be sure.
- Note anything a reviewer should look at twice: a new protected field, a changed exit
  code, a new environment variable, a dependency.
- Add an entry to `CHANGELOG.md` under `Unreleased` for anything an operator would notice.
- CI has to be green. It runs the four checks above on 3.11 and 3.13, plus the scrub.

## Reporting a vulnerability

Not here, and not in a public issue — see `SECURITY.md`.
