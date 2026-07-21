---
name: review
description: >
  Human sign-off for .plans/review-needed/ work: check out the feature branch,
  run a fresh-context AI critic pass, present evidence, then a survey
  (Approve / Needs Work / Skip) with follow-ups before lane moves. Use when the
  user runs /review, asks to sign off review-needed plans, or human-approve
  finished plan work. Not free-form ad-hoc PR review outside that lane.
argument-hint: "[slug|--list|--skip-ai|--no-launch]"
disable-model-invocation: false
metadata:
  short-description: "Sign off one review-needed plan (AI + survey)"
---

# /review — human sign-off for `review-needed/` work

Run a **single** human review session for one plan under **`.plans/review-needed/`**:
check out its feature branch when safe, optionally launch inspection systems,
run a **fresh-context AI code review**, present the package, then collect a
**survey** decision (Approve / Needs Work / Skip / optional Defer) with
follow-ups before any lane move.

This skill **embeds** an AI critic pass; it is not a separate “code review any
diff” product. For ad-hoc uncommitted/PR review outside `review-needed/`, use
the platform’s code-review tools when the queue is empty and no plan slug was
given.

`$ARGUMENTS` is everything after `/review`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/review` | Pick **one** plan from `review-needed/`; full session (AI + survey) |
| `/review <slug>` | Same for that plan if under `review-needed/`; else refuse |
| `/review --list` | Inventory only — no checkout, AI, launch, or survey |
| `/review --skip-ai` | Evidence + survey only (still one plan) |
| `/review --no-launch` | Skip auto-launch of local systems |

Flags may combine with a slug: `/review --no-launch my-slug`.

## Hard rules

1. **One plan per invocation.** Never batch; never auto-start the next.
   Footer may note remaining queue count only.
2. **Pipeline order** (fixed):

   ```text
   select → checkout (if safe) → evidence + optional launch
          → AI code review (fresh context)
          → present package
          → survey → follow-ups → lane move
   ```

   Do **not** open the survey before the AI pass finishes (or a clear
   “AI pass skipped/failed: …” message).
3. **AI is advisory.** Never auto-approve/reject. Survey is authoritative.
4. **`review-needed/` → `completed/`** only after survey **Approve** (+
   override follow-up when AI was REVISE/ESCALATE). Re-prompt on ambiguous
   free text.
5. **Needs Work** → **`bugs/` or `features/`** (inferred), **never**
   `in-progress/`. Actionable notes required first.
6. Never auto-merge, push, force-push, or delete branches.
7. Preserve basenames (including `.local.md`) on every move.

## 1. Resolve project

Find a root with `.plans/` (CWD, then git root). Print the absolute path.
If missing: explain and stop.

## 2. Select one plan

**`--list`:** list each `review-needed/*.{md,local.md}` (skip `.gitkeep`): path,
Priority, Value, Goal one-liner, whether `feature/<slug>` exists. Stop.

**Named slug:** resolve under `review-needed/` only. Other lane → refuse with
the right command pointer.

**Bare `/review`:** pick **one** by Priority (P1→P3, default P2) → Value
(high→low, default medium) → oldest mtime → filename. State why it won.
Other queued plans: **one line** only.

**Empty queue:** report empty; optional `python scripts/pending_merges.py`
advisory one-liner. Clarify this `/review` is for plan sign-off. Stop.

## 3. Load plan

Read fully. Restate Goal, Done when, Preferred models, Progress ≤15 lines.
Slug = filename without `.md` / `.local.md`.

## 4. Branch checkout (safe only)

Branch name: `feature/<slug>` (same rules as
`scripts/worktree_for_agent.feature_branch_name`).

| Situation | Action |
|-----------|--------|
| Already on branch | Leave it; report status |
| Clean tree + local branch | `git checkout feature/<slug>` |
| Clean tree + remote only | Tracking checkout from `origin/feature/<slug>` |
| Dirty tree | **Do not** switch; offer `python scripts/worktree_for_agent.py ensure --project <root> --agent-id review --slug <slug>` or stop |
| Missing branch | Continue with plan + available refs; never invent a branch |

Report `git status` and shortstat vs integration (`dev` → `develop` → `main`
→ `master`).

## 5. Evidence pack

- Diff summary vs integration (files, shortstat, themes)
- Done when checklist for human judgment (do not auto-tick)
- PR URL if `gh pr view` works
- Verification notes from plan Progress if present

## 6. Launch (unless `--no-launch`)

Scoped to this plan’s touches:

- **Auto-launch OK:** docs `npm start`, clear local `dev` without destructive
  pre-steps. Background preferred; report URL + stop instructions.
- **Confirm first / print-only:** Docker Compose, migrations, privileged
  ports, remote deploys, `sudo`, destructive resets.
- Nothing useful → one line “no launch.”

Survey waits until AI pack is ready (or skip/fail stated).

## 7. AI code review (unless `--skip-ai`)

**Fresh context required.** Spawn a **read-only** reviewer subagent
(`spawn_subagent`, `subagent_type: general-purpose`, description prefix
`[reviewer]`). The orchestrator must not sole-author the verdict.

**Subagent prompt must include:**

- Plan Goal, Done when, Constraints (and Progress verification notes)
- How to collect the diff: merge-base of integration vs `feature/<slug>`
  (or current HEAD if already checked out)
- Output format from `.anchor/templates/review.md` if present, else
  `anchor/templates/review.md`: checklist; **Verdict** ACCEPT | REVISE |
  ESCALATE; structured findings (severity, file:line when known)
- **Read-only:** no product file edits; findings only

On spawn/empty failure: “AI pass skipped/failed: …” then continue.

## 8. Present package

1. Plan identity (path, slug, Goal)
2. Evidence (diff, Done when, PR/URLs)
3. AI verdict + top findings (or skip/fail)
4. How to exercise the system

## 9. Survey (required before lane moves)

Prefer `ask_user_question` (or equivalent) with options:

| Option | Meaning |
|--------|---------|
| **Approve** | Done when holds; sign off |
| **Needs Work** | Changes required — return to ready queue |
| **Skip** | Leave in `review-needed/` |
| **Defer** (optional) | → `blocked/` only if confirmed |

Re-prompt when free text is ambiguous. Sole plan + explicit
“approve \<slug\>” may count as Approve.

## 10. Follow-ups

One short round (+ one retry if unusable):

| Choice | Follow-ups |
|--------|------------|
| **Approve** | If AI REVISE/ESCALATE: required override confirmation with top issues. Optional note if ACCEPT. |
| **Needs Work** | Required actionable bullets; 1–3 clarifying prompts if vague. Write into plan `## Progress` / `## Review notes` **before** move. |
| **Skip** | Optional reason. |
| **Defer** | Blocker + unblock condition required. |

Empty Needs Work feedback → refuse move; stay in `review-needed/`.

## 11. Lane moves

| Choice | Move |
|--------|------|
| **Approve** | → `completed/` (optional `YYYY-MM-DD-` prefix); drop stale lease if any |
| **Needs Work** | → **`bugs/` or `features/`** (same basename); **never** `in-progress/` |
| **Skip** | No move |
| **Defer** | → `blocked/` with note |

### Needs Work → bugs vs features

Same table as **`/draft --promote`**:

| Prefer `bugs/` when… | Prefer `features/` when… |
|----------------------|---------------------------|
| Fix / regression / crash / incorrect behavior | New capability, add/support/enable |
| Repair existing behavior | Header **Value:** high\|medium\|low |
| Pure defect language in Goal | Expansion of product surface |

Human override wins; if ambiguous ask once; refuse if target basename exists;
footer states lane + reason.

## 12. Footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include final path, AI verdict, survey choice, ready-lane reason if Needs Work,
remaining queue count. **Do not** start the next plan.

## Out of scope

- Executing plan Steps (`/work`)
- Promoting drafts
- Auto-merging feature branches
- Multi-plan sessions
- AI auto-Approve without survey
- Needs Work → `in-progress/`

## Quick discovery

```bash
ls -la .plans/review-needed
ls .plans/bugs .plans/features .plans/in-progress \
   .plans/completed 2>/dev/null
```
