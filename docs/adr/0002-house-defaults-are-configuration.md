---
status: accepted
---
# House defaults, fill-only-if-empty fields and markups are operator configuration, not code

Cancellation policy IDs, the contact block and channel markups were once module constants. In a shared tool those values are wrong for every other account and leak commercial detail. They live in a per-account configuration file located through the environment; the package ships an example file and refuses to create or backfill a listing when the file is absent, rather than falling back to any built-in value.
