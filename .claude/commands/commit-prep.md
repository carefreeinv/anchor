---
description: Pre-commit pass — run & fix tests, update release notes, blog significant changes
---

Prepare the working tree for a commit. Work the three gates in order; don't move on
while an earlier gate is red. `$ARGUMENTS`, if present, is a hint about what the
pending commit is about — use it to focus the release notes and blog decision.

This command is **project-agnostic**. It assumes no specific language, test runner,
changelog format, or docs stack. Every gate below says *discover what this repo
actually does* — follow the repo's existing conventions over the defaults here, and
when a gate doesn't apply to this project, skip it with a one-line note rather than
inventing structure the project never asked for.

**Scope:** this command **only prepares** (tests, CHANGELOG, blog-if-warranted)
and reports gate results. It does **not** `git commit`, push, or merge.

## Gate 1 — tests: run and fix

1. From the repo root (or the agent's worktree root), run **this project's**
   automated checks — prefer what CI runs:
   - If CI config exists (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`,
     `.circleci/`, etc.), run the same commands those jobs run, or the local
     equivalent. CI is the authority on what "green" means here.
   - Else discover from the repo: a task runner target (`make test`, `just test`,
     `npm test`, `composer test`, `rake`), then the language's default runner when
     tests exist (`pytest`, `go test ./...`, `cargo test`, `phpunit`, `rspec`), then
     configured linters/type-checkers (`ruff`, `eslint`, `mypy`, `tsc`, `clippy`).
   - **Skip** checks that don't apply — missing tool, no test suite, no CI — and
     note in one line what you skipped and why. Do not scaffold a test suite, add a
     runner, or invent a build step that this project does not have.
   - If a docs site **is** present and has a documented build (`docs/package.json`
     with a build script and installed deps, MkDocs, Sphinx, Hugo, …), run that
     build **only when docs sources changed**. Otherwise skip with a note.
2. Fix failures and re-run. Stop rule: after **two** failed fix attempts on the same
   failure, stop and surface it — don't thrash.
3. Never weaken, skip, or delete a test just to go green; if a test seems wrong, say
   so and let the user decide.

## Gate 2 — release notes

1. Review what the commit will contain: `git status` and `git diff` (plus
   `git diff --cached` if things are staged).
2. Update the project's changelog if it has one:
   - Prefer the existing file and its existing layout — `CHANGELOG.md`, `CHANGES.md`,
     `NEWS`, `docs/changelog.md`, a `changelog.d/` fragment directory (Towncrier
     etc.), or release notes generated from commit messages. **Match what's there.**
     If the project generates its changelog from Conventional Commits or PR labels,
     the entry belongs in the commit message — say so instead of hand-editing a
     generated file.
   - For a Keep a Changelog layout, add lines under `## [Unreleased]` (or the file's
     equivalent pending section) in `### Added` / `### Changed` / `### Fixed` when
     those subsections exist; otherwise plain bullets under Unreleased.
   - If **no** changelog exists and the project shows no other release-note
     convention, create `CHANGELOG.md` with a minimal `[Unreleased]` section and add
     the entries there — operators need one place to look.
   - Imperative mood; mention the file/flag/command a user would touch. Skip
     internal-only churn (refactors, test-only changes).
3. **Hard rule — docs describe current state, not plans:** CHANGELOG, blog, and docs
   cover **shipped** code only. Never restate `.plans/` contents (drafts, backlog,
   unfinished acceptance criteria) as release notes or product docs. When plan work
   ships, document the code and its public contract — not the plan file.

## Gate 3 — blog post (only when warranted)

Write a short **Markdown** announcement **only if** the commit introduces or
significantly updates/fixes a user-facing capability: a new tool/command, a new
platform or integration, a breaking behavior change, or a headline fix. For routine
changes, state in one line why no post is needed and stop here.

### Where posts live (no docs app required)

1. Prefer an existing blog/news directory if one is obvious (`docs/blog/`, `blog/`,
   `website/blog/`, Hugo `content/posts/`, Jekyll `_posts/`, …) and follow its
   conventions.
2. If the project has **no** blog and no docs site, the default is `docs/blog/` —
   create it (`mkdir -p docs/blog`) and write a plain `.md` file. Do **not** require
   a static-site generator, `npm install`, tag registries, or any scaffold. A folder
   of Markdown posts is enough; the project can wire a docs app later or never.
3. If a project clearly has no place for announcements and no audience for them,
   skipping with a one-line reason is a valid outcome.

### Post shape

- Filename: follow the directory's existing pattern; default `YYYY-MM-DD-<slug>.md`
  (today's date, kebab-case slug).
- Body: short title (`# …`), lead paragraph, then 3–8 short paragraphs — what
  changed, why an operator cares, how to use it (real commands from the **shipped**
  diff).
- Front matter: match neighboring posts exactly when they have it (e.g. Docusaurus
  `authors` / `<!-- truncate -->`, Jekyll `layout`) — and **only** then. For a newly
  created bare `docs/blog/`, keep it minimal or omit it.
- Cross-check every claim against the diff — do not promise anything the code
  doesn't do, and do not source "coming soon" from `.plans/`. Mark anything
  unverified `(unverified)`.

## If you hit a usage limit mid-prep

Test-fix loops are where prep burns the most capacity. If a session/weekly cap or
quota lands partway through, follow capacity routing (`.anchor/capacity-routing.md`,
or `anchor/capacity-routing.md` in the Anchor repo): checkpoint what's green so far,
then reroute or wait — and **never** finish a gate by weakening it. A partially
prepped tree reported honestly is fine; gates are red until they actually pass.

## Finish

Summarize: which checks ran (and which were skipped and why), changelog path +
entries (or why the project's convention put them elsewhere), blog post path (or
the one-line reason none was written), and whether gates are **green** or **red**.

**Do not** run `git commit`, push, or merge as part of this command. Report gate
status and stop.
