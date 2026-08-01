---
description: Intentional product ship — branch intake, exclusion prompt, plan-diff review, merge, tag, push
argument-hint: "[--dry-run|--since <Nd>|--all-pending|--base <branch>|--exclude <branch>,…|--skip-review]"
---

# /release — intentional product ship

Orchestrates a **release**: which pending branches ship, a review of each
one against its plan, then merge → tag → push. This is **not** the default
path for finishing a single feature plan — `/work` still ends at a
feature-branch commit plus an optional plain [`/push`](/skills/push).
`/release` is the moment pending branches are offered for inclusion and a
version goes out.

`$ARGUMENTS` is everything after `/release`.

## Usage

| Invocation | Behavior |
|------------|----------|
| (default) | Inventory + exclusion prompt + **plan–diff review** + merge PASS set + tag/push |
| `/release --dry-run` | Inventory (+ review if cheap); **no** merge, tag, or push |
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

### 2. Branch intake (required before any tag)

Releases must not silently omit finished work sitting on feature branches.

1. **Inventory candidates** — branches with unmerged commits relative to the
   base. Reuse `scripts/pending_merges.py` (`find_pending`, or the CLI:
   `python scripts/pending_merges.py --since <Nd>` / `--all-pending` /
   `--json`) for ahead-count, last-commit age, and `.plans/completed/` slug
   match — do not hand-roll this in the skill.
2. **Recency filter** (default `30d`, `--since` overrides, `--all-pending`
   disables it): a branch flagged as a completed-plan match is **always**
   included regardless of age — finished work does not age out.
3. **Present a candidate table** whenever it is non-empty:

   | Branch | Ahead | Last commit | Completed plan? | Notes |
   |--------|-------|-------------|-----------------|-------|
   | feature/foo | 3 | 2d ago | yes (`foo`) | |

4. **Exclusion prompt (hard).** If any candidates exist, **stop and ask**
   which branches (if any) to exclude. Default assumption: include all
   listed candidates unless the user names exclusions (by name, glob, or
   "exclude completed-only" / "exclude WIP-only"). `--exclude` pre-seeds
   this but the table and the question are still shown. **Do not** merge,
   review, or continue toward a tag until this is answered when the list is
   non-empty. An empty candidate list needs no prompt — note "no unmerged
   candidates" and continue.

### 3. Plan–diff review (hard, after the include set is known)

For **each included branch**, the current session — not a rubber stamp —
reads its diff against the release base and checks it against the related
plan, before any merge. This is the one place in the release pipeline that
catches a lesser executor's mistakes (scope creep, missing `Done when`,
wrong files touched, tests left red, secrets, docs written from unfinished
plan backlog) while a stronger reviewer is still in the loop.

**Resolve the related plan**, in order:
1. `feature/<slug>` → `.plans/completed/*<slug>*` (date prefix and
   `.local.md` both allowed)
2. Else a ready/in-progress plan matching that slug
3. Else commit-message / branch-name heuristics; if still nothing, review as
   **unplanned** and flag it for the human — prefer excluding an unplanned
   branch unless the user insists on including it anyway

**Collect the diff:**
```bash
git log --oneline <base>..<branch>
git diff --stat <base>...<branch>
git diff <base>...<branch>        # full if small; else --stat + samples of the changed paths
```
Cap huge diffs: summarize by path and open the full diff only for
critical/high-risk paths. Never write PASS without having actually read
Goal / Done when / Steps against the touched files.

**Review checklist**, one row of judgment per branch:

| Check | Fails if… |
|-------|-----------|
| Scope | Diff touches paths outside the plan's Goal / Steps / files-in-scope signals |
| Completeness | Plan's `Done when` items aren't evidenced by the diff, tests, or commits |
| Correctness signals | Obvious bugs, incomplete renames, a TODO/FIXME left as the only "fix", a verify command that's cheap to re-run and fails |
| Doctrine | Docs/CHANGELOG restating unfinished plan backlog as shipped, secrets, force-push residue |
| Fit | Diff reads like thrash, wrong-tier work, or an unrelated drive-by |

**Verdict per branch:**
- **PASS** — merge as-is
- **PASS WITH NOTES** — merge OK; record the concern for release notes / `## Deferred / concerns`
- **HOLD** — do not merge; report findings; the user may exclude it, send it
  back to the feature branch to fix, or explicitly say "merge anyway" after
  seeing the HOLD reason

Present a **review table** (branch, plan path/slug, verdict, one-line
reason) before merging anything. **Default:** stop for user confirmation if
any branch is HOLD; otherwise merge the PASS / PASS WITH NOTES set.
`--skip-review` is opt-in only — print the risk (lesser-model errors may
ship unreviewed) before honoring it, never assume it.

### 4. Merge included, reviewed branches

One branch at a time, fast-forward when possible, otherwise a normal merge
with a stop-on-conflict (never force, never rebase a shared branch unless
the user explicitly opts in). Report each merge result. On conflict: stop,
leave the tree for the human or `/work` to resolve, do **not** tag. Never
merge a HOLD branch without the explicit override described above. Never
delete a feature branch unless the user asks.

Only continue to ship steps once merges succeed (or there was nothing to
merge).

### 5. Ship steps

1. Confirm intent + version — or run [`/tag --suggest`](/skills/tag) and
   accept its suggestion.
2. Ensure the CHANGELOG has a **dated section** for that version (not only
   `[Unreleased]`); fold in notes from the branches just merged / their
   completed plans when that's cheap.
3. Run [`/commit-prep`](/skills/overview) if the tree is dirty; commit a
   version bump if one is needed.
4. [`/tag`](/skills/tag) an annotated tag at the release commit, on the
   release base.
5. Push the release base and the tag (`python scripts/pending_merges.py`
   again is a cheap sanity check that nothing else got left behind) — or
   `gh release create` when `gh` is available and the user wants a GitHub
   Release.
6. Print verify steps: `git describe --tags`, the included/excluded branch
   lists, and the release URL if one was created.

### `--dry-run`

Run inventory (and the plan–diff review, if it's cheap enough to be useful
context) but stop before any merge, tag, or push — print exactly what a
real run would do.

## Safety

- **Exclusion prompt is not optional** when candidates exist — no silent
  default-include past that point.
- **Plan–diff review is not optional** — `--skip-review` requires an
  explicit ask and prints the risk before running.
- **HOLD blocks merge** without an explicit user override after seeing why.
- **Never force-pushes, never rebases a shared branch**, never merges an
  excluded or HOLD branch silently.
- **Never invents a new tag scheme** — delegates to `/tag`, which detects
  and matches whatever scheme the repo already uses.
- **Never runs from a session underqualified for the review step** without
  first saying so via `SUGGEST-ESCALATE`.

## Footer

`## Result` · `## How to verify` · `## Deferred / concerns`
