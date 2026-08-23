---
title: "/push and /release — publish, then ship, as two deliberate steps"
authors: [carefree]
tags: [feature, skills]
---

**`/push`** publishes the current branch and nothing else. **`/release`**
is the moment pending branches get reviewed and a version goes out. Neither
one does the other's job.

<!-- truncate -->

## Why two skills, not one

"Push my branch" and "cut a release" are different requests with different
blast radii, and collapsing them tends to produce a `/deploy`-style skill
that quietly does too much: a routine push that also drags in three
forgotten feature branches, or a release that never got a second look at
what it actually shipped.

`/push` stays thin on purpose — confirm, push, done. `/release` stays
deliberate on purpose — nothing already on the release base ships without
being reviewed first, and `/release` itself never merges a branch onto it.

## `/push`

```bash
/push              # confirm remote + branch, git push -u
/push --tags       # also push tags already reachable from HEAD (after a separate confirm)
/push --prep       # run /commit-prep first; stop if red
```

No force by default, ever — not even on your own feature branch. A push to
`main`/`master`/`dev`/`develop` prints a risk line and asks first, even
under an otherwise non-interactive flow. It never creates a tag and never
merges.

## `/release`

`/release` never merges. Every branch with unmerged commits gets reported
against the release base (`dev`, else `develop`, else mainline), classified
by its plan's lane — a branch sitting in `review-needed/`, the normal end
state of finished agent work, is the thing most likely to be wrongly left
out, so it's called out by name rather than silently omitted. This reuses
the same `pending_merges.py` logic `/review` already relies on — now
extended with a recency window (`--since`, default 30 days) that always
keeps completed-plan branches regardless of age, so finished work never
quietly ages out of consideration.

```text
unmerged-work report (classified by plan lane)
  → stop-and-confirm (hard, whenever completed/ or review-needed/ work is missing from the base)
  → plan-diff review of what is already on the base → PASS / PASS WITH NOTES / HOLD
  → confirm version → CHANGELOG → /tag → push
```

Landing a branch on the base is not this skill's job: a **`/review`**
Approve, or a **`/work`** scoped merge, does that. `/release` picks up only
once work is already there.

## The plan–diff review is the point

Before a version ships, the session running `/release` reads the diff of
what's already on the release base against the branch's actual plan —
scope, whether `Done when` is evidenced, obvious correctness gaps, doctrine
violations, fit. This is the one place in the whole pipeline built
specifically to catch a lesser executor's mistakes while a stronger
reviewer is still watching, before a version ships with them in it. A
**HOLD** verdict blocks the **tag** until the user either fixes the branch,
or explicitly overrides after seeing why — there is no merge step for it to
block.

`--skip-review` exists, but it's explicit-only and prints exactly what
you're giving up before it runs.

Docs: [`/push`](/skills/push), [`/release`](/skills/release). Sources:
`.claude/commands/{push,release}.md` and
`.grok/skills/{push,release}/SKILL.md`, both scaffolded into projects by
`anchor`.
