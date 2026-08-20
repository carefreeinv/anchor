# CLAUDE.md — working in the Anchor repo

This repo's purpose: help less-powerful models behave like Mythos-class models via structured prompting, orchestration, and verification. Read `anchor/ANCHOR.md` first — and practice it while working here.

- Doctrine + templates: `anchor/`
- Per-platform instructions: `platforms/` (the reusable CLAUDE.md for OTHER repos is `platforms/claude-code/CLAUDE.md`)
- Hardware tiers: `hardware/{personal-devices,h100,space-1-vera-rubin}/`
- Fleet tooling: `scripts/` (registry: `scripts/endpoints.yaml`), MCP servers: `mcp/`
- Docs site: `docs/` (Docusaurus; `npm install && npm start`)
- Work plans: `.plans/` (dotdir; **fully gitignored in this repo only** — projects track `.plans/` and only ignore `*.local.md`). Draft with **`/draft`** → `drafts/`; execute with **`/work`**. Scaffold source: `anchor/scaffold/plans/`

Conventions: Python 3.10+, OpenAI-compatible endpoints only, model quirks belong in `anchor_client.py` quirks handling (never in callers). Docs pages mirror repo files — update both when changing doctrine.

## Hard rule: `/commit-prep` before any commit outside `.plans/`

**All agents, every project using Git:** run **`/commit-prep`** (tests, CHANGELOG,
blog-if-warranted) **before any commit that touches a path outside `.plans/`, and
before any merge commit**. `/commit-prep` is **prep only** — it does not commit.
After a **green** prep, if plan work is complete, stage + commit on the **feature
branch** (see `/work`); never on main/dev — **except** the plans-only lane-move
commit below, which `/review` makes on the branch it just integrated into, because
that is where the lane move exists.

**Plans-only commits take the light path.** A commit whose paths are *entirely*
under `.plans/` — a lane move, review notes, a `## Handoff` line — states what
moved and why, then commits. No CHANGELOG, no blog, no test run: a lane move
cannot break a test, and gating it behind one is what trains operators to skip the
skill. Skills that rearrange `.plans/` (**`/review`**, **`/work`**, **`/draft --promote`**)
**commit that themselves** rather than leaving it staged for the next unrelated
commit to swallow.

**A merge commit is gated before it exists.** A clean textual merge can still be
semantically broken, and the merged tree is state neither branch was prepped in:

```bash
git merge --no-ff --no-commit <branch>   # stage the merge, do not commit
# run /commit-prep against the merged working tree, then:
#   green → git add -A && git commit     # -A matters: prep EDITS the working tree
#                                        # (CHANGELOG, test fixes, a new blog file).
#                                        # A bare `git commit` commits only the index
#                                        # and silently drops prep's own output.
#   red   → git merge --abort || git reset --hard HEAD
#           `--abort` REFUSES when prep modified a file involved in the merge —
#           exactly what its fix-the-tests gate does. The reset is the fallback,
#           and it discards prep's edits along with the merge: say so.
```

A **fast-forward** merge creates no commit and cannot conflict — its content is
byte-identical to what was already prepped on the branch — so it needs no
additional prep. The plans-only commit that follows still takes the light path.

**Never merge on your own initiative** — a `/work` session may land a feature branch on **`dev` only**
when the operator answers its culmination question in-session *and* the
scoped-merge gate passes; unattended runs never ask and never merge, and `main` is
reached solely through `/review`'s promotion survey.
Optional push of that feature branch only. Do not skip prep for “small” changes outside `.plans/`.
See `.claude/commands/commit-prep.md` / Grok `commit-prep` / chat in `CHAT.md`.

## Hard rule: docs describe current state, not plans

**Framework-wide (all Anchor agents, every project):** documentation describes the
**project as it exists now** — shipped code, public contracts, operator-facing
behavior. **Never** write docs, CHANGELOG, blog, or release notes that restate the
**contents** of `.plans/` (drafts, ready backlog, in-progress plan bodies,
unfinished acceptance items) as product documentation or roadmap. When work from a
plan **ships**, document the code and public contract — not the plan file. See
`anchor/ANCHOR.md` and mythos-core rule 12.

| Allowed | Forbidden |
|---------|-----------|
| Document **shipped** behavior and public contracts | Cite, summarize, or preview plan files by slug or path as docs |
| Document the `.plans/` **workflow** when it is a shipped product feature | “Coming soon” sections sourced from plan backlog |
| Changelog/blog for **shipped** code/docs | Changelog/blog that tracks unfinished plans |

**This repository:** `.plans/` is fully gitignored private working backlog. Public
docs describe **released** doctrine and tooling only — never this tree’s contents
(especially `drafts/` and `*.local.md`).
