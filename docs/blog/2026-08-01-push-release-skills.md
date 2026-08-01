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
deliberate on purpose — nothing merges without being reviewed first.

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

Every branch with unmerged commits gets inventoried against the release
base (`dev`, else `develop`, else mainline), using the same
`pending_merges.py` logic `/review` already relies on — now extended with a
recency window (`--since`, default 30 days) that always keeps
completed-plan branches regardless of age, so finished work never quietly
ages out of consideration.

```text
inventory pending branches
  → exclusion prompt (hard, whenever candidates exist)
  → plan-diff review per included branch → PASS / PASS WITH NOTES / HOLD
  → merge the reviewed set (HOLD blocks unless overridden)
  → confirm version → CHANGELOG → /tag → push
```

## The plan–diff review is the point

Before any branch merges, the session running `/release` reads its diff
against the release base and checks it against the branch's actual plan —
scope, whether `Done when` is evidenced, obvious correctness gaps, doctrine
violations, fit. This is the one place in the whole pipeline built
specifically to catch a lesser executor's mistakes while a stronger
reviewer is still watching, before any of it ships. A **HOLD** verdict
blocks the merge until the user either fixes it, excludes the branch, or
explicitly says "merge anyway" after seeing why.

`--skip-review` exists, but it's explicit-only and prints exactly what
you're giving up before it runs.

Docs: [`/push`](/skills/push), [`/release`](/skills/release). Sources:
`.claude/commands/{push,release}.md` and
`.grok/skills/{push,release}/SKILL.md`, both scaffolded into projects by
`anchor`.
