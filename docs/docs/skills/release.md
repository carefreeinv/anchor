---
sidebar_position: 3.92
sidebar_label: /release · ship a version
---

# `/release`

**Best used:** when it's time to cut a version — not for finishing a single
plan (that's [`/work`](/skills/work) plus an optional [`/push`](/skills/push)).
See [Skills overview](/skills/overview).

`/release` never merges. It reports finished work that is **not** yet on the
release base (so nothing ships silently omitted), plan–diff reviews what
**is** already on the base against its plan, then tags and pushes — in that
order, with hard stops along the way. Branches reach the base through
[`/review`](/skills/review) Approve or a [`/work`](/skills/work) scoped
merge; `/release` is not a third route onto an integration branch.

## Why use it

| Without `/release` | With `/release` |
|---------------------|------------------|
| Finished branches sit forgotten outside integration | Every unmerged branch is reported before a tag ships, classified by its plan's lane |
| A version ships with no second look at what's already on the base | Each shipping branch gets a **plan–diff review** — scope, completeness, correctness, doctrine, fit |
| A weak executor's mistakes ship silently | HOLD blocks the tag until the user overrides after seeing why |
| Tag scheme invented per release | Delegates version detection/creation to [`/tag`](/skills/tag) |

## Usage

| Invocation | Behavior |
|------------|----------|
| (default) | Unmerged-work report + **plan–diff review** + tag/push. **No merging** |
| `/release --dry-run` | Report (+ review if cheap); no tag or push |
| `/release --since <Nd>` | Recency window for "recent" unmerged commits (default `30d`) |
| `/release --all-pending` | Ignore recency; every branch ahead of base is a candidate |
| `/release --base <branch>` | Override the release/integration base |
| `/release --exclude <branch>,…` | Pre-seed exclusions (table still shown; user can change it) |
| `/release --skip-review` | Explicit only — skips the plan–diff review, with a printed risk line |

## Pipeline

```text
resolve base (dev → develop → main/master)
  → unmerged-work report (scripts/pending_merges.py), classified by plan lane
  → stop-and-confirm (hard, if anything sits in completed/ or review-needed/)
  → plan-diff review of what is already on the base → PASS / PASS WITH NOTES / HOLD
  → confirm version (or /tag --suggest) → CHANGELOG dated section
  → /commit-prep if dirty → /tag → push base + tag
  → verify (git describe, excluded/unmerged work list, release URL)
```

## The plan–diff review

For each set of commits already on the release base since the last tag, the
session running `/release` — not a rubber stamp — reads the diff and checks
it against the related plan (resolved from `.plans/completed/` by slug, or a
ready/in-progress match, or flagged **unplanned** if neither exists). This is
the point in the pipeline built specifically to catch a lesser executor's
mistakes — scope creep, an unevidenced `Done when`, tests left red, secrets,
docs restating unfinished plan backlog — while a stronger reviewer is still
in the loop, before a version ships with them in it.

Preferred models for this step: **mid+ / reasoner / frontier**. An
underqualified session opens with `SUGGEST-ESCALATE` for the review rather
than rubber-stamping everything PASS.

## Safety

- **`/release` never merges.** It tags what is already on the release base;
  branches reach `dev` through `/review` Approve or a `/work` scoped merge,
  and `main` only through `/review`'s promotion survey.
- **The unmerged-work confirmation is not optional** when anything sits in
  `completed/` or `review-needed/` — no silently shipping past finished work.
- **Plan–diff review is not optional** — `--skip-review` is explicit-only
  and prints its risk before running.
- **HOLD blocks the tag** without an explicit user override after seeing why.
- **Never force-pushes, never rebases a shared branch.**
- **Never invents a tag scheme** — delegates to `/tag`.

## Scaffolded?

Yes — dual-use Claude command + Grok skill (`scripts/anchor.py` platform lists).

Full contract: source `.claude/commands/release.md` / `.grok/skills/release/SKILL.md`.
