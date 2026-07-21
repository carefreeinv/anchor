---
description: Human sign-off for .plans/review-needed/ — AI critic pass, then survey (Approve / Needs Work / Skip)
argument-hint: "[slug|--list|--skip-ai|--no-launch]"
---

# /review — human sign-off for `review-needed/` work

Run a **single** human review session for one plan under **`.plans/review-needed/`**:
check out its feature branch when safe, optionally launch inspection systems,
run a **fresh-context AI code review**, present the package, then collect a
**survey** decision (Approve / Needs Work / Skip / optional Defer) with
follow-ups before any lane move.

This is **not** free-form “code review any PR.” Ad-hoc diffs belong to the
platform’s code-review tools. This skill’s home is **`review-needed/`**.

`$ARGUMENTS` is everything after `/review`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/review` | Pick **one** plan from `review-needed/`; full session (AI + survey) |
| `/review <slug>` | Same for that plan if it is under `review-needed/`; else refuse |
| `/review --list` | Inventory `review-needed/` only — no checkout, AI, launch, or survey |
| `/review --skip-ai` | Evidence + survey only (still one plan) |
| `/review --no-launch` | Skip auto-launch of local systems |

Flags may combine with a slug: `/review --no-launch my-slug`.

## Hard rules

1. **One plan per invocation.** Never batch, never auto-start the next after
   finishing. Footer may say “N still in review-needed; re-run `/review`.”
2. **Pipeline order** (fixed):

   ```text
   select → checkout (if safe) → evidence + optional launch
          → AI code review (fresh context)
          → present package
          → survey → follow-ups → lane move
   ```

   Do **not** ask Approve/Needs Work before the AI pass finishes (or a clear
   “AI pass skipped/failed: …” message).
3. **AI is advisory.** It never auto-approves or auto-rejects. The human
   survey is authoritative for lane moves.
4. **`review-needed/` → `completed/`** only after **Approve** in the survey
   (plus any required override follow-up). Weak “lgtm” without survey choice
   does not complete — re-prompt the survey when ambiguous.
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

**Named slug:** resolve `review-needed/<slug>.md` or `<slug>.local.md` (unique
prefix OK). If the plan lives in another lane: refuse; point at the right
command (`/work`, `/draft`, …).

**Bare `/review`:** among `review-needed/*.md` and `*.local.md`, pick **one**
by Priority (P1→P3, default P2) → Value (high→low, default medium) → oldest
mtime → filename. State why it won. Other queued plans: **one line** only.

**Empty queue:** report empty. One optional advisory line from
`python scripts/pending_merges.py` if useful — **not** a second review session.
If the user only wanted ad-hoc code review: say this skill is for plan
sign-off; use the platform’s code-review skill for arbitrary diffs. Stop.

## 3. Load plan

Read the full file. Restate **Goal**, **Done when**, **Preferred models**,
**Progress** (if any) in ≤15 lines. Slug = filename without `.md` / `.local.md`.

## 4. Branch checkout (safe only)

Feature branch: `feature/<slug>` (same idea as
`scripts/worktree_for_agent.py` `feature_branch_name`).

| Situation | Action |
|-----------|--------|
| Already on `feature/<slug>` | Leave it; report status |
| Clean tree, branch exists locally | `git checkout feature/<slug>` |
| Clean tree, only on remote | Check out tracking branch from `origin/feature/<slug>` |
| Dirty tree / other feature work | **Do not** switch. Offer worktree: `python scripts/worktree_for_agent.py ensure --project <root> --agent-id review --slug <slug>` or stop |
| Branch missing | Continue with plan + any available refs; never invent a branch |

Report `git status` and shortstat vs integration (`dev`, else `develop`, else
`main`, else `master` — first that exists).

## 5. Evidence pack

Build a short pack for the human:

- Diff summary vs integration (files, shortstat); top-level change themes
- Done when checklist (for human judgment — do not auto-tick)
- PR URL if `gh pr view` works for this branch
- Pointers to verification notes in plan Progress if present

## 6. Launch (unless `--no-launch`)

Discover **low-risk** inspection targets **scoped to this plan’s touches**
(Steps/Touches, docs site, package `dev`/`start`, open PR):

- **Auto-launch OK:** documented docs `npm start`, clear local `dev` with no
  destructive pre-steps. Prefer background; report URL + how to stop.
- **Confirm first** (or print-only): Docker Compose, migrations, privileged
  ports, remote deploys, `sudo`, destructive resets, multi-service fleets.
- Nothing useful → one line “no launch.”

Launch may run while the AI pass runs; the **survey waits** for the AI pack
(or skip/fail message).

## 7. AI code review (unless `--skip-ai`)

Run the critic in a **fresh context** (subagent / separate Task). The
orchestrator of this session must **not** be the sole author of the verdict
(Anchor self-review rule).

**Inputs:** plan Goal + Done when + Constraints; branch diff vs integration;
verification notes if available.

**Output shape:** project `.anchor/templates/review.md` if present, else
`anchor/templates/review.md` (checklist; **Verdict** ACCEPT | REVISE |
ESCALATE; notes). Prefer structured findings (severity, file:line when known).
Empty findings + ACCEPT is legitimate.

**Read-only:** critic must not edit product code. On spawn/empty failure:
surface “AI pass skipped/failed: …” and continue to present + survey.

## 8. Present package

Show the human, in one structured block:

1. Plan identity (path, slug, Goal)
2. Evidence (diff, Done when, PR/URLs)
3. AI verdict + top findings (or skip/fail reason)
4. How to exercise the system (launch URLs/commands)

## 9. Survey (required before lane moves)

Use the product’s ask/question UI when available; else a numbered menu:

| Option | Meaning |
|--------|---------|
| **Approve** | Done when holds; sign off |
| **Needs Work** | Changes required — return to ready queue |
| **Skip** | Not now; leave in `review-needed/` |
| **Defer** (optional) | External blocker → `blocked/` only if confirmed |

Do not treat free-text “lgtm” as Approve without a clear Approve selection
(sole queued plan + explicit “approve \<slug\>” is acceptable). Re-prompt when
ambiguous.

## 10. Follow-ups

Ask only what is missing (one short round; one retry if still unusable):

| Choice | Follow-ups |
|--------|------------|
| **Approve** | If AI was REVISE/ESCALATE: **required** — “Approve despite critic concerns?” with top issues restated; need explicit yes. Optional archive note if AI was ACCEPT. |
| **Needs Work** | **Required** actionable bullets. If vague (“fix it”): ask 1–3 concrete questions (which Done when fails? which AI finding? docs vs behavior?). Write answers into plan `## Progress` or `## Review notes` **before** moving. |
| **Skip** | Optional one-liner reason. |
| **Defer** | What blocks + what unblocks (**required** before `blocked/`). |

Needs Work with still-empty feedback → **refuse move**; stay in
`review-needed/`; note that actionable feedback is required.

## 11. Lane moves (after survey + required follow-ups)

| Choice | Move |
|--------|------|
| **Approve** | `git mv` (or `mv`) `review-needed/<file>` → `completed/` (optional `YYYY-MM-DD-` prefix). Drop any stale lease for the plan if present. |
| **Needs Work** | → **`bugs/` or `features/`** (same basename). See inference below. **Never** `in-progress/`. |
| **Skip** | No move. |
| **Defer** | → `blocked/` with blocker note in the plan. |

### Needs Work → bugs vs features

Reuse **`/draft --promote`** inference (do not fork forever):

| Prefer `bugs/` when… | Prefer `features/` when… |
|----------------------|---------------------------|
| Fix / regression / crash / incorrect behavior | New capability, add/support/enable |
| Repair existing behavior | Header **Value:** high\|medium\|low |
| Pure defect language in Goal | Expansion of product surface |

1. Explicit human override this turn wins (“as a bug”, “to features”).
2. Else apply the table from Goal / headers / Steps.
3. If still ambiguous: **ask once** (bug vs feature); do not guess.
4. Footer: inferred lane + one-line reason.

Refuse if target basename already exists in that ready lane (report both
paths; leave file in `review-needed/`).

## 12. Footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: plan path after any move, AI verdict, survey choice, ready-lane
reason if Needs Work, remaining `review-needed/` count. **Do not** start the
next plan.

## Out of scope

- Executing plan Steps (`/work`)
- Promoting drafts (`/draft --promote`)
- Auto-merging feature branches
- Reviewing more than one plan per invocation
- AI auto-Approve without human survey
- Moving Needs Work into `in-progress/`

## Quick discovery

```bash
ls -la .plans/review-needed
ls .plans/bugs .plans/features .plans/in-progress \
   .plans/completed 2>/dev/null
```
