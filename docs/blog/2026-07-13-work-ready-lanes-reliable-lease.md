---
title: /work picks ready lanes only, with a reliable claim lease
authors: [carefree]
tags: [fix, tooling]
---

Bare **`/work`** now selects only from ready lanes (`bugs/`, `features/`) and never
scans `in-progress/`. In-progress plans are owned by a required lease — so several
agents can share one project without ever stealing each other's work.

<!-- truncate -->

## The collision it fixes

`/work` used to try to be helpful by resuming "your" in-progress plans first. To do
that it had to reason about *ownership* of everything under `in-progress/` — and
ownership was fragile. Leases were **optional** (interactive `/work` often just did
a `git mv`), and the lease TTL was a short **1 hour**. So an in-progress plan that a
live agent was actively working — but hadn't leased, or whose hour had lapsed —
looked *stalled* to a second agent's `/work`, which could then silently reclaim it.
Two agents, one plan.

## What changed

- **Bare `/work` is ready-lanes-only.** It never scans `in-progress/` to resume or
  reclaim. Resuming your own work is now an explicit named target
  (`/work in-progress/<slug>.md`), and only if you hold the lease.
- **Claiming is atomic and required.** Moving a ready plan into `in-progress/`
  writes its lease under `.plans/.leases/` in the same step. The lease is what marks
  the plan yours; a bare `git mv` with no lease is no longer how you claim.
- **Long TTL + heartbeat.** The lease TTL is now **24h**, and a live agent extends
  it with a heartbeat, so slow-but-alive work never looks orphaned:

  ```bash
  python scripts/work_once.py --heartbeat in-progress/foo.md --agent-id worker-1
  ```

- **No silent reclaim.** A foreign, unleased, or expired-lease in-progress plan is
  never auto-taken. Recovering genuinely-abandoned work (a crashed agent past the
  24h TTL) is an explicit choice:

  ```bash
  python scripts/work_once.py --recover --path in-progress/foo.md --agent-id worker-2
  ```

## A deterministic picker for smaller models

Less-reliable models shouldn't have to reason about lanes and leases by hand. There
is now a single command that prints exactly one next ready plan — or a clear
"nothing ready" (exit `1`) — and, with `--claim`, performs the move-and-lease
itself:

```bash
python scripts/plan_select.py --next                       # print the next ready plan
python scripts/plan_select.py --next --claim --agent-id w1  # claim it atomically
python scripts/plan_select.py --next --json                 # machine-readable
```

## Multi-agent by default

The project-orchestrator MCP moves with the same rules: `plans_claim` gains a
`recover` flag, there's a new `plans_heartbeat` tool, and `plans_complete` now moves
an agent-finished plan to `review-needed/` for human sign-off rather than straight to
`completed/`. Unique `--agent-id` per worker, required leases, and no silent reclaim
are what let a fleet pull from one backlog safely.
