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
| `.plans/review-needed/` | yes | **no** | agent believes `Done when` holds, awaiting human sign-off; human runs **`/review`** (AI + survey) → `completed/` or `bugs|features/` |
| `.plans/drafts/` | yes (edit plan only) | **no** | |
| `.plans/completed/` | yes (history) | **no** | |

**Never** implement from `drafts/` or `completed/`. **Bare `/work` never scans
`in-progress/`** — it picks only ready lanes. Every in-progress plan is **owned**
by whoever claimed it (a **required lease** under `.plans/.leases/` with an agent
id). **Ignore** every in-progress plan you do not own; a foreign, unleased, or
expired-lease in-progress plan is **never** silently reclaimed. Resuming your own
in-progress work is an **explicit named claim** (`/work in-progress/<slug>.md`,
or `work_once.py --recover` for an expired lease) — not a bare-pick side effect.
If the user names a draft: refuse execution; offer **edit-only**. Do **not** promote it.

### Agent move rule (hard)

Agents may relocate plan files **only** as:

```text
bugs|features/     →  in-progress/     (start work + lease)
in-progress/       →  review-needed/   (Done when holds — required agent finish)
review-needed/     →  completed/       (HUMAN ONLY via /review Approve)
review-needed/     →  in-progress/     (human requested changes; agent resumes)
review-needed/     →  bugs|features/   (release/return; also /review Needs Work)
bugs|features|in-progress/  →  ambiguous/   (half-baked)
bugs|features|in-progress/  →  blocked/     (cannot fix now)
in-progress/       →  bugs|features/   (release for others)
ambiguous|blocked/ →  bugs|features/   (return when unblocked)
```

**Preserve basename** on every move (including `.local.md`). Agents must **never**
drop or add the `.local` suffix; only a human may rename for privacy/tracking.

Agents must **never** promote drafts except via **`/draft --promote`**, move work
into `drafts/`, move **`in-progress/` → `completed/`** (forbidden — always finish
to `review-needed/`), move `review-needed/` → `completed/` except under a
human-confirmed **`/review` Approve**, or touch another agent's `in-progress/` plan.

## Priority (when no target is given)

Bare `/work` picks from **ready lanes only** (`bugs/`, `features/`). It never
scans `in-progress/` to resume or reclaim — resume is an explicit named target.

1. All of `.plans/bugs/*.md` before any feature.
2. Within each lane, order by header `Priority: P1 | P2 | P3` (default **P2** if
   absent): P1 → P2 → P3; then `Value: high | medium | low` (default **medium**):
   high → medium → low; then oldest first (mtime), ties by filename.
3. Among ready plans, keep only **model-fit** plans (next section) — unless
   `--no-fit-check` is set.
4. **Skip plans with unmet `Depends on`** — do not start; report blockers.
5. **Skip plans assigned to a human.** An `- **Assignee:**` header whose value
   is a person's name, username, email, or `human` means a person completes it —
   never bare-pick or claim it, whatever its fit. (Absent, `ai`, `agent`, or
   `unassigned` = agent-eligible.) You **may** still read it and edit its body to
   add a status/progress note or answer a question, and commit that; you just
   never move it to `in-progress/`/`review-needed/`/`completed/`. `plan_fit.py`
   and the pickers already filter these out.
6. Skip `drafts/`, `completed/`, `ambiguous/`, `blocked/`, `review-needed/`,
   **all** `in-progress/` (owned by whoever claimed it), and `README.md`.

**Less-reliable / small models:** don't reason about lanes by hand — run the
deterministic picker, which only ever returns ready work and claims it atomically
(move + lease together):

```bash
python scripts/plan_fit.py --tier <yours> --effort <current>   # what fits me, and why
python scripts/plan_select.py --next            # print the next ready plan
python scripts/plan_select.py --next --claim --agent-id <id>   # + claim it
```

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

Tiers: `small` | `mid` | `reasoner` | `frontier` (see `.anchor/templates/plan.md`,
`.anchor/ANCHOR.md` routing, `.anchor/model-fitness.md`). Absent field → treat as
**mid** (any solid executor; not a free pass for wasteful frontier pickup of
obviously trivial work after you load the Goal) — a **ceiling hint, not a
floor**: it does not exclude `small`.

### Know yourself

Before selecting a plan, identify **all three**:

1. **Model name + fit tier** (product name if known; else closest tier). Use
   `.anchor/model-fitness.md` and the plan-template table. **Name and catalog
   tier win over vibes** — e.g. **Grok 4.5 is mid-class** for Preferred matching
   (listed under `mid`; named “Grok 4.5” is a good hit). Temporary-coordinator
   eligibility is not the same as “treat every `mid` plan as overqualified.”
2. **Cost posture** when the product supports it: current **reasoning effort** /
   thinking mode if known (`low` | `medium` | `high` | …). **High effort on a
   mid-class model is a cost dial, not a tier promotion** — it does not by
   itself make you overqualified for `mid` Preferred plans.
3. **Cheaper capacity** on this host/fleet (next subsection) — required whenever
   fit is poor **or** the top ready work is `small`/`mid` while this session is
   expensive (true higher tier, or mid model stuck on high effort).

### Let the script decide fit

Do not judge fit by reading plan headers — it is a mechanical rule, and models
get it wrong in both directions. Ask:

```bash
python scripts/plan_fit.py --tier <yours> [--model <name>] [--effort <current>]
```

One `take:`/`skip:` line per ready plan with the reason, plus an effort note when
your dial is off for that plan's tier (`--endpoint <name>` instead of `--tier`
for fleet workers; `--json` for tooling). It is read-only — claim with
`plan_select.py --next --claim` once you have picked. Its verdicts *are* the
rules below; if your judgment disagrees with it, the script is right.

### Cheaper capacity probe

Before hard-skipping overqualified work, and when about to burn a high-cost
session on `small`/`mid` Preferred, probe for a **lesser configured executor**:

1. **Fleet registry:** `scripts/endpoints.yaml` (or project registry). Map
   registry tiers → fit tiers: `swarm`→`small`,
   `executor`|`executor-heavy`|`detached`→`mid`, `reasoner`→`reasoner`,
   `frontier`→`frontier`. Keep endpoints whose mapped tier is **≤** the plan’s
   highest Preferred tier (or named models that match Preferred).
2. **Reachability:** listed ≠ live. A cheap connect/list (or prior known-down
   note) is enough; unreachable workers do not count as delegation targets.
3. **Product-local models:** smaller models registered in this harness (custom
   OpenAI-compatible endpoints, local NIM, etc.).
4. **Project conventions:** model-priority / Preferred orchestrator in
   `.anchor/conventions.md` or `ANCHOR-CONVENTIONS.md` when present.

**If a cheaper reachable worker fits the plan:** do **not** claim it on bare
`/work` in this expensive session. Print one line with the dispatch path, e.g.:

```text
python scripts/work_once.py --once --endpoint <name> --registry scripts/endpoints.yaml
```

(or “open a session on \<model\>”). Leave the plan unclaimed for that worker.

**If none are configured or reachable:** you are the available executor — do
**not** permanent-refuse mid work. Apply **same-model cost right-size** (next)
and/or wait for the operator to paste the suggested command.

### Reasoning effort / same-model cost right-size

When no cheaper worker is available (or the operator already chose this model
to clear the backlog), map the plan’s Preferred tier → a suggested effort and
**emit a pasteable platform command**. Never silently change product settings
yourself if only the human/UI can.

| Preferred (use highest listed tier) | Suggested effort on reasoning models |
|-------------------------------------|--------------------------------------|
| `small` | `low` (or `minimal` / `none` if the product offers them) |
| `mid` | `low` or `medium` |
| `reasoner` | `high` |
| `frontier` | `high` or `xhigh` as needed |

**Pasteable commands (use what this product documents):**

| Product | Lower cost for `small`/`mid` work | Raise for `reasoner`+ work |
|---------|-----------------------------------|----------------------------|
| **Grok Build (TUI)** | `/effort low` — or `/model <id> low` | `/effort high` |
| **Grok CLI / headless** | `--effort low` / `--reasoning-effort low` | `--effort high` |
| **API (Grok-class)** | `reasoning_effort: "low"` | `"high"` |
| **Nemotron / Qwen3 hybrid** | thinking **off** for bulk execute | thinking **on** for plan/critic |
| **No effort dial (e.g. some Claude sessions)** | switch session to Haiku / local executor | switch up a tier |

Effort vs fit:

- **Good fit + high effort on `small`/`mid` Preferred:** print the lower-effort
  command in one line, then **execute** (or pause one turn only if the operator
  must apply a slash command first — say which). Do **not** reclassify as
  overqualified solely because effort is high.
- **True overqualified** (clearly higher *tier* than all Preferred, e.g. Fable
  on `small`/`mid` only) **+ no cheaper worker + operator needs progress:**
  suggest `/work --no-fit-check` **and** the effort/model command above; stop
  unless they insist or already authorized “do it on this model.” Use Rule 2's
  terse skip format — an expensive session declining cheap work should cost the
  operator three lines, not three paragraphs.
- **Underqualified:** still skip. Suggest a stronger session/model — cranking
  effort up is not a substitute when Preferred needs reasoner/frontier you are
  not.

### Matching

A plan is a **good fit** if you match any listed name (fuzzy: "Sonnet",
"Sonnet-class", "Claude Sonnet 5", "Grok 4.5") or your tier is among the listed
tiers / clearly in the same class.

| Fit | Meaning | Bare `/work` |
|-----|---------|--------------|
| **good** | You are in Preferred models / same class | Eligible (apply effort right-size if needed) |
| **overqualified** | You are a clearly higher **tier** than all preferred (e.g. Fable/frontier on `small`/`mid` only) | **Skip** (Rule 2 format) if cheaper capacity exists; else probe + effort/`--no-fit-check` suggestions |
| **underqualified** | Every **tier** the plan lists is above yours (e.g. it lists `reasoner`/`frontier` only and you are `mid`) | **Skip** (Rule 2 format) — leave for stronger models |
| **unknown** | No **Preferred models** line, or a list with no tier and no name you match | **Eligible** — claim after a one-line fit note (this is what `work_once.py` does) |

### Do not under-rate yourself (the floor is a tier, not a vibe)

Symmetric to the cheaper-capacity probe above: an unnecessary skip stalls the
backlog exactly the way a wasteful frontier pickup burns credits. Before you
classify yourself **underqualified**, check all four:

1. **Only listed tiers set the floor.** `small | mid | reasoner | frontier` are
   the gate. Product **names** in the list are *extra* good-fit hits, never a
   raised floor — `**Preferred models:** mid, Claude Sonnet 5, Grok 4.5` is a
   **good** fit for any `mid` worker, named or not.
2. **Names-only lists do not gate.** A list of only names, none of them you, is
   **unknown** — eligible after a one-line fit note. (`classify_fit` in
   `scripts/plan_select.py` returns `unknown` here; a session that skips is
   stricter than the harness, and wrong.)
3. **A missing Preferred line does not gate.** Unlabeled work is unlabeled, not
   reserved for a higher tier.
4. **A hard step inside a good-fit plan is not a fit failure.** Difficulty you
   find *after* claiming is a per-step **Route to** / `## Escalation triggers`
   question, or a return-to-ready hand-back — not grounds to refuse the claim.
   Claim it, run the steps you own, escalate the step.

Escalate on your **weak column** (`.anchor/model-fitness.md`) and on
orchestration-class work — not on the mere existence of a stronger model. "A
better model could do this" is true of nearly every plan and is not a fit
verdict.

### Rules

1. **Bare `/work`:** never start a plan that is overqualified or underqualified
   for you. Pick the highest-priority **good** fit instead. On good-fit
   `small`/`mid` work, still run the effort right-size note when the session is
   on high reasoning cost.
2. **All ready plans are poor fit — keep the refusal short.** A skip is a
   one-line verdict plus at most two `→` lines, then **stop**. Do not silently
   burn the wrong tier — and do not pad the refusal either:

   ```text
   skip: features/<slug> — underqualified (Preferred: reasoner; you: Sonnet 5/mid)
   → python scripts/work_once.py --once --endpoint h100-nemotron --registry scripts/endpoints.yaml
   → /work --no-fit-check <slug> to run it here anyway
   ```

   One verdict line **per skipped plan** (a table only past ~4). The probe
   appears *only* as the target in the `→` line — narrating what you checked and
   what was unreachable is noise unless it changes the recommendation or the
   user asks. Do **not** restate the plan's Goal, re-derive the fit rules, or
   justify the tier call at length; the verdict line already says it. No
   `## Result` footer on a turn that did no work.
3. **`--no-fit-check`:** disable Preferred-models / tier filtering for this
   invocation only. Still pick **one** plan by normal lane/Value priority (or
   the named slug/path). Still **state fit in one line** before executing so the
   mismatch is visible — do not pretend the recommendation matched. Still
   suggest effort right-size when applicable. Does **not** mean “run every plan
   in `.plans/`.”
4. **User names slug/path** (without `--no-fit-check`): explicit target overrides
   the skip — but **state the fit mismatch in one line first**, then proceed.
   Include effort/delegate suggestions when the mismatch is cost, not capability.
5. **`--list`:** for each ready plan show path, lane (from directory), Priority,
   Value, Preferred models, and your fit (`good` / `overqualified` / `underqualified` /
   `unknown`). Optionally note suggested effort and any cheaper endpoint that
   would fit. Do not implement. Fit is still computed under `--list` even if
   `--no-fit-check` is also passed (list is informational).
6. Per-step **Route to** still applies after load for mixed-difficulty steps
   (Sonnet default; Opus/reasoner for deep/security; frontier for multi-hour
   autonomy via plan-then-delegate; smaller/local for mechanical rows).
7. **Operator already said use this model efficiently / no local yet:** treat
   as authorization to execute **good-fit** (and explicit-target) work here after
   stating the effort command; still probe so you can recommend local setup
   later (`/local-models`, registry entries) without blocking progress now.

Right-size works both ways: expensive models leave cheap work for cheaper
workers when those exist; when they do not, same-model effort downshift keeps
the queue moving. Small models do not grab architecture plans to "try hard."

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

- If the plan is still under `bugs/` or `features/`, **claim it** — move it to
  `.plans/in-progress/` (same filename) **and record a lease** with your stable
  agent id, together. The claim is **required**, not optional: it is what marks
  the plan as yours so other agents skip it. Do this atomically with the picker
  (`python scripts/plan_select.py --next --claim --agent-id <id>`, or
  `work_once.py --once --agent-id <id>`), which writes the lease under
  `.plans/.leases/` as it moves the file. A bare `git mv` with no lease leaves the
  plan looking unowned — don't do that.
- **Long-running work:** the lease has a long TTL (24h); a live agent refreshes
  it (`work_once.py --heartbeat in-progress/<slug>.md --agent-id <id>`) so its
  plan never looks orphaned. Only a lease left untouched past the TTL is
  reclaimable, and only via an explicit `--recover`.
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

1. **Always** `git mv` the file from `in-progress/` to `.plans/review-needed/`
   (create the dir if needed). Drop any lease for the plan. That move means
   *agent asserts Done when* — it is **not** final archive. Do **not** set a
   Status field. Do **not** move to `completed/` from `/work` (no optional
   self-certify path).
2. Tell the human to run **`/review`** (or `/review <slug>`) for sign-off: AI
   critic + survey — Approve → `completed/`, Needs Work → `bugs|features/`,
   Skip. Never perform `review-needed/` → `completed/` yourself outside a
   human-confirmed `/review` Approve.
3. Session footer: `## Result`, `## How to verify`, `## Deferred / concerns`,
   including the new path under `review-needed/` and a one-line “run `/review`”
   reminder.

**If the user stops mid-plan:** leave the file in **`in-progress/`** with a
brief `## Progress` note. Do **not** move to `completed/` or `review-needed/`.
Other agents must ignore it.

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
   .plans/ambiguous .plans/blocked .plans/review-needed \
   .plans/drafts .plans/completed 2>/dev/null
```
