# Narration script: the agent session clip

Play the rendered clip with the mic on and read this over it, pausing the video
whenever a line needs more time than the screen gives it. The cues are what appears
on screen, not timestamps.

**Cue: `claude` starts, the step 1 prompt is typed**
> This is hsctl, a command-line client for one Hostaway account, driven by an agent.
> Everything on screen is a local sandbox with invented villas. Every command prints
> the account and the surface, and the surface here says SANDBOX, so nothing is live.
> First I ask it to list the portfolio.

**Cue: the five-row listings table, then the one-line summaries**
> Five villas. Before doing anything it orients itself and reads each listing back.
> No writes yet.

**Cue: the step 2 prompt, then the amenity reads**
> Now the audit. Every villa should carry a smoke detector, a first aid kit and linens.
> I have told it to report and change nothing.

**Cue: the missing-amenities table**
> Two villas are short. Villa Anaya has no smoke detector and no first aid kit. Villa
> Padma has no smoke detector and no linens. The other three are complete.

**Cue: the step 3 prompt, then the dry-run diffs**
> Next I ask for the fix as a proposal. Every write in this tool is a dry run until you
> say otherwise, so what you see is the exact before and after, with the amenity IDs,
> and the line saying nothing was sent. Amenities merge against what the listing already
> has, because Hostaway replaces the whole set on every write, so this only adds.

**Cue: the step 4 prompt, then the "Applied." lines**
> This is the beat that matters. I approve, it sends the same command with one more
> flag, and then it reads each listing back rather than trusting the answer. Hostaway
> can accept a write, report success and store none of it.

**Cue: the read-back lines, then the amenities on each villa**
> The three standing inclusions on both villas, each field confirmed by a second read
> rather than by the response to the write.

**Cue: the step 5 prompt, the calendar, then the refusal**
> One more workflow. Block Villa Saka over Christmas and New Year with a five-night
> minimum. The minimum stay is an ordinary write. Closing the nights is not: availability
> moves bookings, so it is a protected field, and the apply flag on its own is refused
> with the protected fields named and nothing sent.

**Cue: the same command with `--allow-protected`, then "Applied."**
> Said on purpose, with the second flag, it goes. Seventeen nights closed, minimum five,
> and the prices untouched — this command cannot reach a price at all.

**Cue: step 6, the range read back with the days either side**
> And it checks the day on each side of the range to prove the block did not bleed past
> the dates I asked for.

**Cue: the last step marker**
> That is the pattern. Read, propose, approve, apply, verify. A dry run by default, a
> second flag for anything that moves money or bookings, and a read-back after every
> write that lands.
