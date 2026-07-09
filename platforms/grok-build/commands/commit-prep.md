# /commit-prep — pre-commit pass (Grok Build)

<!-- (unverified) Grok Build's file-based custom-command convention, if any, isn't
     documented publicly as of this writing. If your Grok Build environment loads
     custom commands from a folder, drop this file there under the name `commit-prep`.
     Otherwise paste the body below into custom instructions. This file exists so
     `/commit-prep` means the same thing everywhere Anchor is installed. -->

When the user types `/commit-prep`, prepare the working tree for a commit. Work the
three gates in order; don't move on while an earlier gate is red.

1. **Tests — run and fix.** Run what CI runs, from the repo root: `ruff check .`,
   `pytest -q`, `python3 scripts/check_docs_sync.py`; `shellcheck config.sh bin/anchor`
   if shell files changed; `cd docs && npm run build` if `docs/` changed and
   `node_modules` exists. Fix failures and re-run — after two failed fix attempts on
   the same failure, stop and surface it. Never weaken or delete a test to go green.
2. **Release notes.** Review `git status` / `git diff`, then add one line per
   user-visible change to the `## [Unreleased]` section of `CHANGELOG.md`
   (`### Added` / `### Changed` / `### Fixed`). Skip internal-only churn.
   **Hard rule — docs describe current state, not plans:** never changelog/blog/docs
   the **contents** of `.plans/` (any project). Cover **shipped** code only; when
   plan work ships, document the code — not the plan file.
3. **Blog post — only when warranted.** If the commit introduces or significantly
   updates/fixes a user-facing capability (new tool/command, platform, hardware tier,
   breaking change, headline fix), write `docs/blog/YYYY-MM-DD-<slug>.md` with front
   matter (`title`, `authors: [carefree]`, `tags` from `docs/blog/tags.yml`), a lead
   paragraph, `<!-- truncate -->`, then 3–8 short paragraphs grounded in the actual
   **shipped** diff — never “coming soon” from `.plans/`. Otherwise say in one line
   why no post is needed.

Finish by summarizing test status, CHANGELOG entries, and the blog post path (or why
none). Do NOT run `git commit` — the user commits.
