---
description: Pre-commit pass — run & fix tests, update release notes, blog significant changes
---

Prepare the working tree for a commit. Work the three gates in order; don't move on
while an earlier gate is red. `$ARGUMENTS`, if present, is a hint about what the
pending commit is about — use it to focus the release notes and blog decision.

## Gate 1 — tests: run and fix

1. From the repo root, run what CI runs (`.github/workflows/ci.yml`):
   - `ruff check .`
   - `pytest -q`
   - `python3 scripts/check_docs_sync.py`
   - if `config.sh` or `bin/anchor` changed: `shellcheck config.sh bin/anchor`
   - if `docs/` changed and `docs/node_modules` exists: `cd docs && npm run build`
     (skip with a note otherwise)
2. Fix failures and re-run. Anchor stop rule applies: after **two** failed fix attempts
   on the same failure, stop and surface it — don't thrash.
3. Never weaken, skip, or delete a test just to go green; if a test seems wrong,
   say so and let the user decide.

## Gate 2 — release notes

1. Review what the commit will contain: `git status` and `git diff` (plus
   `git diff --cached` if things are staged).
2. Add one line per **user-visible** change under the `## [Unreleased]` section of
   `CHANGELOG.md`, in the appropriate `### Added` / `### Changed` / `### Fixed`
   subsection. Imperative mood, mention the file/flag/command a user would touch.
   Skip internal churn (refactors, test-only changes) — the changelog is for operators.
   **Hard rule — docs describe current state, not plans:** CHANGELOG, blog, and docs
   cover **shipped** code only. Never restate `.plans/` contents (drafts, backlog,
   unfinished acceptance) as release notes or product docs. When plan work ships,
   document the code — not the plan file. (Anchor repo: `.plans/` is private backlog;
   same rule, extra care.)

## Gate 3 — blog post (only when warranted)

Write a Docusaurus blog post **only if** the commit introduces or significantly
updates/fixes a user-facing capability: a new tool/command, a new platform or
hardware tier, a breaking behavior change, or a headline fix. For routine changes,
state in one line why no post is needed and stop here.

When warranted:

- File: `docs/blog/YYYY-MM-DD-<slug>.md` (today's date, kebab-case slug).
- Front matter: `title`, `authors: [carefree]`, `tags:` from `docs/blog/tags.yml`.
- Lead paragraph, then `<!-- truncate -->`, then 3–8 short paragraphs: what changed,
  why an operator cares, how to use it (real commands from the **shipped** diff).
- Cross-check every claim against the diff — the post must not promise anything the
  code doesn't do, and must not source “coming soon” from `.plans/`. Mark anything
  you couldn't verify `(unverified)`.

## Finish

Summarize: test status per check, CHANGELOG entries added, blog post path (or the
one-line reason none was written). Do **not** run `git commit` — this command
prepares; the user commits.
