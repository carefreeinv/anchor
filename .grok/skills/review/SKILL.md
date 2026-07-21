---
name: review
description: >
  Human sign-off for .plans/review-needed/ work: check out the feature branch,
  run a fresh-context AI critic pass, survey (Approve / Needs Work / Skip), then
  on Approve merge feature → dev and archive the plan. Empty queue with dev ahead
  of main offers a promotion review (dev → main). Use when the user runs /review,
  asks to sign off review-needed plans, or promote integration to mainline.
argument-hint: "[slug|--list|--skip-ai|--no-launch|--promote|--no-promote|--push]"
disable-model-invocation: false
metadata:
  short-description: "Sign off plan (merge→dev) or promote dev→main"
---

# /review — human sign-off + integrate

Two modes, **one decision per invocation**:

1. **Plan review** — one plan under **`.plans/review-needed/`**: evidence, AI
   critic, survey. **Approve** merges `feature/<slug>` → **integration**
   (`dev` / `develop`), then moves the plan to `completed/`.
2. **Promotion review** — when the plan queue is empty (or `/review --promote`)
   and integration is **ahead of mainline**: evidence for `main`…`dev`, survey.
   **Promote** merges integration → **mainline** (`main` / `master`).

This skill **embeds** an AI critic pass; it is not a separate “code review any
diff” product. For ad-hoc uncommitted/PR review outside these modes, use the
platform’s code-review tools.

`$ARGUMENTS` is everything after `/review`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/review` | Plan mode if queue non-empty; else promotion mode if integration ahead of mainline; else stop |
| `/review <slug>` | Plan session for that `review-needed/` plan |
| `/review --list` | Inventory queue + one-line “integration ahead of mainline: N” if any; no merge |
| `/review --skip-ai` | Evidence + survey only (still one decision) |
| `/review --no-launch` | Skip auto-launch of local systems |
| `/review --promote` | Force **promotion** mode (refuses if not ahead); ignore plan pick |
| `/review --no-promote` | Empty queue → stop without offering promotion |
| `/review --push` | After a **successful local merge**, also offer/confirm `git push` of the updated branch(es) |

Flags may combine with a slug: `/review --no-launch my-slug`.

## Hard rules

1. **One decision per invocation.** Either one plan review **or** one promotion
   review — never both, never auto-start the next plan. Footer may note remaining
   queue count only.
2. **Pipeline order** (plan mode):

   ```text
   select → checkout (if safe) → evidence + optional launch
          → AI code review (fresh context)
          → present package
          → survey → follow-ups
          → merge feature → integration (on Approve)
          → lane move to completed/ (only after merge success or “nothing to merge”)
   ```

   Promotion mode:

   ```text
   detect empty queue + ahead → evidence (log/shortstat)
        → optional AI on mainline..integration
        → survey Promote / Skip / Defer
        → merge integration → mainline (on Promote)
   ```

   Do **not** open the survey before the AI pass finishes (or a clear
   “AI pass skipped/failed: …” message), unless `--skip-ai`.
3. **AI is advisory.** Never auto-approve/reject. Survey is authoritative.
4. **`review-needed/` → `completed/`** only after survey **Approve** (+
   override follow-up when AI was REVISE/ESCALATE) **and** the feature→integration
   merge succeeded (or there was nothing to merge). Re-prompt on ambiguous free text.
5. **Needs Work** → **`bugs/` or `features/`** (inferred), **never**
   `in-progress/`. Actionable notes required first. **No merge** on Needs Work.
6. **Merge only after human survey Approve / Promote.** Never merge on AI ACCEPT
   alone. **Never force-push. Never delete branches** unless the human explicitly
   asks after a successful merge (default: leave `feature/<slug>`). **Push to
   `origin` only** with confirm after local success, or when `--push` was set
   (still confirm once). Default is **local merge only**.
7. Preserve basenames (including `.local.md`) on every move.
8. **`/work` and executors never merge.** Only this skill after survey may land
   branches on integration/mainline.

## Integration / mainline resolution

Same order as `scripts/worktree_for_agent.py` / `scripts/pending_merges.py`:

| Role | Candidates (first that exists) |
|------|--------------------------------|
| **Integration** | `dev`, then `develop`. If neither exists, **create `dev`** from mainline (`main`, else `master`) before merging. |
| **Mainline** | `main`, then `master` |

Optional ahead advisory: `python scripts/pending_merges.py` (feature→integration
and integration→mainline rows).

## 1. Resolve project

Find a root with `.plans/` (CWD, then git root). Print the absolute path.
If missing: explain and stop.

## 2. Select mode and target

Parse flags: `--list`, `--skip-ai`, `--no-launch`, `--promote`, `--no-promote`,
`--push`, optional slug.

**`--list`:** list each `review-needed/*.{md,local.md}` (skip `.gitkeep`): path,
Priority, Value, Goal one-liner, whether `feature/<slug>` exists. Also print one
line: `integration (<name>) ahead of mainline (<name>): N commits` (or `0` /
not a git repo). Stop — no checkout, AI, survey, or merge.

**`--promote`:** skip plan selection; go to **§ Promotion review**. If
integration is not ahead of mainline, report and stop.

**Named slug:** resolve under `review-needed/` only. Other lane → refuse with
the right command pointer. Plan mode.

**Bare `/review`:**

1. If any `review-needed` plans: pick **one** by Priority (P1→P3, default P2) →
   Value (high→low, default medium) → oldest mtime → filename. State why it won.
   Other queued plans: **one line** only. Plan mode.
2. Else if `--no-promote`: report empty queue; stop.
3. Else if integration is ahead of mainline: **promotion mode** (§ Promotion).
4. Else: report empty queue + nothing to promote; optional `pending_merges.py`
   one-liner; stop.

## 3. Load plan (plan mode)

Read fully. Restate Goal, Done when, Preferred models, Progress ≤15 lines.
Slug = filename without `.md` / `.local.md`.

## 4. Branch checkout (safe only, plan mode)

Branch name: `feature/<slug>` (same rules as
`scripts/worktree_for_agent.feature_branch_name`).

| Situation | Action |
|-----------|--------|
| Already on branch | Leave it; report status |
| Clean tree + local branch | `git checkout feature/<slug>` |
| Clean tree + remote only | Tracking checkout from `origin/feature/<slug>` |
| Dirty tree | **Do not** switch; offer `python scripts/worktree_for_agent.py ensure --project <root> --agent-id review --slug <slug>` or stop |
| Missing branch | Continue with plan + available refs; never invent a branch |

Report `git status` and shortstat vs integration.

## 5. Evidence pack (plan mode)

- Diff summary vs integration (files, shortstat, themes)
- Done when checklist for human judgment (do not auto-tick)
- PR URL if `gh pr view` works
- Verification notes from plan Progress if present
- Whether `feature/<slug>` has commits not in integration (`git rev-list --count <integration>..feature/<slug>`)

## 6. Launch (unless `--no-launch`, plan mode)

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

## 8. Present package (plan mode)

1. Plan identity (path, slug, Goal)
2. Evidence (diff, Done when, PR/URLs, commits ahead of integration)
3. AI verdict + top findings (or skip/fail)
4. How to exercise the system
5. Note: **Approve will merge `feature/<slug>` → integration, then archive**

## 9. Survey (plan mode)

Prefer `ask_user_question` (or equivalent) with options:

| Option | Meaning |
|--------|---------|
| **Approve** | Done when holds; merge feature → integration; archive |
| **Needs Work** | Changes required — return to ready queue (no merge) |
| **Skip** | Leave in `review-needed/` (no merge) |
| **Defer** (optional) | → `blocked/` only if confirmed (no merge) |

Re-prompt when free text is ambiguous. Sole plan + explicit
“approve \<slug\>” may count as Approve.

## 10. Follow-ups (plan mode)

One short round (+ one retry if unusable):

| Choice | Follow-ups |
|--------|------------|
| **Approve** | If AI REVISE/ESCALATE: required override confirmation with top issues. Optional note if ACCEPT. |
| **Needs Work** | Required actionable bullets; 1–3 clarifying prompts if vague. Write into plan `## Progress` / `## Review notes` **before** move. |
| **Skip** | Optional reason. |
| **Defer** | Blocker + unblock condition required. |

Empty Needs Work feedback → refuse move; stay in `review-needed/`.

## 11. Merge feature → integration (Approve only)

**Only after** survey Approve (+ required override). Order is hard:

1. **Clean tree required.** If dirty: stop; leave plan in `review-needed/`; no merge.
2. Resolve integration branch (create `dev` from mainline if needed).
3. If no `feature/<slug>` (local or remote): **skip merge**; note “no branch to
   merge”; proceed to lane move.
4. If `git rev-list --count <integration>..feature/<slug>` is `0`: skip merge;
   note “already on integration”; proceed to lane move.
5. Otherwise, with a clean tree:

   ```bash
   git checkout <integration>
   git merge --ff-only feature/<slug>
   # if that fails (not FF-able):
   git merge --no-ff feature/<slug> -m "Merge feature/<slug>: <plan title>"
   ```

6. **On conflict:** `git merge --abort` if in progress; leave plan in
   `review-needed/`; report conflict paths; **do not** move to `completed/`.
7. **On success:** report new HEAD of integration; then lane move (§12).
8. **Push:** only if `--push` or human confirms after local success:
   `git push origin <integration>`. Never force-push. Hook rejection → surface
   output; do not retry with `--no-verify`.

Prefer a dedicated clean worktree for the merge if the current tree holds
another branch checked out in a second worktree that blocks checkout.

## 12. Lane moves (plan mode)

| Choice | Move |
|--------|------|
| **Approve** (merge OK or nothing to merge) | → `completed/` (optional `YYYY-MM-DD-` prefix); drop stale lease if any |
| **Approve** (merge required and failed) | **No move** — stay in `review-needed/` |
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

---

## Promotion review (empty queue or `--promote`)

### When

- `review-needed/` has no plans (or `--promote` forces this path), **and**
- integration exists and `git rev-list --count <mainline>..<integration>` > 0

If not ahead: report and stop (with `--promote`, say why).

### Evidence

- `git log --oneline <mainline>..<integration>`
- `git diff --stat <mainline>...<integration>`
- Optional: `python scripts/pending_merges.py` table
- Optional AI critic (`--skip-ai` to skip) on that range — same
  `templates/review.md` verdict shape; advisory only

### Survey

| Option | Meaning |
|--------|---------|
| **Promote to main** | Merge integration → mainline |
| **Skip** | Leave branches as-is |
| **Defer** | Note only; no merge |

### Merge integration → mainline (Promote only)

1. Clean tree required; else stop.
2. ```bash
   git checkout <mainline>
   git merge --ff-only <integration>
   # if not FF-able:
   git merge --no-ff <integration> -m "Merge <integration> into <mainline>"
   ```
3. Conflict → abort; no push; report files.
4. Success → report SHAs. Push `origin <mainline>` only with confirm / `--push`.
5. If mainline has commits not in integration (diverged): prefer attempting the
   merge; if messy, **stop and report** (“integrate main→dev first”) rather than
   inventing policy — do not force.

No plan lane moves in promotion mode.

---

## 13. Footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: mode (plan vs promotion), final plan path if any, AI verdict, survey
choice, merge result (SHAs / skipped / conflict), push done or not, remaining
queue count. **Do not** start the next plan or chain into promotion after a plan
Approve in the same invocation (human re-runs `/review`).

## Out of scope

- Executing plan Steps (`/work`)
- Promoting drafts
- Merging without survey Approve/Promote
- Multi-plan sessions
- AI auto-Approve without survey
- Needs Work → `in-progress/`
- Force-push, `--no-verify`, deleting feature branches by default
- Release tags / version bumps on main merge

## Quick discovery

```bash
ls -la .plans/review-needed
ls .plans/bugs .plans/features .plans/in-progress \
   .plans/completed 2>/dev/null
python scripts/pending_merges.py
git rev-list --count main..dev 2>/dev/null
```
