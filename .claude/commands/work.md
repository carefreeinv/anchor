---
description: Execute the next (or named) ready plan from ./.plans — backlog work entrypoint
argument-hint: "[slug|path|--list|--no-fit-check]"
---

# /work — execute a tracked plan from `./.plans`

Start (or resume) **implementation** of a ready plan. Plans are git-tracked
markdown under **`.plans/`** (dotdir — use that path explicitly; many UIs hide it).

If `.plans/README.md` exists, treat it as the process contract. This command is
the entrypoint; do not re-derive priority rules from chat history alone.

**Path is authoritative.** A plan’s lane and lifecycle are determined only by
which directory it lives in — never by `Lane:` or `Status:` fields inside the
file. Ignore those fields if present; do not write them.

`$ARGUMENTS` is everything after `/work`. Parse flags and the optional target from it.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/work` | Pick highest-priority **model-fit** ready plan and execute it |
| `/work --list` | List ready plans (incl. Preferred models + fit); **do not** implement |
| `/work --no-fit-check` | Same priority as bare `/work`, but **skip model-fit filtering** (still one plan, not the whole backlog) |
| `/work --no-fit-check <slug>` | Execute that plan even if Preferred models say otherwise |
| `/work <slug>` | Match `slug.md` or `slug.local.md` under ready lanes |
| `/work .plans/features/foo.md` | Execute that path if it is a ready-lane file |

## Lanes (hard rules)

| Path | Read? | Execute? | Notes |
|------|-------|----------|-------|
| `.plans/bugs/` | yes | **yes** (pick → move to in-progress) | highest priority ready |
| `.plans/features/` | yes | **yes** (after all bugs) | ready |
| `.plans/in-progress/` | yes | **only if you moved it there** | claimed; others **ignore** |
| `.plans/ambiguous/` | yes | **no** | half-baked; agent may park here |
| `.plans/blocked/` | yes | **no** | cannot fix now; agent may park here |
| `.plans/drafts/` | yes (edit plan only) | **no** | |
| `.plans/completed/` | yes (history) | **no** | |

**Never** implement from `drafts/` or `completed/`. **Ignore** every plan under
`in-progress/` that **you** did not move there (ownership = lease under
`.plans/.leases/` with your agent id, or you performed the mv this session).
If the user names a draft: refuse execution; offer **edit-only**. Do **not** promote it.

### Agent move rule (hard)

Agents may relocate plan files **only** as:

```text
bugs|features/     →  in-progress/     (start work + lease)
in-progress/       →  completed/       (Done when holds)
bugs|features|in-progress/  →  ambiguous/   (half-baked)
bugs|features|in-progress/  →  blocked/     (cannot fix now)
in-progress/       →  bugs|features/   (release for others)
ambiguous|blocked/ →  bugs|features/   (return when unblocked)
```

Agents must **never** promote drafts, move work into `drafts/`, or touch another
agent's `in-progress/` plan. **Promotion from drafts is human-only.**

## Priority (when no target is given)

1. **Your** plans under `.plans/in-progress/` first (resume).
2. All of `.plans/bugs/*.md` before any feature.
3. Within each lane, order by header `Priority: P1 | P2 | P3` (default **P2** if
   absent): P1 → P2 → P3; then `Value: high | medium | low` (default **medium**):
   high → medium → low; then oldest first (mtime), ties by filename.
4. Among ready plans, keep only **model-fit** plans (next section) — unless
   `--no-fit-check` is set.
5. **Skip plans with unmet `Depends on`** — do not start; report blockers.
6. Skip `drafts/`, `completed/`, `ambiguous/`, `blocked/`, foreign `in-progress/`,
   and `README.md`.

If multiple plans share the top priority, **just pick the first in sorted order**
(Priority → Value → oldest → filename) and start — this is the default; do **not**
print a menu or ask which to run. Name the other tied plans in one line so the
user can redirect if they want a different one. Only pause to ask when the user
**explicitly** asks to choose (e.g. "let me pick", "which should I run?").

## Model fit (required)

Plan headers SHOULD include:

```markdown
- **Preferred models:** <names and/or tiers>
```

Tiers: `small` | `mid` | `reasoner` | `frontier` (see `anchor/templates/plan.md`,
`anchor/ANCHOR.md` routing, `anchor/model-fitness.md`). Absent field → treat as
**mid** (any solid executor; not a free pass for wasteful frontier pickup of
obviously trivial work after you load the Goal).

### Know yourself

Before selecting a plan, identify **your** model name and tier (product name if
known; otherwise the closest tier). Use that for matching.

### Matching

A plan is a **good fit** if you match any listed name (fuzzy: "Sonnet",
"Sonnet-class", "Claude Sonnet 5") or your tier is among the listed tiers /
clearly in the same class.

| Fit | Meaning | Bare `/work` |
|-----|---------|--------------|
| **good** | You are in Preferred models / same class | Eligible |
| **overqualified** | You are a clearly higher tier than all preferred (e.g. Fable/frontier on `small`/`mid` only) | **Skip** — leave for cheaper models |
| **underqualified** | Preferred needs reasoner/frontier (or named stronger models) and you are below that | **Skip** — leave for stronger models |
| **unknown** | No useful Preferred models signal and Goal is ambiguous | Eligible only after a one-line fit note; prefer plans with an explicit list |

### Rules

1. **Bare `/work`:** never start a plan that is overqualified or underqualified
   for you. Pick the highest-priority **good** fit instead.
2. **All ready plans are poor fit:** print a short table (path, Preferred models,
   fit reason) and **stop**. Do not silently burn the wrong tier. Suggest
   `/work --no-fit-check` (or a named slug), or a session with a listed model.
3. **`--no-fit-check`:** disable Preferred-models / tier filtering for this
   invocation only. Still pick **one** plan by normal lane/Value priority (or
   the named slug/path). Still **state fit in one line** before executing so the
   mismatch is visible — do not pretend the recommendation matched. Does **not**
   mean “run every plan in `.plans/`.”
4. **User names slug/path** (without `--no-fit-check`): explicit target overrides
   the skip — but **state the fit mismatch in one line first**, then proceed.
5. **`--list`:** for each ready plan show path, lane (from directory), Priority,
   Value, Preferred models, and your fit (`good` / `overqualified` / `underqualified` /
   `unknown`). Do not implement. Fit is still computed under `--list` even if
   `--no-fit-check` is also passed (list is informational).
6. Per-step **Route to** still applies after load for mixed-difficulty steps
   (Sonnet default; Opus/reasoner for deep/security; frontier for multi-hour
   autonomy via plan-then-delegate; smaller/local for mechanical rows).

Right-size works both ways: expensive models leave cheap work on the table;
small models do not grab architecture plans to "try hard."

## Steps

### 1. Resolve project root and inventory

- Find the git repo root (or CWD if not a git repo).
- Confirm `.plans/` exists (`ls -la .plans` — include the leading dot).
- If missing: stop and explain that `/work` needs a `.plans/` tree; point at
  Anchor's formalize-plans workflow or create the layout if the user asks.
- Inventory: your `in-progress/` (if any), then ready `bugs/`, `features/`.
  **Ignore** foreign `in-progress/` files. Skim headers for Priority, Value, and
  Preferred models only (not Status/Lane).

### 2. Parse arguments

- Flags may combine with a slug/path: e.g. `/work --no-fit-check formalize-plans-workflow`.
- `--list` / `-l` → list ready plans (path, lane-from-dir, Value, Preferred
  models, fit); stop.
- `--no-fit-check` → disable model-fit skip for this run (see Model fit rules);
  does not change lane priority and does not execute more than one plan.
- Otherwise treat remaining token as **slug** or **path**.
- Path under `drafts/` or `completed/` → refuse execute (see lanes).
- Slug: find unique match for `{slug}.md` or `{slug}.local.md` under ready
  lanes; if zero or many matches, report and stop or disambiguate.

### 3. Load the plan

- Read the full markdown file.
- Restate **Goal**, **Preferred models**, **Depends on**, and **Done when** in ≤10 lines.
- **Dependencies:** verify each Depends-on slug is satisfied (under `completed/` or
  git history of `completed/`, and not still open elsewhere). If unmet → **do not
  execute**; report blockers.
- Do **not** rewrite the plan unless a step is impossible (then stop and say why).
- If a `## Progress` section exists, resume from the first incomplete step.

### 4. Mark in progress

- If the plan is still under `bugs/` or `features/`, **move it** to
  `.plans/in-progress/` (same filename) before substantive work. Prefer
  `git mv` when the file is tracked. Optionally record a lease via
  `work_once.py` / `.plans/.leases/` with a stable agent id.
- Optionally add or update a brief `## Progress` note. Do **not** write
  `Status:` or `Lane:` fields.

### 5. Execute

- Walk **## Steps** in order (table rows or numbered list).
- For each step: do the work; run its **Verify by** command when present.
- One step at a time; no opportunistic drive-bys outside the plan's file scope.
- Two failed fix attempts on the same error → stop; summarize attempts +
  hypothesis; escalate (do not thrash).
- Honor per-step **Route to** (fleet offload / escalate / downgrade) when present.

### 6. Complete or pause

**Done when** all checklist items hold and verifications pass:

1. `git mv` the file from `in-progress/` to `.plans/completed/` (create the dir
   if needed). Optional rename: `YYYY-MM-DD-<slug>.md`. That move **is** the
   done marker — do not set a Status field. Drop any lease for the plan.
2. Session footer: `## Result`, `## How to verify`, `## Deferred / concerns`,
   including the new path under `completed/`.

**If the user stops mid-plan:** leave the file in **`in-progress/`** with a
brief `## Progress` note. Do **not** move to `completed/`. Other agents must
ignore it.

**If the plan is half-baked:** move to `.plans/ambiguous/` and note what is missing.

**If you cannot fix the issue:** move to `.plans/blocked/` (out of ready queue) or
return to `bugs/`|`features/` (release for another agent).

## Output footer

End every substantive `/work` turn with:

```text
## Result
## How to verify
## Deferred / concerns
```

## Git worktrees + branches + commits (when the project uses Git)

**One working tree ⇒ one HEAD.** Parallel agents must not share a single checkout.

### Worktree (preferred for parallel agents)

Before substantive code edits, ensure a **per-agent worktree** and do all file
work there:

```bash
python scripts/worktree_for_agent.py ensure \
  --project <repo> --agent-id <your-id> --slug <plan-slug>
# or after claim: work_once.py … --ensure-worktree
```

Layout: `var/worktrees/<agent-id>/` + `registry.json`. The helper ensures
integration **`dev`**/`develop` (creates **`dev` from `main`/`master`** if
missing). Optional `--slug` checks out `feature/<slug>` inside the worktree.

### Integration + feature branch

1. Prefer **`dev`**, else **`develop`**; create **`dev` from main/master** if neither
   exists (report creation; push `origin dev` when allowed).
2. Feature branch `feature/<slug>` **in your worktree** — never auto-merge to
   `dev`/`main`/`master`.
3. When plan work is complete (Done when holds / finishing `/work`):
   - Run **`/commit-prep`** first (**prep only** — tests, CHANGELOG, blog).
   - If gates are **green**: **stage + commit on the feature branch** (HEREDOC
     message). Optional `git push -u origin HEAD` when a remote feature branch is
     expected. Report branch + commit SHA.
   - If gates are **red**: do not commit; fix or stop per stop rules.
   - **Never** commit on `main`/`master`/`dev`/`develop`; **never** auto-merge to
     integration. Leave PR/merge to the human.

## Out of scope

- Creating new plans (use **`/draft`** → `.plans/drafts/`; optional `--local`)
- **Promoting** drafts → ready (use **`/draft --promote <slug>`**; never from `/work`)
- Executing every ready plan in one shot unless the user explicitly asks to
  continue to the next after finishing one
- Running `git commit` **without** `/commit-prep`, or committing when the user did
  not ask and the plan does not require it
- **Documenting plan backlog** as product docs (hard rule: docs describe **current
  shipped state**, not `.plans/` contents). When work ships, document the code —
  not this plan file.

## Quick discovery commands

```bash
ls -la .plans
ls .plans/bugs .plans/features .plans/in-progress \
   .plans/ambiguous .plans/blocked .plans/drafts .plans/completed 2>/dev/null
```
