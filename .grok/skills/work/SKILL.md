---
name: work
description: >
  Execute the next (or named) ready plan from ./.plans. Use when the user runs
  /work, asks to work the backlog, pick up a plan, continue planned work, or
  execute a plan under .plans/bugs or .plans/features.
argument-hint: "[slug|path|--list|--no-fit-check]"
disable-model-invocation: false
metadata:
  short-description: "Execute next plan from ./.plans"
---

# /work — execute a tracked plan from `./.plans`

Start (or resume) **implementation** of a ready plan. Plans are git-tracked
markdown under **`.plans/`** (dotdir — use that path explicitly; many UIs hide it).

If `.plans/README.md` exists, treat it as the process contract. This skill is the
entrypoint; do not re-derive priority rules from chat history alone.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/work` | Pick highest-priority **model-fit** ready plan and execute it |
| `/work --list` | List ready plans (incl. Preferred models + fit); **do not** implement |
| `/work --no-fit-check` | Same priority as bare `/work`, but **skip model-fit filtering** (still one plan, not the whole backlog) |
| `/work --no-fit-check <slug>` | Execute that plan even if Preferred models say otherwise |
| `/work <slug>` | Match `slug.md` or `slug.local.md` under ready lanes |
| `/work .plans/features/foo.md` | Execute that path if it is a ready-lane file |

`$ARGUMENTS` is everything after `/work`. Parse flags and the optional target from it.

## Lanes (hard rules)

| Path | Read? | Execute? | Complete (`git mv` to completed)? |
|------|-------|----------|----------------------------------|
| `.plans/bugs/` | yes | **yes** (highest priority) | **yes** |
| `.plans/features/` | yes | **yes** (after all bugs) | **yes** |
| `.plans/drafts/` | yes (edit plan only) | **no** | **no** |
| `.plans/completed/` | yes (history) | **no** | n/a |

**Never** implement from `drafts/` or `completed/`. If the user names a draft:
refuse execution; offer **edit-only**. Do **not** promote it.

### Agent move rule (hard)

The **only** `git mv` (or equivalent relocate) an agent may perform under
`.plans/` is ready-lane → `completed/` when **Done when** holds:

```text
.plans/bugs|features/<slug>.md  →  .plans/completed/
```

Agents must **never** move plans between `drafts/`, `bugs/`, and `features/`
(no promote, demote, or lane swaps). **Promotion is human-only.**

## Priority (when no target is given)

1. All of `.plans/bugs/*.md` before any feature.
2. Then `.plans/features/*.md` ordered by header `Value: high | medium | low`
   (default **medium** if absent): high → medium → low; ties by filename.
3. Among those, keep only **model-fit** plans (next section) — unless
   `--no-fit-check` is set.
4. Skip `drafts/`, `completed/`, and `README.md`.

If multiple plans share the top priority and the user did not say “just pick”,
print a short menu (path + first heading + Preferred models) and ask which to
run. If they said “just pick” / “go” / equivalent, take the first in sorted
order without asking again.

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
5. **`--list`:** for each ready plan show path, lane, Value, Status, Preferred
   models, and your fit (`good` / `overqualified` / `underqualified` /
   `unknown`). Do not implement. Fit is still computed under `--list` even if
   `--no-fit-check` is also passed (list is informational).
6. Per-step **Route to** still applies after load for mixed-difficulty steps.

Right-size works both ways: expensive models leave cheap work on the table;
small models do not grab architecture plans to "try hard."

## Steps

### 1. Resolve project root and inventory

- Find the git repo root (or CWD if not a git repo).
- Confirm `.plans/` exists (`ls -la .plans` — include the leading dot).
- If missing: stop and explain that `/work` needs a `.plans/` tree; point at
  Anchor’s formalize-plans workflow or create the layout if the user asks.
- Skim headers of ready-lane `*.md` for Value, Status, Preferred models.

### 2. Parse arguments

- Flags may combine with a slug/path: e.g. `/work --no-fit-check formalize-plans-workflow`.
- `--list` / `-l` → list ready plans (path, lane, Value, Status, Preferred
  models, fit); stop.
- `--no-fit-check` → disable model-fit skip for this run (see Model fit rules);
  does not change lane priority and does not execute more than one plan.
- Otherwise treat remaining token as **slug** or **path**.
- Path under `drafts/` or `completed/` → refuse execute (see lanes).
- Slug: find unique `{slug}.md` or `{slug}.local.md` under ready lanes; if zero
  or many matches, report and stop or disambiguate.

### 3. Load the plan

- Read the full markdown file.
- Restate **Goal**, **Preferred models**, and **Done when** in ≤10 lines.
- Do **not** rewrite the plan unless a step is impossible (then stop and say why).
- If `Status: in_progress` or a `## Progress` section exists, resume from the
  first incomplete step.

### 4. Mark in progress

- Set header `Status: in_progress` if that field exists or the file uses the
  Anchor plan header block. Do not require a mid-flight commit unless the user
  wants one.

### 5. Execute

- Walk **## Steps** in order (table rows or numbered list).
- For each step: do the work; run its **Verify by** command when present.
- One step at a time; no opportunistic drive-bys outside the plan’s file scope.
- Two failed fix attempts on the same error → stop; summarize attempts +
  hypothesis; escalate (do not thrash).
- Honor per-step **Route to** (fleet offload / escalate / downgrade) when present.

### 6. Complete or pause

**Done when** all checklist items hold and verifications pass:

1. Set `Status: done` (and optional date).
2. `git mv` the file to `.plans/completed/` (create the dir if needed). Optional
   rename: `YYYY-MM-DD-<slug>.md`.
3. Session footer: `## Result`, `## How to verify`, `## Deferred / concerns`,
   including the new path under `completed/`.

**If the user stops mid-plan:** leave the file in its ready lane with
`Status: in_progress` and a brief `## Progress` note (what finished / what’s
next). Do **not** move to `completed/`.

## Output footer

End every substantive `/work` turn with:

```text
## Result
## How to verify
## Deferred / concerns
```

## Out of scope

- Creating new plans (use plan mode / planner / write under `.plans/drafts/`)
- **Promoting** drafts → `bugs/` or `features/` (human-only; never `git mv` between those lanes)
- Executing every ready plan in one shot unless the user explicitly asks to
  continue to the next after finishing one
- Running `git commit` unless the user asks

## Quick discovery commands

```bash
ls -la .plans
ls .plans/bugs .plans/features .plans/drafts .plans/completed 2>/dev/null
```
