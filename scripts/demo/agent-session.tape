# VHS tape: a real Claude Code session driving hsctl against the demo server.
# Requires the server running fresh, so the audit finds the seeded gaps:
#   uv run python scripts/demo/fake_hostaway.py 8765
# Render:  vhs scripts/demo/agent-session.tape
#
# Fixed pauses per step. VHS's screen-wait only reads the top of the scrollback,
# so it cannot see the agent's step marker once the transcript scrolls past it.
# The idle stretches are cut afterwards, which is what leaves typing, tool calls
# and replies and drops the waiting:
#   ffmpeg -i scripts/demo/out/agent-session.mp4 \
#     -vf "mpdecimate=hi=64*12:lo=64*5:frac=0.33,setpts=N/FRAME_RATE/TB" -an \
#     -c:v libx264 -pix_fmt yuv420p -crf 20 scripts/demo/out/agent-session-cut.mp4
Output scripts/demo/out/agent-session.mp4

Set Shell zsh
Set FontSize 18
Set FontFamily "Menlo"
Set Width 1600
Set Height 1000
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms
Set WindowBar Colorful
Set WindowBarSize 44

Hide
Type "source scripts/demo/agent-shell.sh"
Enter
Type "clear"
Enter
Sleep 1s
Show

Type "claude"
Enter
Sleep 8s

Type "[step 1] We are pointed at a Hostaway sandbox: HOSTAWAY_API_BASE_URL is local and nothing is live. Run uv run hsctl listings and give me a one-line summary per villa."
Enter
Sleep 75s

Type "[step 2] Every villa should carry Smoke detector, First aid kit and Linens as standing inclusions. Read each villa with hsctl listing-amenities and show me a table of what is missing where. Change nothing yet."
Enter
Sleep 180s

Type "[step 3] Prepare the fix. Dry-run hsctl amenities-set for each villa that needs one and show me the before and after. Still nothing applied."
Enter
Sleep 180s

Type "[step 4] Looks right. Send them with --apply, then read each villa back and confirm the amenities landed."
Enter
Sleep 210s

Type "[step 5] One more. Block Villa Saka over Christmas and New Year, 2026-12-20 to 2027-01-05, with a five-night minimum. Dry-run hsctl calendar-set first. Availability is protected, so the send needs --allow-protected as well as --apply."
Enter
Sleep 180s

Type "[step 6] Read the range back, and the day either side of it, so we can see the block did not bleed past the dates I asked for."
Enter
Sleep 120s
