# hsctl demo kit

Everything here runs against a local demo server with five invented villas. No real
account, listing, guest or price appears on screen. Writes mutate that server's memory
and vanish when it stops.

Every command below is run from the repository root.

## Files

| File | Purpose |
| --- | --- |
| `fake_hostaway.py` | Stand-in Hostaway API: five synthetic villas, their calendars, catalogs and two reservations. |
| `env.demo` | Points `hsctl` at the demo server. Contains no credentials. |
| `hostaway-demo.tape` | VHS script for the scripted CLI clip, no audio. |
| `agent-session.tape` | VHS script that drives a real Claude Code session against the sandbox. |
| `agent-shell.sh` | Sourced by the agent tape: sandbox environment plus the Claude Code flags it needs. |
| `NARRATION.md` | Read-aloud script for the agent clip, cued to what appears on screen. |
| `record-voiceover.sh` | Records a mic take over a rendered clip and muxes it. |
| `out/` | Rendered mp4 and gif. Gitignored. |

## The demo account

Account `424242`, five villas, and a seeded gap for the audit to find. `hsctl` reads
the surface from the base URL alone, so pointing it at `127.0.0.1` is what makes every
command banner `SANDBOX` (ADR 0004 in `docs/adr/`). If the banner ever reads `LIVE`, stop.

| Listing | Villa | Missing |
| --- | --- | --- |
| 1001 | Villa Saka | — |
| 1002 | Villa Nira | — |
| 1003 | Villa Anaya | Smoke detector, First aid kit |
| 1004 | Villa Sereno | — |
| 1005 | Villa Padma | Smoke detector, Linens |

Two reservations check out in January 2027, and the calendar shows the nights they
occupy. Restart the server to put the seeded gaps back.

## Try it by hand

```sh
uv run python scripts/demo/fake_hostaway.py 8765 &
source scripts/demo/env.demo
uv run hsctl listings          # the banner must read "hsctl SANDBOX"
uv run hsctl listing-amenities 1003
uv run hsctl amenities-set 1003 --add 'Smoke detector' --apply
```

## Clip 1: the scripted CLI intro

```sh
pkill -f fake_hostaway.py; uv run python scripts/demo/fake_hostaway.py 8765 >/dev/null 2>&1 &
vhs scripts/demo/hostaway-demo.tape
```

Restart the demo server before every render: applied writes persist for its lifetime,
so a second take would open on a listing that already has its smoke detector.

## Clip 2: the agent session

```sh
pkill -f fake_hostaway.py; uv run python scripts/demo/fake_hostaway.py 8765 >/dev/null 2>&1 &
vhs scripts/demo/agent-session.tape          # ~16 min, fixed pauses per step
ffmpeg -i scripts/demo/out/agent-session.mp4 \
  -vf "mpdecimate=hi=64*12:lo=64*5:frac=0.33,setpts=N/FRAME_RATE/TB" -an \
  -c:v libx264 -pix_fmt yuv420p -crf 20 scripts/demo/out/agent-session-cut.mp4
```

The tape uses fixed pauses because VHS's screen-wait only reads the top of the
scrollback and cannot see the agent's per-step marker once the transcript scrolls.
The ffmpeg pass drops frames that did not change, which removes the waiting and leaves
the typing, the tool calls and the replies. For a voiceover, slow the tables back down
in an editor or narrate over the uncut take.

### Recording it on camera instead

The story is: an agent audits the portfolio, proposes a diff, you say yes, it applies
and verifies.

```sh
pkill -f fake_hostaway.py; uv run python scripts/demo/fake_hostaway.py 8765 >/dev/null 2>&1 &
source scripts/demo/env.demo
uv run hsctl listings      # the banner must read "hsctl SANDBOX"
clear && claude
```

The environment is inherited by Claude Code's shell, so every `hsctl` call the agent
makes hits the demo server. Paste the prompts in `agent-session.tape` one at a time and
pause after each so the output settles on screen.

If the agent asks for confirmation before a write, that is the repository's own safety
gate working on camera: a write is a dry run until `--apply`, and availability, price
and fees need `--allow-protected` as well (ADR 0001 in `docs/adr/`). Answer "yes,
sandbox, go ahead" and keep rolling.

## Voiceover

Two ways, both over an already-rendered clip:

- **Loom.** Open the clip, start Loom with the mic on, and read `NARRATION.md`, pausing
  the video wherever a line needs more time. One take, no editor.
- **`record-voiceover.sh`.** Plays the clip in QuickTime, records the mic and muxes to
  `*-voiced.mp4`. Re-run to retake. Use this for a clean clip with no Loom frame.

Before recording: terminal font 18 to 20 pt, window around 1600x900, dock hidden, other
windows closed, and the demo server restarted so the audit finds the seeded gaps.
