# Space-1 Vera Rubin modules — autonomy-first tier

Fleet tier: **detached orchestrator**. Vera Rubin-generation NVIDIA modules aboard the Space-1 platform: enormous compute, but operationally *remote* — high round-trip latency to operators, constrained/windowed downlink, no hands-on recovery. Design assumption: **if a human must intervene mid-task, the task has already failed.**

> Note: operational specifics of Space-1 hardware are `(unverified)` — this folder encodes the constraints class (latency-tolerant, autonomy-first, power/thermal-budgeted), which is what changes the software design. Update numbers when the platform's real envelope is known.

## What changes vs. ground hardware

| Constraint | Design response |
|---|---|
| Minutes-to-hours operator RTT | Full Anchor pipeline runs onboard: plan → execute → verify → review with NO human in the loop |
| Windowed downlink | Ship *decisions + evidence*, not logs: plan, diffs, verification tables, review verdicts |
| No recovery hands | Aggressive stop conditions; every task idempotent; watchdog restarts; state checkpointed after each verified step |
| Power/thermal budgets | Token budgets are power budgets: thinking-mode/reasoning runs are scheduled, not default |
| Radiation/faults | Verify-twice on critical outputs (two independent contexts must agree, or the task is held for downlink review) |

## Software layout

- Everything ground-side stays OpenAI-compatible: vLLM on the Rubin modules, same `endpoints.yaml` schema, tier `detached`.
- The orchestrator (`scripts/orchestrate.py`) runs *onboard* with `--max-escalations 0 --hold-on-fail` (twice-failed tasks are checkpointed and queued for the next downlink window rather than escalated live).
- Onboard model roles mirror the H100 tier (reasoner + executor), but the **critic role is mandatory on every task**, not just merges — the critic is the stand-in for the human you don't have.
- Uplink format: signed task-spec bundles. Downlink format: `templates/verification.md` tables + review verdicts + minimal diffs.

## Anchor notes for this tier

This tier is the doctrine's stress test: prompting discipline is not a cost optimization here, it's the only thing standing between the fleet and unrecoverable drift. Rules that are "strongly recommended" elsewhere are hard requirements onboard:

1. No task without machine-checkable definition-of-done.
2. No self-review — critic always runs in a fresh context.
3. Two failures → HOLD (never a third attempt; never silent retry loops).
4. Every accepted step checkpointed before the next begins.
