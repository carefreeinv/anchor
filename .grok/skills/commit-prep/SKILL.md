---
name: commit-prep
description: Pre-commit pass — run & fix tests, update release notes, blog significant changes
---

# /commit-prep — pre-commit pass

When the user types `/commit-prep`, **prepare** the working tree for a commit. Work
the three gates in order; don't move on while an earlier gate is red. `$ARGUMENTS`,
if present, hints at what the pending commit is about — use it to focus release
notes and the blog decision.

**Project-agnostic.** Assume no specific language, test runner, changelog format, or
docs stack. Discover what *this* repo does and follow its conventions over the
defaults below. When a gate doesn't apply, skip it with a one-line note rather than
inventing structure the project never asked for.

**Scope:** prep only. **Do not** `git commit`, push, or merge here.

## Gate 1 — tests: run and fix

1. From the worktree/project root, run **this project's** checks:
   - Prefer what CI runs (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`,
     `.circleci/`) — CI is the authority on what "green" means.
   - Else discover: task-runner target (`make test`, `just test`, `npm test`,
     `composer test`, `rake`), then the language default (`pytest`, `go test ./...`,
     `cargo test`, `phpunit`, `rspec`), then configured linters/type-checkers
     (`ruff`, `eslint`, `mypy`, `tsc`, `clippy`).
   - Skip what doesn't exist and note it in one line. Do not scaffold a test suite
     or invent a build step the project lacks.
   - Docs-site build **only** if the project has one and docs sources changed.
2. Fix failures and re-run. After **two** failed attempts on the same failure, stop
   and surface it — don't thrash.
3. Never weaken, skip, or delete a test to go green. If a test looks wrong, say so
   and let the user decide.

## Gate 2 — release notes

1. Review `git status` / `git diff` (and `git diff --cached` if staged).
2. Update the project's changelog **in its existing form** — `CHANGELOG.md`,
   `CHANGES.md`, `NEWS`, `docs/changelog.md`, or a `changelog.d/` fragment dir. If
   the project generates release notes from Conventional Commits or PR labels, the
   entry belongs in the commit message — say so rather than hand-editing a generated
   file. Keep a Changelog layout → bullets under `## [Unreleased]`, using
   `### Added` / `### Changed` / `### Fixed` when present.
3. If no changelog and no other convention exists, create `CHANGELOG.md` with a
   minimal `[Unreleased]` section.
4. Imperative mood; name the file/flag/command a user would touch. Skip internal-only
   churn. **Shipped** user-visible changes only — never `.plans/` backlog contents.

## Gate 3 — blog post (only when warranted)

Write a short Markdown announcement **only if** the commit introduces or
significantly updates/fixes a user-facing capability (new tool/command, new platform
or integration, breaking change, headline fix). Otherwise give a one-line reason why
no post is needed.

- Prefer an existing blog dir (`docs/blog/`, `blog/`, `website/blog/`, Hugo
  `content/posts/`, Jekyll `_posts/`) and match its conventions.
- No blog and no docs site → default `docs/blog/`, creating it if missing. No
  static-site generator required; plain Markdown is enough.
- Filename default `YYYY-MM-DD-<slug>.md`. Front matter only when neighboring posts
  use it. Ground every claim in the shipped diff; mark anything unverified
  `(unverified)`.

## If you hit a usage limit mid-prep

Test-fix loops burn capacity. On a session/weekly cap or quota, follow capacity
routing (`.anchor/capacity-routing.md`): checkpoint what's green, then reroute to
the next model in priority order **that clears the task's fitness floor**, or wait
for reset. Never finish a gate by weakening it — gates stay red until they pass.

## Finish

Summarize checks run/skipped, changelog path + entries, blog path (or why none), and
whether gates are **green** or **red**. Stop — do not commit.
