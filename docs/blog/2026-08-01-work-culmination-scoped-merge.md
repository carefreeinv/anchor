---
title: "`/work` now ends with a question: review, merge, or hold"
authors: [carefree]
tags: [feature, doctrine, tooling, skills]
---

Until now, only a `/review` survey could land a branch on `dev`. That rule is
amended: a `/work` session may merge its own finished work onto integration — when
the operator answers its end-of-run question in-session, and the branch passes a
mechanical scoped-merge gate.

<!-- truncate -->

## The gap this closes

Getting finished work from a plan into `dev` was the least legible part of the
workflow. `/work` committed on `feature/<slug>`, moved the plan to
`review-needed/`, said "run `/review`", and stopped. Nothing showed how much other
work was already queued behind that same door, and a one-line change paid a full
review cycle — or quietly stalled in a worktree nobody revisited.

## The culmination question

After green `/commit-prep` gates and a successful feature-branch commit, an
**interactive** `/work` asks once:

```text
Plan '<slug>' is done and committed on feature/<slug>. What now?
  1. Review it now (default) — /review does an AI critic pass, then you sign off
  2. Merge to dev now — I checked the work; land it without a review cycle
  3. Hold for testing — leave the branch and worktree; I'll come back to it
```

Answer 3 is the one that did not exist before in any form: finished work you
deliberately park, recorded as a `## Handoff` hold note so it reads as *parked*
rather than *ignored*.

## What the operator is trusting

The merge route trades the AI critic for a narrower mandate — you watched the work
happen — so the gate's job is to prove nothing *else* rode along. All six must
hold:

**Provenance** (the branch head is the commit this run just made) · **clean tree** ·
**file scope** (every changed path inside the run's declared touched set) ·
**mergeable** (fast-forward preferred) · **target is integration only** (a
`main`/`master` target aborts the path) · and the **human answer** itself.

```bash
python scripts/merge_feature.py --root <checkout> --slug <slug> \
  --touched touched.txt --expect-head <sha> --dry-run
# 0 would merge · 3 scope violation · 4 precondition · 5 conflict · 2 git error
```

Any failure falls back to `/review`, naming the check that refused. Refusing is
always the safe outcome — the failure mode is a false refusal, never a silent
over-merge. That principle is why the gate refuses on *missing* facts too: an empty
touched set, an absent `--expect-head`, or a `--base` that would narrow the diff are
all refusals rather than checks quietly skipped.

The helper has **no `--yes` flag**, on purpose. Five checks are mechanical; the
sixth is the operator's answer, and a flag is exactly the inference this path
forbids — a flag a human can pass is a flag a fleet worker can pass. Unattended
runs (`work_once.py`, fleet workers, the coordinator MCP) never ask and never
merge; they finish to `review-needed/` exactly as before.

One thing is rejected outright: landing only the in-scope paths when the scope
check fails. Cherry-picking files out of a branch fabricates a commit matching no
branch state and hides the out-of-scope change. A scope violation means the branch
is not what `/work` thinks it is — precisely when a human review earns its cost.

## Seeing what has not landed

`pending_merges.py` now answers *where* the work sits, not just that it is ahead:

```bash
python scripts/pending_merges.py           # branch · target · ahead · worktree · plan lane · held
python scripts/pending_merges.py --brief
# handoff: 3 branch(es) ahead of dev · 1 completed awaiting merge · 1 held
```

Git is the authority on worktree paths; a `registry.json` entry git no longer knows
about is still shown, labeled `stale registry`. `/commit-prep` prints this table
after its three gates — **advisory, not a fourth gate**. Unmerged branches are the
normal state of a healthy repo; they never make prep red, and prep still commits
nothing.

## `main` did not move

`/review` remains the only route to mainline, through its empty-queue promotion
survey, and the only route for work you did not just watch happen. The full ladder
now reads:

```text
feature/<slug>  →  (/review Approve | /work scoped merge)  →  dev  →  (/review Promote)  →  main
```

Every skipped review stays auditable: the plan lands in `completed/` carrying
`merged to dev by /work <date> — no /review sign-off`.
