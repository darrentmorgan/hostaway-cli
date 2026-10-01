## What

What an operator can do now that they could not before, in a sentence or two. If it fixes
an issue, `Closes #N`.

## Why

The operating problem behind it, if it is not obvious from the title.

## How I know it works

The tests you added and what they prove. A change to a write command says what the dry run
prints and what the read-back reported.

## Checklist

- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and
      `uv run pytest` all pass locally.
- [ ] Tests are offline and every fixture is invented — no real account, listing, guest or
      property name, in code, fixtures or this description.
- [ ] No string from a production Hostaway account (ids, names, contacts) is in the diff.
- [ ] `CHANGELOG.md` has an entry under `Unreleased`, if an operator would notice this.
- [ ] The vocabulary matches `CONTEXT.md`: applied, dry run, protected field, read-back,
      surface.

## Anything a reviewer should look at twice

Delete what does not apply.

- A new or changed **protected field**, or anything that changes when the gate refuses.
- A new **environment variable**, configuration key or exit code.
- A change to the **surface banner**, the credentials path or the token cache.
- A new field in `SAFE_RESERVATION_FIELDS` — say why it carries nobody's personal details.
- A new **dependency**, with `uv.lock` committed alongside `pyproject.toml`.
- A decision that belongs in an ADR under `docs/adr/`.
