---
description: Pre-commit pass — run & fix tests, update release notes, blog significant changes
---

Prepare the working tree for a commit. Work the three gates in order; don't move on
while an earlier gate is red. `$ARGUMENTS`, if present, is a hint about what the
pending commit is about — use it to focus the release notes and blog decision.

This command is **project-agnostic**: it does not assume Docusaurus, npm docs, or
Anchor-only tooling. Discover what *this* repo actually uses.

**Scope:** this command **only prepares** (tests, CHANGELOG, blog-if-warranted)
and reports gate results. It does **not** `git commit`, push, or merge.

## Gate 1 — tests: run and fix

1. From the repo root (or the agent’s worktree root), run **this project’s**
   automated checks — prefer what CI runs:
   - If `.github/workflows/*.yml` (or similar) exists, run the same commands those
     jobs run (or the local equivalent).
   - Else discover from the repo: e.g. `pytest` / `python -m pytest` when tests
     exist; `ruff` / `eslint` / `cargo test` / `go test` / `npm test` when
     configured; `make test` / `just test` when present.
   - **Skip** checks that don’t apply (missing tool, no test suite, no CI) and
     note what you skipped in one line — do not invent a Docusaurus/`docs` npm
     build for a project that has no docs app.
   - If a docs site **is** present and has a documented build (e.g. `docs/package.json`
     with a build script and `node_modules`, MkDocs, Sphinx, Hugo, etc.), run that
     build **only when docs sources changed**. Otherwise skip with a note.
2. Fix failures and re-run. Anchor stop rule: after **two** failed fix attempts on
   the same failure, stop and surface it — don't thrash.
3. Never weaken, skip, or delete a test just to go green; if a test seems wrong,
   say so and let the user decide.

## Gate 2 — release notes

1. Review what the commit will contain: `git status` and `git diff` (plus
   `git diff --cached` if things are staged).
2. Update the project’s changelog if it has one:
   - Prefer existing `CHANGELOG.md` / `CHANGELOG` / `CHANGES.md` / Keep a Changelog
     layout. Add lines under `## [Unreleased]` (or the file’s equivalent “pending”
     section) in `### Added` / `### Changed` / `### Fixed` when those subsections
     exist; otherwise plain bullets under Unreleased.
   - If **no** changelog file exists, create `CHANGELOG.md` with a minimal
     `[Unreleased]` section and add the entries there (operators need a place to
     look).
   - Imperative mood; mention the file/flag/command a user would touch. Skip
     internal-only churn (refactors, test-only changes).
3. **Hard rule — docs describe current state, not plans:** CHANGELOG, blog, and
   docs cover **shipped** code only. Never restate `.plans/` contents (drafts,
   backlog, unfinished acceptance) as release notes or product docs. When plan
   work ships, document the code — not the plan file.

## Gate 3 — blog post (only when warranted)

Write a short **Markdown** announcement **only if** the commit introduces or
significantly updates/fixes a user-facing capability: a new tool/command, a new
platform or hardware tier, a breaking behavior change, or a headline fix. For
routine changes, state in one line why no post is needed and stop here.

### Where posts live (no docs app required)

1. Prefer an existing project blog directory if one is obvious (`docs/blog/`,
   `blog/`, `website/blog/`, Hugo `content/posts/`, etc.).
2. **Default for Anchor-style and unknown layouts:** `docs/blog/`.
3. If that directory **does not exist**, **create it** (`mkdir -p docs/blog`) and
   write the post there as a plain `.md` file. Do **not** require Docusaurus,
   `npm install`, `tags.yml`, or any static-site scaffold. A folder of Markdown
   posts is enough; the project can wire a docs app later or never.

### Post shape

- Filename: `YYYY-MM-DD-<slug>.md` (today’s date, kebab-case slug).
- Body: short title (`# …`), lead paragraph, then 3–8 short paragraphs — what
  changed, why an operator cares, how to use it (real commands from the
  **shipped** diff).
- Optional YAML front matter when useful (`title`, `date`, `tags` as a simple
  list). Use project conventions if present (e.g. Docusaurus `authors` /
  `<!-- truncate -->` **only** when that project’s existing posts already use
  them). For a newly created bare `docs/blog/`, keep front matter minimal or omit
  it — plain Markdown is fine.
- Cross-check every claim against the diff — do not promise anything the code
  doesn’t do, and do not source “coming soon” from `.plans/`. Mark anything
  unverified `(unverified)`.

## Finish

Summarize: which tests ran (and which were skipped and why), CHANGELOG path +
entries, blog post path (or the one-line reason none was written), and whether
gates are **green** or **red**.

**Do not** run `git commit`, push, or merge as part of this command. Report gate
status and stop.
