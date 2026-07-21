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
the empty-queue **dev → main** gate.

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
| `/review` | Plan mode if queue non-empty; else promotion mode if `dev` ahead of `main` |
| `/review <slug>` | Session for that plan only (must be under `review-needed/`) |
| `/review --list` | Inventory queue + ahead-of-mainline advisory; no merge |
| `/review --skip-ai` | Evidence + survey only (still one decision) |
| `/review --no-launch` | Skip auto-launch of local systems |
| `/review --promote` | Force promotion review (refuses if not ahead) |
| `/review --no-promote` | Empty queue stops without offering promotion |
| `/review --push` | After successful **local** merge, confirm push to `origin` |

**One decision per invocation** (one plan **or** one promotion). After you
finish, re-run `/review` for the next item — the skill never drains the queue
or chains plan Approve into promotion in one go.

## Session pipeline (plan)

```text
select → checkout (if safe) → evidence + optional launch
       → AI code review (fresh context)
       → present package
       → survey → follow-ups
       → merge feature → integration (on Approve)
       → lane move to completed/ (after merge success or nothing to merge)
```

1. **Select** — bare pick uses Priority → Value → oldest mtime → filename.
2. **Checkout** — `feature/<slug>` only when the tree is clean (or after confirm);
   dirty trees get a worktree offer, not a silent switch.
3. **Launch** — low-risk local servers only; confirm Docker/migrations/deploy.
4. **AI critic** — fresh subagent/context; format from `templates/review.md`
   (ACCEPT | REVISE | ESCALATE). **Advisory only.**
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

Scaffold always creates the empty `.plans/` tree (including `review-needed/`).
Process contract also lives in `.plans/README.md` once scaffolded.

## Related

- [**`/work`**](/skills/work) — agents finish to `review-needed/`; **never** merge
- [`pending_merges.py`](/tooling/scripts) — advisory table of unmerged branches
- [Doctrine — tracked plans](/doctrine)
