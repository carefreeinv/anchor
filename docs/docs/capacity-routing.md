---
sidebar_position: 5
sidebar_label: Capacity Routing
---

<!-- synced-from: anchor/capacity-routing.md @ bedddfbcecb88b54c94ab5a8512df7a80878d462 -->

# Capacity routing

Subscription tiers ration capacity, not just tokens: a session cap, a rolling five-hour window, a weekly quota. Anchor treats hitting one as a **scheduling problem**, not a failure. An agent that hits a cap and gives up wastes your time; an agent that hits a cap and quietly finishes on a weaker model wastes something worse, because the work looks done.

This doctrine ships to every scaffolded project as `.anchor/capacity-routing.md`, and it pays off most in multi-provider harnesses — Cursor, Cline, OpenRouter-backed tools, or an `endpoints.yaml` fleet — where a second model is one config line away.

## Recognize the limit

Capacity signals are HTTP **429**, `rate_limit_error`, `insufficient_quota`, `RESOURCE_EXHAUSTED`, prose like "usage limit reached" / "weekly limit" / "resets at …", a harness banner announcing a cap, or a forced model downgrade you did not ask for.

Distinguish **capacity** from **transient**. A per-minute rate limit resolves with one backoff and a retry; a session or weekly cap does not. If the error names a reset hours or days out, stop retrying and route — a retry loop against a weekly cap buys nothing but wall-clock and log noise.

## Decide: reroute, wait, or stop

Work the order and take the first that applies.

| Condition | Action |
|---|---|
| Another model in **model priority** is available **and** clears the task's fitness floor | **Reroute.** Checkpoint, restate, continue there. |
| Alternatives exist but all sit **below** the fitness floor | **Wait** if reset is near; otherwise **stop and report**. Do not demote the task. |
| No alternative, reset soon (minutes to ~an hour) | **Wait**, with a stated resume time. Checkpoint first. |
| No alternative, reset far or unknown | **Stop and report.** Leave the tree and plan resumable. |

The fitness floor is the whole point. [Model priority](/skills/overview) is an escalation ladder, not a menu of equals. Rerouting a rename or a formatting pass down a tier costs nothing; rerouting architecture work, a security review, or a subtle debugging session down a tier produces confident, wrong output — the exact failure Anchor exists to prevent. Consult [model fitness](/model-fitness): if the task lands in the fallback model's weak column, **waiting is correct**, and so is stopping. Never let a quota reset decide the quality bar.

## Reroute correctly

A different model is a different session with no memory of this one. Re-sending the last prompt loses the plan, the constraints, and every decision already made.

**Checkpoint before switching** — write state where the next model will look (the in-progress plan file under `.plans/in-progress/`, or a scratch note): what's done, what's next, what's verified vs. assumed, which files are mid-edit. **Restate on arrival** with the task spec, constraints, and acceptance criteria, the same restate-first discipline every Anchor session opens with. **Say the tier changed**, in the transcript and the footer, so anyone reading results later can tell which tier produced which work. **Re-verify rather than inherit** — the previous model's claims are still claims, and anything unverified stays `(unverified)` across the handoff.

## Wait correctly

Waiting is legitimate and often cheaper than a bad reroute — but wait visibly. State the reset time (marked `(unverified)` when the provider didn't give one) and what resumes when it clears. Checkpoint first and assume the process dies. Prefer one long sleep to a polling loop, and don't spend remaining quota on status checks. When a durable timer is available — [`/fleet-watch`](/skills/fleet-watch), a systemd timer, cron — hand the resume to it rather than holding a session open.

## Never

Never silently continue on a downgraded model; if the harness swaps tiers under you, surface it and re-apply the fitness floor. Never weaken the work to fit remaining capacity — no skipped tests, no narrowed scope, no dropped acceptance criteria to finish before a cap. Never fabricate completion: partial work reported honestly beats a claimed finish. Never spend the last of a quota retrying a limit that resets hours out.

## Report

Whatever the path, the operator gets the limit hit (provider and kind — session, weekly, quota), the decision and why, the checkpoint location, and for a reroute, the model moved to and what still needs re-verification on the new tier.
