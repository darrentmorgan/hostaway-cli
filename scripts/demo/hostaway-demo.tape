# VHS tape: the scripted hsctl intro, no audio. Requires the demo server:
#   uv run python scripts/demo/fake_hostaway.py 8765
# Render:  vhs scripts/demo/hostaway-demo.tape
# Restart the server before every render: an applied write lasts its lifetime.
Output scripts/demo/out/hostaway-demo.mp4
Output scripts/demo/out/hostaway-demo.gif

Set Shell zsh
Set FontSize 20
Set FontFamily "Menlo"
Set Width 1600
Set Height 900
Set Padding 30
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set WindowBar Colorful
Set WindowBarSize 44

Hide
Type "source scripts/demo/env.demo && alias hsctl='uv run hsctl' && setopt interactive_comments && clear"
Enter
Sleep 2s
Show

Type "# Your whole portfolio, from the terminal. Every command says which surface."
Enter
Sleep 1.5s
Type "hsctl listings"
Enter
Sleep 5s

Type "clear"
Enter
Type "# One listing in full, as JSON. The banner is on stderr, so a pipe stays clean."
Enter
Sleep 1s
Type "hsctl get 1003 | head -16"
Enter
Sleep 4.5s

Type "clear"
Enter
Type "# Availability and nightly rates across a date range."
Enter
Sleep 1s
Type "hsctl calendar 1001 --start 2027-01-08 --end 2027-01-15"
Enter
Sleep 5s

Type "clear"
Enter
Type "# Every villa should carry a smoke detector and a first aid kit. This one does not."
Enter
Sleep 1s
Type "hsctl listing-amenities 1003"
Enter
Sleep 4.5s

Type "clear"
Enter
Type "# Writes preview and stop. Nothing is sent without --apply."
Enter
Sleep 1s
Type "hsctl amenities-set 1003 --add 'Smoke detector' --add 'First aid kit'"
Enter
Sleep 5s

Type "clear"
Enter
Type "# Happy with the diff? Apply it, and hsctl reads the listing back to check it landed."
Enter
Sleep 1s
Type "hsctl amenities-set 1003 --add 'Smoke detector' --add 'First aid kit' --apply"
Enter
Sleep 5s

Type "clear"
Enter
Type "# A peak-season minimum stay across 17 nights is an ordinary write."
Enter
Sleep 1s
Type "hsctl calendar-set 1001 --start 2026-12-20 --end 2027-01-05 --min-stay 5 --apply"
Enter
Sleep 5s

Type "clear"
Enter
Type "# Closing the same nights moves bookings, so --apply on its own is refused."
Enter
Sleep 1s
Type "hsctl calendar-set 1001 --start 2026-12-20 --end 2027-01-05 --blocked --apply"
Enter
Sleep 5s

Type "clear"
Enter
Type "# Say so on purpose and it goes, previewed, applied and read back."
Enter
Sleep 1s
Type "hsctl calendar-set 1001 --start 2026-12-20 --end 2027-01-05 --blocked --apply --allow-protected"
Enter
Sleep 6s

Type "clear"
Enter
Type "# Reconcile a booking by its channel reference. Guest details are never printed."
Enter
Sleep 1s
Type "hsctl reservation-lookup --reservation-id DEMOAIRBNB01 --departure-start 2027-01-01 --departure-end 2027-01-31"
Enter
Sleep 6s

Type "clear"
Enter
Type "# hsctl: dry run by default, a second flag for money and availability, read back every time."
Enter
Sleep 5s
