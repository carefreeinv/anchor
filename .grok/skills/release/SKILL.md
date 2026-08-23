---
name: release
description: >
  Intentional product ship via /release — reports unmerged branches against
  the release base, plan-diff reviews what's already on the base (PASS/PASS
  WITH NOTES/HOLD), then tags and pushes. Never merges — branches reach the
  base through /review or /work's scoped merge. Use when the user runs
  /release, wants to cut a version, or asks what's ready to ship. Not the
  default finish for a single plan — that's /work + optional /push.
argument-hint: "[--dry-run|--since <Nd>|--all-pending|--base <branch>|--exclude <branch>,…|--skip-review]"
disable-model-invocation: false
metadata:
  short-description: "Unmerged-work report → plan-diff review → tag → push (never merges)"
---

# /release — intentional product ship

**Fleet script paths in this file assume the Anchor source tree's own
`scripts/`.** This same file is also scaffolded verbatim into every dependent
project, where fleet tooling lives under **`.anchor/scripts/`** instead —
substitute that prefix throughout when `scripts/<name>.py` isn't at the
project root but `.anchor/scripts/<name>.py` is.

Orchestrates a **release**: which pending branches ship, a review of each
of what is on the base against its plan, then tag → push. It never merges. This is **not** the default
path for finishing a single feature plan — `/work` still ends at a
feature-branch commit plus an optional plain [`/push`](/skills/push).
`/release` is the moment pending branches are offered for inclusion and a
version goes out.

`$ARGUMENTS` is everything after `/release`.

## Usage

| Invocation | Behavior |
|------------|----------|
| (default) | Unmerged-work report + **plan–diff review** + tag/push. **No merging** |
| `/release --dry-run` | Report (+ review if cheap); **no** tag or push |
| `/release --since <Nd>` | Recency window for "recent" unmerged commits (default `30d`) |
| `/release --all-pending` | Ignore recency; every branch ahead of base is a candidate |
| `/release --base <branch>` | Override the release/integration base |
| `/release --exclude <branch>,…` | Pre-seed exclusions (still shows the table; user can change it) |
| `/release --skip-review` | **Explicit only** — skip the plan–diff review (warn loudly; never the default) |

## Fit

This is orchestration-class work: judging whether someone else's diff
matches their plan, catching a lesser model's mistakes before they ship.
Prefer **mid+ / reasoner / frontier** sessions, especially for many branches
or large diffs. If the current session is underqualified for that judgment
call, open with `SUGGEST-ESCALATE: <stronger model> — plan-diff review needs
a model that can catch scope creep and incomplete work` for the review step
(or the whole release) rather than rubber-stamping every branch PASS.

## Steps

### 1. Resolve release base

Default: `dev` if it exists, else `develop`, else `main`/`master` — same
order `scripts/pending_merges.py` uses. `--base <branch>` overrides.

### 2. Unmerged-work report (required before any tag)

`/release` **does not merge.** It tags what is *already* on the release base, so
its job here is to make loudly visible any finished work that will **not** be in
this release — the failure mode is shipping a version that silently omits it.

1. **Inventory candidates** — branches with unmerged commits relative to the
   base. Reuse `scripts/pending_merges.py` (`find_pending`, or the CLI:
   `python scripts/pending_merges.py --since <Nd>` / `--all-pending` /
   `--json`) for ahead-count, last-commit age, worktree, plan lane, and
   `.plans/completed/` slug match — do not hand-roll this in the skill.
2. **Recency filter** (default `30d`, `--since` overrides, `--all-pending`
   disables it): a branch flagged as a completed-plan match is **always**
   listed regardless of age — finished work does not age out.
3. **Classify each candidate by its plan's lane**, because the lane is what
   says whether the work is finished:

   | Plan lane | Reading |
   |-----------|---------|
   | `completed/` | Merged and archived — a branch still ahead here is a leftover; investigate |
   | `review-needed/` | **Finished, awaiting sign-off** — the normal end state of agent work, and the most likely thing to be wrongly omitted |
   | `in-progress/` | Claimed and unfinished — expected to be absent |
   | `bugs/`, `features/` | Ready or returned — expected to be absent |
   | `drafts/` | Not promoted — expected to be absent |
   | none | Unplanned branch — name it; the user decides whether it matters |

4. **Present the table** whenever it is non-empty:

   | Branch | Ahead | Last commit | Plan lane | Notes |
   |--------|-------|-------------|-----------|-------|
   | feature/foo | 3 | 2d ago | review-needed | finished, not in this release |

5. **Stop and confirm (hard).** If anything sits in `completed/` or
   `review-needed/`, say plainly that it is finished work which this release
   will **not** contain, and ask whether to proceed anyway or stop and land it
   first. Landing it is not this skill's job: **`/review`** Approve, or a
   **`/work`** scoped merge, puts a branch on `dev`. An empty candidate list
   needs no prompt — note "no unmerged candidates" and continue.

### 3. Plan–diff review of what is being shipped

Review the commits **already on the release base** since the last tag against
their plans, so the release notes describe what actually shipped and any
concern is recorded rather than discovered later.

- **PASS** — behaves as its plan describes
- **PASS WITH NOTES** — record the concern for the release notes / `## Deferred / concerns`
- **HOLD** — something on the base looks wrong. This does **not** gate a merge
  (there is none); it gates the **tag**: report it and ask before tagging, since
  a tag is the thing that is hard to retract.

`--skip-review` requires an explicit ask and prints the risk before running.

### 4. Ship steps

1. Confirm intent + version — or run [`/tag --suggest`](/skills/tag) and
   accept its suggestion.
2. Ensure the CHANGELOG has a **dated section** for that version (not only
   `[Unreleased]`); fold in notes from the completed plans whose work is on
   the base.
3. Run [`/commit-prep`](/skills/overview) if the tree is dirty; commit a
   version bump if one is needed.
4. [`/tag`](/skills/tag) an annotated tag at the release commit, on the
   release base.
5. Push the release base and the tag (`python scripts/pending_merges.py`
   again is a cheap sanity check that nothing else got left behind) — or
   `gh release create` when `gh` is available and the user wants a GitHub
   Release.
6. Print verify steps: `git describe --tags`, the list of unmerged work this
   release deliberately excludes, and the release URL if one was created.

### `--dry-run`

Run the report (and the plan–diff review, if it's cheap enough to be useful
context) but stop before any tag or push — print exactly what a real run
would do.

## Safety

- **`/release` never merges.** It tags what is already on the release base.
  Branches reach `dev` through **`/review`** Approve or a **`/work`** scoped
  merge, and `main` only through `/review`'s promotion survey — `/release` is
  not a third route onto an integration branch.
- **The unmerged-work confirmation is not optional** when anything sits in
  `completed/` or `review-needed/` — no silently shipping past finished work.
- **Plan–diff review is not optional** — `--skip-review` requires an
  explicit ask and prints the risk before running.
- **HOLD blocks the tag** without an explicit user override after seeing why.
- **Never force-pushes, never rebases a shared branch.**
- **Never invents a new tag scheme** — delegates to `/tag`, which detects
  and matches whatever scheme the repo already uses.
- **Never runs from a session underqualified for the review step** without
  first saying so via `SUGGEST-ESCALATE`.

## Footer

`## Result` · `## How to verify` · `## Deferred / concerns`
