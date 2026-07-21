---
sidebar_position: 3.5
sidebar_label: /review · human sign-off
---

# `/review`

**Best used:** when one or more plans sit under **`.plans/review-needed/`** and a
human should sign off (or send work back). See [Skills overview](/skills/overview).

Human sign-off for finished plan work: pick **exactly one** plan from
`review-needed/`, check out its feature branch when safe, optionally launch local
systems to inspect, run a **fresh-context AI code review**, then collect a
**survey** decision with follow-ups before any lane move.

This is **not** free-form “code review any PR.” Ad-hoc diffs belong to the
platform’s code-review tools. `/review`’s home is the **`review-needed/`** lane.

## Why use it

| Without `/review` | With `/review` |
|-------------------|----------------|
| Human must remember branch name, diff, and Done when | Skill checks out `feature/<slug>`, packs evidence, runs AI critic |
| Easy to rubber-stamp or give vague “fix it” feedback | Survey + follow-ups force Approve override or actionable Needs Work notes |
| Unclear where rejected work should go | Needs Work returns to **`bugs/` or `features/`** by plan shape |

## Usage

| Invocation | Behavior |
|------------|----------|
| `/review` | Pick **one** highest-priority plan in `review-needed/`; full session |
| `/review <slug>` | Session for that plan only (must be under `review-needed/`) |
| `/review --list` | Inventory queue; no checkout, AI, launch, or survey |
| `/review --skip-ai` | Evidence + survey only (still one plan) |
| `/review --no-launch` | Skip auto-launch of local systems |

**One plan per invocation.** After you finish, re-run `/review` (or name a slug)
for the next item — the skill never drains the queue in one go.

## Session pipeline

```text
select → checkout (if safe) → evidence + optional launch
       → AI code review (fresh context)
       → present package
       → survey → follow-ups → lane move
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
7. **Move** — see table below.

## Survey → lanes

| Choice | Lane move |
|--------|-----------|
| **Approve** | `review-needed/` → `completed/` (optional `YYYY-MM-DD-` prefix) |
| **Needs Work** | → **`bugs/` or `features/`** (same basename; inferred like `/draft --promote`) — **not** `in-progress/` |
| **Skip** | Stay in `review-needed/` |
| **Defer** | → `blocked/` when the human confirms a real external blocker |

Needs Work lane inference reuses [**`/draft --promote`**](/skills/draft) rules
(bug vs feature signals; ask once if ambiguous; human override wins).

Agents must **not** move `review-needed/` → `completed/` outside a
human-confirmed Approve in this skill — that rule is the point of the lane.
See [**`/work`**](/skills/work) and [`.plans/` doctrine](/doctrine).

## Install (platform wiring)

| Platform | Install |
|----------|---------|
| **Claude Code** | Scaffold installs `.claude/commands/review.md` |
| **Grok Build** | Scaffold installs `.grok/skills/review/SKILL.md` |

Scaffold always creates the empty `.plans/` tree (including `review-needed/`).
Process contract also lives in `.plans/README.md` once scaffolded.
