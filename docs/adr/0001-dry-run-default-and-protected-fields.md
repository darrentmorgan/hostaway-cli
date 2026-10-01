---
status: accepted
---
# Every write is a dry run unless applied, and protected fields need a second flag

hostaway-cli drives a production booking system. Every mutating command prints the before and after diff and exits; the apply flag sends it; a protected field (price, currency, fees, deposit, commission, calendar availability, deletion) additionally requires the protected-write flag, and the command prints which protected fields it is about to touch. We chose two flags over one because the operator's habit of typing the apply flag must not be enough to move money; and over a hard refusal because an API-permitted write that the operator has explicitly confirmed should complete, with the diff and read-back as the guardrail rather than a human hand on a different keyboard.

## Consequences

- The flags are `--apply` and `--allow-protected`. A command is protected only when a protected field is actually in the change: calendar-set with only a minimum stay is an ordinary write; with availability it is protected. Markups are ordinary writes.

- Every applied write is followed by a read-back and the difference is reported; Hostaway can accept a write and silently drop fields.
- Per-field confirmation on channel-connected listings is operator practice documented in the README, not enforced in code.
