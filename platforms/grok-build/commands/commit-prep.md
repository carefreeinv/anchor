# /commit-prep — pre-commit pass (Grok Build)

<!-- (unverified) Grok Build's file-based custom-command convention, if any, isn't
     documented publicly as of this writing. If your Grok Build environment loads
     custom commands from a folder, drop this file there under the name `commit-prep`.
     Otherwise paste the body below into custom instructions. This file exists so
     `/commit-prep` means the same thing everywhere Anchor is installed. -->

When the user types `/commit-prep`, **prepare** the working tree for a commit.
Work the three gates in order; don't move on while an earlier gate is red.
Project-agnostic — do not assume Docusaurus or Anchor-only tooling.

**Scope:** prep only (tests, CHANGELOG, blog-if-warranted). **Do not** `git commit`,
push, or merge here.

1. **Tests — run and fix.** From the worktree/project root, run **this project’s**
   checks: prefer CI workflows; else discover (`pytest`, linters, `npm test`,
   `make test`, etc.). Skip what doesn’t exist and note it. Docs-site build only
   if the project has one and docs changed. Fix failures; two failed attempts on
   the same failure → stop. Never weaken or delete a test to go green.
2. **Release notes.** Review `git status` / `git diff`. Update existing
   `CHANGELOG.md` / `CHANGELOG` / Keep a Changelog `## [Unreleased]` (or create
   `CHANGELOG.md` with Unreleased if none). User-visible **shipped** changes
   only — never `.plans/` backlog.
3. **Blog post — only when warranted.** If the commit introduces or significantly
   updates/fixes a user-facing capability, write Markdown under `docs/blog/`
   (create the folder if missing). No docs-app scaffold required. Ground claims
   in the shipped diff. Otherwise one line why no post is needed.

**Finish:** summarize tests / CHANGELOG / blog and whether gates are **green** or
**red**. Stop — do not commit.
