---
sidebar_position: 3.5
sidebar_label: /review · human sign-off
---

# `/review`

**Best used:** when plans sit under **`.plans/review-needed/`** and a human
should sign off (or send work back), or when the queue is empty and **`dev` is
ahead of `main`** and you want a promotion pass. See [Skills overview](/skills/overview).

Human sign-off with **integration**: pick **exactly one** plan from
`review-needed/`, check out its feature branch when safe, optionally launch local
systems, run a **fresh-context AI code review**, then collect a **survey**.
**Approve** merges `feature/<slug>` into the integration branch (`dev` /
`develop`) and archives the plan to `completed/`. When the queue is empty and
integration is ahead of mainline, the same skill offers a **promotion review**
whose **Promote** merges `dev` into `main`.

This is **not** free-form “code review any PR.” Ad-hoc diffs belong to the
platform’s code-review tools. `/review` owns **`review-needed/`** sign-off and
the empty-queue **dev → main** gate. CLI: **`anchor review`** picks the top
`review-needed/` plan and runs the critic (headless too). `anchor review <slug>`
names one. `--list` lists. `--no-delegate` skips. Empty queue with integration
ahead of mainline: exit 2 names **`anchor review --promote`** (operator required;
never auto-promote). Probe once this session (`anchor review --help`);
last-known-good CLI wins over re-implementing the critic in chat. Survey and
merge stay in the skill.

| Intent | argv |
|--------|------|
| List queue | `anchor review --list` |
| Pick + critic | `anchor review` |
| Named critic | `anchor review <slug>` (`--no-delegate` skips) |
| Empty queue + ahead | `anchor review --promote` (operator required; never auto) |

## Why use it

| Without `/review` | With `/review` |
|-------------------|----------------|
| Human must remember branch name, diff, and Done when | Skill checks out `feature/<slug>`, packs evidence, runs AI critic |
| Easy to rubber-stamp or give vague “fix it” feedback | Survey + follow-ups force Approve override or actionable Needs Work notes |
| Unclear where rejected work should go | Needs Work returns to **`bugs/` or `features/`** by plan shape |
| Green feature branches pile up unmerged | **Approve merges feature → `dev`**, then archives the plan |
| `dev` drifts from `main` with no ritual | Empty queue + **Promote** merges `dev` → `main` after a dedicated survey |

## Usage

| Invocation | Behavior |
|------------|----------|
| `/review` | On `main`/`dev` with both a queue **and** `dev` ahead of `main`: asks which to review. Else **batch mode if 2+ eligible plans are queued** (the default), plan mode for a single plan; else promotion mode if `dev` ahead of `main` |
| `/review <slug>` | Session for that plan only (must be under `review-needed/`) |
| `/review --list` | Inventory queue + ahead-of-mainline advisory; no merge |
| `/review --skip-ai` | Evidence + survey only (still one decision) |
| `/review --no-launch` | Skip auto-launch of local systems |
| `/review --promote` | Force promotion review (refuses if not ahead) |
| `/review --no-promote` | Empty queue stops without offering promotion |
| `/review --push` | After successful **local** merge, confirm push to `origin` |
| `/review --batch [N]` | Batch mode with an explicit cap: review up to `N` (default 3) top-priority plans in one invocation, each with its own full pipeline and required survey. Bare `/review` already batches; this only sets `N` |
| `/review --no-batch` (alias `--single`) | Force single-item mode for this run — one plan **or** one promotion. Overrides the project and machine settings |

In single-item mode (a named slug, `--promote`, `--skip-ai`, `--no-batch`, or
fewer than 2 eligible plans) it is **one decision per invocation** — one plan
**or** one promotion. After you finish a single-item session, re-run `/review`
for the next item; the skill never chains plan Approve into promotion in one go.
With 2+ eligible plans queued, bare `/review` opens a batch instead (below).

### Batch mode (default for a queue of 2+ plans)

Batch mode is on by default for bare `/review` — currently a trial, so the
default may change. It is for working through a queue faster **without**
weakening the per-plan gate: each of up to `N` plans (default 3, capped, top
Priority/Value first) still gets its own fresh-context AI critic and its own
required survey — no shared verdict, no inferred Approve from a pattern in
earlier items. Before the loop starts, `/review` shows the whole batch
(what's in, what got excluded and why) so nothing is a surprise mid-session.

A candidate is excluded from the batch (falls back to single-item review)
when it: carries a `## Handoff` **hold** note, has a large diff (>8 files or
±300 lines net), or shares a touched path with another candidate — an exact
match, or one plan naming a directory containing the other's file (the same
overlap rule `/work --batch`'s `batch_dispatch.py` applies for parallel
execution, restated in prose here so this check stands on its own) —
batching two plans that would conflict at merge time, or rushing a human
through a big diff back-to-back with others, defeats the point of a careful
review. Fewer than 2 eligible plans after filtering means nothing to batch.

An explicit `--batch` refuses to combine with `--skip-ai`, a slug, or
`--promote`; without the flag, those simply run single-item. (Skipping the
fresh-context critic across several plans at once is exactly the rubber-stamp
risk this mode is designed to avoid.) Batch mode never applies to promotion
review, which stays a single, deliberate decision.

**Turning it off.** Pass `--no-batch` (or `--single`) for one run. To change the
default, set it per project with `anchor --set-review-batch off` (stored as
`**Review batch:** off` in `.anchor/conventions.md`) or for your machine with
`./config.sh --review-batch off` (`REVIEW_BATCH` in `~/.config/anchor/defaults`).
The order is: flag, then project, then machine, then the built-in default (on).
`anchor --show-review-batch` prints the effective setting and where it came from,
and every batch overview repeats how to opt out.

## Session pipeline (plan)

```text
select → checkout (if safe) → evidence + optional launch
       → AI code review (fresh context)
       → present package
       → survey → follow-ups
       → merge feature → integration (on Approve)
       → lane move to completed/ (after merge success or nothing to merge)
```

Human-assisted only. **Never** move to `completed/` or open a PR on critic **REVISE**. The autonomous critic loop (work → review → review → PR) lives in [`/work`](/skills/work), not here.

1. **Select** — run from `main`/`dev` while a review queue coexists with an
   unpromoted `dev`, the skill first asks whether to review `dev` for promotion
   or pick a feature branch from the queue. Otherwise the bare pick uses
   Priority → Value → oldest mtime → filename.
2. **Checkout** — `feature/<slug>` only when the tree is clean (or after confirm);
   dirty trees get a worktree offer, not a silent switch.
3. **Launch** — low-risk local servers only; confirm Docker/migrations/deploy.
4. **AI critic** — fresh subagent/context; format from `templates/review.md`
   (ACCEPT | REVISE | ESCALATE). **Advisory** for merges and human lane moves.
   Autonomous `/work` treats **ACCEPT** as a hard gate for archive-on-branch + PR.
5. **Survey** — Approve | Needs Work | Skip | optional Defer.
6. **Follow-ups** — e.g. override if AI was REVISE and human Approves; actionable
   bullets required for Needs Work.
7. **Merge + move** — see tables below.

## Survey → merge + lanes (plan)

| Choice | Git | Lane move |
|--------|-----|-----------|
| **Approve** | Merge `feature/<slug>` → `dev` (create `dev` if needed; FF preferred). Skip merge only if no branch / already integrated. Conflict → **abort**, stay in `review-needed/`. | → `completed/` only after merge success or nothing to merge |
| **Needs Work** | No merge | → **`bugs/` or `features/`** (inferred like `/draft --promote`) — **not** `in-progress/` |
| **Skip** | No merge | Stay in `review-needed/` |
| **Defer** | No merge | → `blocked/` when the human confirms a real external blocker |

Needs Work lane inference reuses [**`/draft --promote`**](/skills/draft) rules
(bug vs feature signals; ask once if ambiguous; human override wins).

**Guards:** clean tree required; never force-push; push to `origin` only with
confirm or `--push` after local success. Agents must **not** move
`review-needed/` → `completed/` outside a human-confirmed Approve in this skill.

## Promotion review (empty queue)

When `review-needed/` is empty and integration is ahead of mainline (or the
human runs `/review --promote`):

1. Evidence: `git log` / shortstat for `mainline..integration` (+ optional AI).
2. Survey: **Promote to main** | **Skip** | **Defer**.
3. Promote → merge integration → mainline (same conflict / push rules). No plan
   lane moves.

## Install (platform wiring)

| Platform | Install |
|----------|---------|
| **Claude Code** | Scaffold installs `.claude/commands/review.md` |
| **Grok Build** | Scaffold installs `.grok/skills/review/SKILL.md` |

## What `/review` commits

Every `/review` outcome that changes a tracked file commits it — it does not leave
the change staged for an unrelated commit to swallow. Which gate applies depends on
what the commit contains, per the [`/commit-prep` hard rule](/platforms/claude-code):

| `/review` does | Gate |
|---|---|
| Fast-forward merge into integration | none — creates no commit; the content was already prepped on the branch, and a fast-forward cannot conflict |
| `--no-ff` merge (feature → integration, or integration → mainline) | **full `/commit-prep`**, run against the *staged* merge before it becomes a commit: `git merge --no-ff --no-commit`, prep, then `git add -A && git commit` if green (prep edits the working tree; a bare commit drops its output) or `git merge --abort \|\| git reset --hard HEAD` if red |
| Lane move + review notes (Approve / Needs Work / Defer) | **light path** — state what moved and why, then commit. No CHANGELOG, no blog, no test run; a lane move cannot break a test |

A project that leaves `.plans/` untracked (as the Anchor repo itself does) has
nothing to commit for the third row, and `/review` says so rather than pretending.


Scaffold always creates the empty `.plans/` tree (including `review-needed/`).
Process contract also lives in `.plans/README.md` once scaffolded.

## Related

- [**`/work`**](/skills/work) — human-assisted default finish is `review-needed/`; interactive
  sessions may also land `feature/<slug>` on **`dev` only** when the operator
  answers the culmination question and the scoped-merge gate passes. Unattended
  runs never merge; they open a PR after critic **ACCEPT**. `/review` remains the only route to `main` and never auto-opens a PR.
- [`pending_merges.py`](/tooling/scripts) — advisory table of unmerged branches, including completed-on-branch awaiting merge
- [How work reaches `dev`](/tooling/how-work-reaches-dev) — local merge routes plus the autonomous PR route
- [Doctrine — tracked plans](/doctrine)
