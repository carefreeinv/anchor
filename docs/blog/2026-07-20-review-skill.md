---
title: "/review — AI critic, then a human survey"
authors: [carefree]
tags: [feature, docs]
---

The `review-needed/` lane held finished work for human eyes. **`/review`** is
how those eyes work: one plan, an AI pass, then Approve / Needs Work / Skip.

<!-- truncate -->

## The missing UX

Moving a plan into `review-needed/` was already doctrine. What was missing was a
**human-facing session** that:

1. Checks out `feature/<slug>` without stomping a dirty tree
2. Runs a **fresh-context** critic against the plan and the branch diff
3. Asks a clear survey instead of hoping free-text “lgtm” means what you think
4. Turns “needs work” into **actionable notes** and a return to the **ready**
   queue (`bugs/` or `features/`), not a silent re-claim to `in-progress/`

## What `/review` does

**One plan per invocation.** Bare `/review` picks by Priority → Value → oldest
mtime; other queued plans get a one-line mention only. Re-run for the next item.

Pipeline (fixed):

```text
select → checkout → evidence + optional launch
       → AI code review (fresh context)
       → present package
       → survey → follow-ups → lane move
```

| Survey | Move |
|--------|------|
| **Approve** | → `completed/` (override required if the critic said REVISE/ESCALATE) |
| **Needs Work** | → `bugs/` or `features/` (same inference as `/draft --promote`) |
| **Skip** | stay in `review-needed/` |

AI is **advisory**. The human survey is authoritative. Agents still must not
complete from `review-needed/` outside a confirmed Approve.

## Where it ships

- Claude: `.claude/commands/review.md`
- Grok: `.grok/skills/review/SKILL.md`
- Docs: [Skills → `/review`](/skills/review)
- Scaffolded into projects with the other dual-use skills

Pair with the earlier [review-needed lane](/blog/2026-07-12-review-needed-lane)
post: lane first, skill second — “done” is no longer the same event as
“completed.”
