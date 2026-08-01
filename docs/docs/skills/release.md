---
sidebar_position: 3.92
sidebar_label: /release · ship a version
---

# `/release`

**Best used:** when it's time to cut a version — not for finishing a single
plan (that's [`/work`](/skills/work) plus an optional [`/push`](/skills/push)).
See [Skills overview](/skills/overview).

`/release` is the moment pending feature branches are offered for inclusion,
reviewed against their plans, merged, tagged, and pushed — in that order,
with hard stops along the way.

## Why use it

| Without `/release` | With `/release` |
|---------------------|------------------|
| Finished branches sit forgotten outside integration | Every unmerged branch is inventoried before a tag ships |
| "Merge everything" with no second look | Each branch gets a **plan–diff review** — scope, completeness, correctness, doctrine, fit |
| A weak executor's mistakes ship silently | HOLD blocks merge until the user overrides after seeing why |
| Tag scheme invented per release | Delegates version detection/creation to [`/tag`](/skills/tag) |

## Usage

| Invocation | Behavior |
|------------|----------|
| (default) | Inventory + exclusion prompt + **plan–diff review** + merge PASS set + tag/push |
| `/release --dry-run` | Inventory (+ review if cheap); no merge, tag, or push |
| `/release --since <Nd>` | Recency window for "recent" unmerged commits (default `30d`) |
| `/release --all-pending` | Ignore recency; every branch ahead of base is a candidate |
| `/release --base <branch>` | Override the release/integration base |
| `/release --exclude <branch>,…` | Pre-seed exclusions (table still shown; user can change it) |
| `/release --skip-review` | Explicit only — skips the plan–diff review, with a printed risk line |

## Pipeline

```text
resolve base (dev → develop → main/master)
  → inventory pending branches (scripts/pending_merges.py)
  → exclusion prompt (hard, if any candidates exist)
  → plan-diff review per included branch → PASS / PASS WITH NOTES / HOLD
  → merge PASS set (HOLD blocks unless overridden)
  → confirm version (or /tag --suggest) → CHANGELOG dated section
  → /commit-prep if dirty → /tag → push base + tag
  → verify (git describe, branch lists, release URL)
```

## The plan–diff review

For each branch making the release, the session running `/release` — not a
rubber stamp — reads the branch's diff against the release base and checks
it against the branch's related plan (resolved from `.plans/completed/` by
slug, or a ready/in-progress match, or flagged **unplanned** if neither
exists). This is the point in the pipeline built specifically to catch a
lesser executor's mistakes — scope creep, an unevidenced `Done when`,
tests left red, secrets, docs restating unfinished plan backlog — while a
stronger reviewer is still in the loop, before any of it lands.

Preferred models for this step: **mid+ / reasoner / frontier**. An
underqualified session opens with `SUGGEST-ESCALATE` for the review rather
than rubber-stamping every branch.

## Safety

- **Exclusion prompt is not optional** once candidates exist.
- **Plan–diff review is not optional** — `--skip-review` is explicit-only
  and prints its risk before running.
- **HOLD blocks merge** without an explicit user override.
- **Never force-pushes, never rebases a shared branch.**
- **Never invents a tag scheme** — delegates to `/tag`.

## Scaffolded?

Yes — dual-use Claude command + Grok skill (`scripts/anchor.py` platform lists).

Full contract: source `.claude/commands/release.md` / `.grok/skills/release/SKILL.md`.
