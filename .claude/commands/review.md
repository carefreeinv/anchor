---
description: Human sign-off for review-needed — AI critic, survey; Approve merges feature→dev; empty queue can promote dev→main
argument-hint: "[slug|--list|--skip-ai|--no-launch|--promote|--no-promote|--push]"
---

# /review — human sign-off + integrate

Two modes, **one decision per invocation**:

1. **Plan review** — one plan under **`.plans/review-needed/`**: evidence, AI
   critic, survey. **Approve** merges `feature/<slug>` → **integration**
   (`dev` / `develop`), then moves the plan to `completed/`.
2. **Promotion review** — when the plan queue is empty (or `/review --promote`)
   and integration is **ahead of mainline**: evidence for `main`…`dev`, survey.
   **Promote** merges integration → **mainline** (`main` / `master`).

This is **not** free-form “code review any PR.” Ad-hoc diffs belong to the
platform’s code-review tools. This skill’s home is **`review-needed/`** plus
the empty-queue promotion path.

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

   Do **not** ask Approve/Needs Work before the AI pass finishes (or a clear
   “AI pass skipped/failed: …” message), unless `--skip-ai`.
3. **AI is advisory.** It never auto-approves or auto-rejects. The human
   survey is authoritative for merges and lane moves.
4. **`review-needed/` → `completed/`** only after **Approve** in the survey
   (plus any required override follow-up) **and** the feature→integration merge
   succeeded (or there was nothing to merge). Weak “lgtm” without survey choice
   does not complete — re-prompt when ambiguous.
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

Optional ahead advisory: `python scripts/pending_merges.py`.

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

**`--promote`:** skip plan selection; go to **Promotion review**. If
integration is not ahead of mainline, report and stop.

**Named slug:** resolve `review-needed/<slug>.md` or `<slug>.local.md` (unique
prefix OK). If the plan lives in another lane: refuse; point at the right
command (`/work`, `/draft`, …). Plan mode.

**Bare `/review`:**

1. If any `review-needed` plans: pick **one** by Priority (P1→P3, default P2) →
   Value (high→low, default medium) → oldest mtime → filename. State why it won.
   Other queued plans: **one line** only. Plan mode.
2. Else if `--no-promote`: report empty queue; stop.
3. Else if integration is ahead of mainline: **promotion mode**.
4. Else: report empty queue + nothing to promote; optional `pending_merges.py`
   one-liner; stop.

## 3. Load plan (plan mode)

Read the full file. Restate **Goal**, **Done when**, **Preferred models**,
**Progress** (if any) in ≤15 lines. Slug = filename without `.md` / `.local.md`.

## 4. Branch checkout (safe only, plan mode)

Feature branch: `feature/<slug>` (same idea as
`scripts/worktree_for_agent.py` `feature_branch_name`).

| Situation | Action |
|-----------|--------|
| Already on `feature/<slug>` | Leave it; report status |
| Clean tree, branch exists locally | `git checkout feature/<slug>` |
| Clean tree, only on remote | Check out tracking branch from `origin/feature/<slug>` |
| Dirty tree / other feature work | **Do not** switch. Offer worktree: `python scripts/worktree_for_agent.py ensure --project <root> --agent-id review --slug <slug>` or stop |
| Branch missing | Continue with plan + any available refs; never invent a branch |

Report `git status` and shortstat vs integration.

## 5. Evidence pack (plan mode)

Build a short pack for the human:

- Diff summary vs integration (files, shortstat); top-level change themes
- Done when checklist (for human judgment — do not auto-tick)
- PR URL if `gh pr view` works for this branch
- Pointers to verification notes in plan Progress if present
- Whether `feature/<slug>` has commits not in integration

## 6. Launch (unless `--no-launch`, plan mode)

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

## 8. Present package (plan mode)

Show the human, in one structured block:

1. Plan identity (path, slug, Goal)
2. Evidence (diff, Done when, PR/URLs, commits ahead of integration)
3. AI verdict + top findings (or skip/fail reason)
4. How to exercise the system (launch URLs/commands)
5. Note: **Approve will merge `feature/<slug>` → integration, then archive**

## 9. Survey (plan mode)

Use the product’s ask/question UI when available; else a numbered menu:

| Option | Meaning |
|--------|---------|
| **Approve** | Done when holds; merge feature → integration; archive |
| **Needs Work** | Changes required — return to ready queue (no merge) |
| **Skip** | Not now; leave in `review-needed/` (no merge) |
| **Defer** (optional) | External blocker → `blocked/` only if confirmed (no merge) |

Do not treat free-text “lgtm” as Approve without a clear Approve selection
(sole queued plan + explicit “approve \<slug\>” is acceptable). Re-prompt when
ambiguous.

## 10. Follow-ups (plan mode)

Ask only what is missing (one short round; one retry if still unusable):

| Choice | Follow-ups |
|--------|------------|
| **Approve** | If AI was REVISE/ESCALATE: **required** — “Approve despite critic concerns?” with top issues restated; need explicit yes. Optional archive note if AI was ACCEPT. |
| **Needs Work** | **Required** actionable bullets. If vague (“fix it”): ask 1–3 concrete questions (which Done when fails? which AI finding? docs vs behavior?). Write answers into plan `## Progress` or `## Review notes` **before** moving. |
| **Skip** | Optional one-liner reason. |
| **Defer** | What blocks + what unblocks (**required** before `blocked/`). |

Needs Work with still-empty feedback → **refuse move**; stay in
`review-needed/`; note that actionable feedback is required.

## 11. Merge feature → integration (Approve only)

**Only after** survey Approve (+ required override). Order is hard:

1. **Clean tree required.** If dirty: stop; leave plan in `review-needed/`; no merge.
2. Resolve integration branch (create `dev` from mainline if needed).
3. If no `feature/<slug>` (local or remote): **skip merge**; note “no branch to
   merge”; proceed to lane move.
4. If already fully contained in integration: skip merge; note “already on
   integration”; proceed to lane move.
5. Otherwise, with a clean tree:

   ```bash
   git checkout <integration>
   git merge --ff-only feature/<slug>
   # if that fails (not FF-able):
   git merge --no-ff feature/<slug> -m "Merge feature/<slug>: <plan title>"
   ```

6. **On conflict:** `git merge --abort` if in progress; leave plan in
   `review-needed/`; report conflict paths; **do not** move to `completed/`.
7. **On success:** report new HEAD of integration; then lane move.
8. **Push:** only if `--push` or human confirms after local success:
   `git push origin <integration>`. Never force-push. Hook rejection → surface
   output; do not retry with `--no-verify`.

Prefer a dedicated clean worktree for the merge if checkout is blocked by
another worktree.

## 12. Lane moves (plan mode)

| Choice | Move |
|--------|------|
| **Approve** (merge OK or nothing to merge) | `git mv` (or `mv`) `review-needed/<file>` → `completed/` (optional `YYYY-MM-DD-` prefix). Drop any stale lease for the plan if present. |
| **Approve** (merge required and failed) | **No move** — stay in `review-needed/` |
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

---

## Promotion review (empty queue or `--promote`)

### When

- `review-needed/` has no plans (or `--promote` forces this path), **and**
- integration exists and is ahead of mainline

If not ahead: report and stop (with `--promote`, say why).

### Evidence

- `git log --oneline <mainline>..<integration>`
- `git diff --stat <mainline>...<integration>`
- Optional: `python scripts/pending_merges.py`
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
2. Prefer `git checkout <mainline> && git merge --ff-only <integration>`; if not
   FF-able, `git merge --no-ff <integration> -m "Merge <integration> into <mainline>"`.
3. Conflict → abort; no push; report files.
4. Success → report SHAs. Push `origin <mainline>` only with confirm / `--push`.
5. If histories have diverged badly: **stop and report** (“integrate main→dev
   first”) rather than inventing policy — do not force.

No plan lane moves in promotion mode.

---

## 13. Footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: mode (plan vs promotion), plan path after any move, AI verdict, survey
choice, merge result (SHAs / skipped / conflict), push done or not, remaining
`review-needed/` count. **Do not** start the next plan or chain into promotion
after a plan Approve in the same invocation (human re-runs `/review`).

## Out of scope

- Executing plan Steps (`/work`)
- Promoting drafts (`/draft --promote`)
- Merging without survey Approve/Promote
- Reviewing more than one plan per invocation
- AI auto-Approve without human survey
- Moving Needs Work into `in-progress/`
- Force-push, `--no-verify`, deleting feature branches by default

## Quick discovery

```bash
ls -la .plans/review-needed
ls .plans/bugs .plans/features .plans/in-progress \
   .plans/completed 2>/dev/null
python scripts/pending_merges.py
git rev-list --count main..dev 2>/dev/null
```
