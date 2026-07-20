# Capacity routing — what to do when a subscription runs out

Subscription tiers ration capacity, not just tokens: a session cap, a rolling
5-hour window, a weekly quota. These are **not** failures — they are a scheduling
problem. An agent that hits one and gives up wastes the operator's time; an agent
that hits one and quietly finishes the job on a weaker model wastes something
worse, because the work looks done.

This file is doctrine for both cases. It applies to any Anchor-using agent, but it
pays off most in multi-provider harnesses (Cursor, Cline, OpenRouter-backed tools,
`scripts/endpoints.yaml` fleets) where a second model is genuinely one config line
away.

## Recognize the limit

Treat these as capacity signals, not bugs to debug or retry blindly:

- HTTP **429**, `rate_limit_error`, `insufficient_quota`, `RESOURCE_EXHAUSTED`
- Prose in the response: "usage limit reached", "weekly limit", "you've hit your
  limit", "resets at …", "upgrade to continue"
- A harness banner announcing a cap, or a forced model downgrade you did not ask
  for (the harness silently swapping tiers is the dangerous case — see below)

Distinguish a **capacity** limit from a **transient** one. A short per-minute rate
limit resolves with one backoff and a retry; a session/weekly cap does not. Retrying
a weekly cap in a loop burns nothing but wall-clock and log noise. If the error
names a reset time hours or days out, it is capacity — stop retrying and route.

## Decide: reroute, wait, or stop

Work the order. Take the first that applies.

| Condition | Action |
|---|---|
| Another model in **model priority** is available **and** clears the task's fitness floor | **Reroute.** Checkpoint, restate, continue there. |
| Alternatives exist but all sit **below** the fitness floor for this task | **Wait** if the reset is near; otherwise **stop and report**. Do not demote the task. |
| No alternative configured, reset is soon (minutes to ~an hour) | **Wait**, with a stated resume time. Checkpoint first. |
| No alternative, reset is far (hours/days), or unknown | **Stop and report.** Leave the tree and the plan resumable. |

**The fitness floor is the hard part, and it is the whole point.** Model priority
is an escalation ladder, not a menu of equals. Rerouting a rename or a formatting
pass down a tier costs nothing. Rerouting architecture work, a security review, or
a subtle debugging session down a tier produces confident, wrong output — the exact
failure Anchor exists to prevent. Consult `model-fitness.md`: if the task sits in
the fallback model's weak column, **waiting is the correct answer**, and so is
stopping. Never let a quota reset decide the quality bar.

## Reroute correctly

A different model is a different session with no memory of this one. A reroute that
just re-sends the last prompt loses the plan, the constraints, and every decision
already made.

1. **Checkpoint before you switch.** Write current state where the next model will
   look: the in-progress plan file under `.plans/in-progress/`, or a scratch note
   the operator can point at. Record what is done, what is next, what is verified
   vs. assumed, and which files are mid-edit.
2. **Restate on arrival.** Open the new session with the task spec, the constraints,
   the acceptance criteria, and the checkpoint — the same restate-first discipline
   every Anchor session starts with. Do not assume continuity.
3. **Say the tier changed.** Name the model you moved to and why, in the transcript
   and in the final footer. An operator reading results later must be able to tell
   which tier produced which work.
4. **Re-verify, do not inherit.** Claims made by the previous model are still just
   claims. Anything unverified stays `(unverified)` across the handoff.

## Wait correctly

Waiting is legitimate and is often cheaper than a bad reroute. But wait *visibly*:

- State the reset time (or best estimate, marked `(unverified)` when the provider
  did not give one) and what resumes when it clears.
- Checkpoint first, exactly as for a reroute. A wait that outlives the session must
  not lose state — assume the process dies.
- Prefer one long sleep to a polling loop. Do not burn the remaining quota on
  status checks.
- If a durable timer is available (`/fleet-watch`, systemd timer, cron), hand the
  resume to it rather than holding a session open.

## Never

- **Never silently continue on a downgraded model.** If the harness swaps tiers
  under you, surface it before proceeding, and re-apply the fitness floor.
- **Never weaken the work to fit remaining capacity** — no skipped tests, no
  narrowed scope, no dropped acceptance criteria, to get done before a cap. Running
  out of capacity mid-task is a scheduling outcome; shipping a hollow result is a
  correctness failure.
- **Never fabricate completion.** Partial work reported honestly beats a claimed
  finish. Say what ran, what did not, and where it stopped.
- **Never spend the last of a quota on a retry loop** against a limit that resets
  hours out.

## Report

Whatever the path, the operator gets: the limit hit (provider + kind — session,
weekly, quota), the decision (reroute / wait / stop) and why, the checkpoint
location, and — for a reroute — the model moved to and what still needs
re-verification on the new tier.
