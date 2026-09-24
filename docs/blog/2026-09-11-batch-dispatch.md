---
title: "Run up to 10 plans in parallel: /work --batch"
authors: [carefree]
tags: [feature, work]
---

`/work` has always been able to run in a dedicated per-agent worktree —
nothing stopped two agents from working the backlog at the same time. What
was missing was **picking a batch that's actually safe to run in parallel**:
nothing checked whether two plans were about to rewrite the same file.
`/work --batch [N]` closes that gap.

<!-- truncate -->

## What it does

`scripts/batch_dispatch.py` looks at every ready plan's `## Likely touch
points` (the advisory list `/draft` populates), builds a conservative
conflict graph — two plans conflict if they share an exact path, or one
names a directory that contains the other's file — and greedily selects up
to **N** (default 10) plans with no overlap, respecting the same
Priority → Value → fit → Depends-on ordering `/work` already uses. Selected
plans get claimed and given their own worktree via the existing
`worktree_for_agent.py` machinery — no new isolation mechanism.

```bash
python scripts/batch_dispatch.py --root . --max 10 --tier mid            # preview
python scripts/batch_dispatch.py --root . --max 10 --tier mid --claim    # claim + worktree
```

## What it deliberately does not do

Anchor doesn't run its own agents, and this tool doesn't start. Its output is
a list of prepared plans — path, worktree, feature branch, agent-id — for an
operator or an orchestrating session to hand to separate executor sessions.
A plan with no touch-point data is excluded from the batch entirely rather
than guessed at; it still runs fine through ordinary serial `/work`.

This is about parallel **execution** only. Parallel *review* is a separate
batch mode, `/review --batch`, and this change leaves `/review`'s
one-decision-per-invocation rule untouched.
