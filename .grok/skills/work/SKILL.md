---
name: work
description: >
  Execute the next (or named) ready plan from ./.plans. Use when the user runs
  /work, asks to work the backlog, pick up a plan, continue planned work, or
  execute a plan under .plans/bugs, features, or your own in-progress.
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

**Path is authoritative.** A plan’s lane and lifecycle are determined only by
which directory it lives in — never by `Lane:` or `Status:` fields inside the
file. Ignore those fields if present; do not write them.

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

| Path | Read? | Execute? | Notes |
|------|-------|----------|-------|
| `.plans/bugs/` | yes | **yes** (pick → move to in-progress) | highest priority ready |
| `.plans/features/` | yes | **yes** (after all bugs) | ready |
| `.plans/in-progress/` | yes | **only if you moved it there** | claimed; others **ignore** |
| `.plans/ambiguous/` | yes | **no** | half-baked; agent may park here |
| `.plans/blocked/` | yes | **no** | cannot fix now; agent may park here |
| `.plans/review-needed/` | yes | **no** | agent believes `Done when` holds, awaiting human sign-off; human runs **`/review`** (AI + survey): Approve merges feature→dev then → `completed/`; Needs Work → `bugs|features/`; empty queue may Promote dev→main |
| `.plans/drafts/` | yes (edit plan only) | **no** | |
| `.plans/completed/` | yes (history) | **no** | |

**Never** implement from `drafts/`, `completed/`, `ambiguous/`, `blocked/`, or
`review-needed/`. **Bare `/work` never scans `in-progress/`** — it picks only
ready lanes. Every in-progress plan is **owned** via a **required lease** under
`.plans/.leases/`; **ignore** every in-progress plan you do not own, and never
silently reclaim a foreign, unleased, or expired-lease one. Resume your own work
by explicit named target (or `work_once.py --recover` for an expired lease).
If the user names a draft: refuse execution; offer **edit-only**. Do **not** promote it.

### Agent move rule (hard)

Agents may relocate plan files **only** as:

```text
bugs|features/     →  in-progress/     (start work + lease)
in-progress/       →  review-needed/   (Done when holds — default agent finish)
in-progress/       →  completed/       (ONLY after the operator answers "merge to dev
                                        now" at culmination AND the scoped-merge gate
                                        passes — see §6. Never self-certified.)
review-needed/     →  completed/       (HUMAN ONLY via /review Approve)
review-needed/     →  in-progress/     (human requested changes; agent resumes)
review-needed/     →  bugs|features/   (release/return; also /review Needs Work)
bugs|features|in-progress/  →  ambiguous/   (half-baked / underspecified)
bugs|features|in-progress/  →  blocked/     (cannot fix now)
in-progress/       →  bugs|features/   (release claim for other agents)
ambiguous|blocked/ →  bugs|features/   (return when clarified / unblocked)
```

**Preserve basename** on every move (including `.local.md`). Agents must **never**
drop or add the `.local` suffix; only a human may rename for privacy/tracking.

Agents must **never** promote drafts (use **`/draft --promote`** instead), move
work into `drafts/`, move `review-needed/` → `completed/` except under a
human-confirmed **`/review` Approve**, or touch another agent’s `in-progress/` plan.

`in-progress/` → `completed/` is **not** a self-certify path: it happens only as the
tail of a merge the **operator** authorized in-session (§6). Unattended runs —
`work_once.py`, fleet workers, the coordinator MCP — never ask, never merge, and
always finish to `review-needed/`.

## Priority (when no target is given)

Bare `/work` picks from **ready lanes only** (`bugs/`, `features/`) — it never
scans `in-progress/` to resume or reclaim. Resume is an explicit named target.

1. All of `.plans/bugs/*.md` before any feature.
2. Within each lane, order by header `Priority: P1 | P2 | P3` (default **P2** if
   absent): P1 → P2 → P3; then `Value: high | medium | low` (default **medium**):
   high → medium → low; then oldest first (mtime), ties by filename.
3. Among ready plans, keep only **model-fit** plans (next section) — unless
   `--no-fit-check` is set.
4. **Skip plans with unmet `Depends on`** (dependency still open / not completed).
   Do not start them; pick another plan or stop and report unmet slugs. Override
   only if the user explicitly insists (and state the risk).
5. **Skip plans assigned to a human.** An `- **Assignee:**` header whose value
   is a person's name, username, email, or `human` means a person completes it —
   never bare-pick or claim it, whatever its fit. (Absent, `ai`, `agent`, or
   `unassigned` = agent-eligible.) You **may** still read it and edit its body to
   add a status/progress note or answer a question, and commit that; you just
   never move it to `in-progress/`/`review-needed/`/`completed/`. `plan_fit.py`
   and the pickers already filter these out.
6. Skip `drafts/`, `completed/`, `ambiguous/`, `blocked/`, `review-needed/`,
   **all** `in-progress/`, and `README.md`.

**Less-reliable / small models:** run the deterministic tools instead of
reasoning about lanes or fit — `python scripts/plan_fit.py --tier <yours>
[--effort <current>]` says what fits you and why (read-only), and
`python scripts/plan_select.py --next [--claim --agent-id <id>]` returns ready
work and claims it atomically (move + lease).

If multiple plans share the top priority, **just pick the first in sorted order**
(Priority → Value → oldest → filename) and start — this is the default; do **not**
print a menu or ask which to run. Name the other tied plans in one line so the
user can redirect if they want a different one. Only pause to ask when the user
**explicitly** asks to choose (e.g. “let me pick”, “which should I run?”).

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
   thinking mode if known (`low` | `medium` | `high` | `xhigh` | …). **Grok family
   (4.5/4.6):** reported effort sets **effective fit tier** (`low`→mid, `medium`/`high`→reasoner, `xhigh`→frontier; **unknown effort → mid**). Report
   `Grok 4.6 @ high → effective frontier` (or 4.5) before Preferred matching.
   **Non-Grok products:** high effort remains a **cost dial only**, not a tier
   promotion.
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
| **Grok Build (TUI)** | `/effort low` — or `/model <id> low` | `/effort high` or `/effort xhigh` (4.6) |
| **Grok CLI / headless** | `--effort low` / `--reasoning-effort low` | `--effort high` |
| **API (Grok-class)** | `reasoning_effort: "low"` | `"high"` |
| **Nemotron / Qwen3 hybrid** | thinking **off** for bulk execute | thinking **on** for plan/critic |
| **No effort dial (e.g. some Claude sessions)** | switch session to Haiku / local executor | switch up a tier |

Effort vs fit:

- **Grok + reported effort:** use **effective tier** for good/under/overqualified
  (e.g. Grok @ high is effective reasoner; @ xhigh is effective frontier — overqualified for Preferred `small`
  only; Grok @ low is mid — underqualified for Preferred `reasoner` only). Pass
  `--effort` to `plan_fit` / `work_once` when known.
- **Good fit + wasteful effort on `small`/`mid` Preferred:** print the lower-effort
  command (`/effort low`) in one line, then **execute** (or pause one turn if the
  operator must apply a slash command first). On **non-Grok** models, do **not**
  reclassify as overqualified solely because effort is high.
- **True overqualified** (effective tier above all Preferred, e.g. Fable or
  Grok@xhigh or Fable on `small`/`mid` only) **+ no cheaper worker + operator needs progress:**
  suggest lower effort / cheaper endpoint **and** `/work --no-fit-check` if needed;
  stop unless they insist. Use Rule 2's terse skip format.
- **Underqualified:** still skip. On Grok, suggest **raising** `/effort` (medium /
  high / xhigh on 4.6) when the map would make you eligible; on other products,
  cranking effort is not a substitute for a stronger model.

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
6. Per-step **Route to** still applies after load for mixed-difficulty steps.
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
  Anchor’s formalize-plans workflow or create the layout if the user asks.
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
- Slug: find unique `{slug}.md` or `{slug}.local.md` under ready lanes; if zero
  or many matches, report and stop or disambiguate.

### 3. Load the plan

- Read the full markdown file.
- Restate **Goal**, **Preferred models**, **Depends on**, and **Done when** in ≤10 lines.
- **Dependencies:** for each Depends-on slug, verify it is satisfied (under
  `completed/`, or git history of `completed/`, and **not** still open in another
  lane). If unmet → **do not execute**; report which deps block and stop (or pick
  another plan). Optional sys checks: `ls .plans/*/<slug>*`, `git log -- .plans/completed/`.
- Do **not** rewrite the plan unless a step is impossible (then stop and say why).
- If a `## Progress` checklist exists, resume from its first unchecked
  (`- [ ]`) bullet — that is what "first incomplete step" means concretely.

### 4. Mark in progress

- If the plan is still under `bugs/` or `features/`, **claim it** — move it to
  `.plans/in-progress/` (same filename) **and record a lease** with your stable
  agent id, together (required, not optional — the lease is what marks the plan
  yours). Do it atomically with `plan_select.py --next --claim --agent-id <id>`
  or `work_once.py --once --agent-id <id>`; a bare `git mv` with no lease leaves
  the plan looking unowned. Long jobs: refresh with `work_once.py --heartbeat
  in-progress/<slug>.md --agent-id <id>` (24h TTL; expired → explicit `--recover`).
- Optionally add or update a brief `## Progress` note. Do **not** write
  `Status:` or `Lane:` fields.

### 5. Execute

- Walk **## Steps** in order (table rows or numbered list).
- For each step: do the work; run its **Verify by** command when present.
- One step at a time; no opportunistic drive-bys outside the plan’s file scope.
- If the plan has a `## Progress` checklist, check off (`- [x]`) that step's
  bullet once its Verify by passes. Advisory only — never required, never a
  gate; skip silently if the plan predates the convention.
- Two failed fix attempts on the same error → stop; summarize attempts +
  hypothesis; escalate (do not thrash).
- Honor per-step **Route to** (fleet offload / escalate / downgrade) when present.

### 6. Complete or pause

**Done when** all checklist items hold and verifications pass:

1. If the plan has a `## Progress` checklist, check off `Done when holds`
   (and confirm every Step bullet is checked).
2. Run **`/commit-prep`**, then commit on `feature/<slug>`. **Record the SHA** —
   the merge gate needs it.
3. Ask the **culmination question**, then follow the answer.
4. Session footer: `## Result`, `## How to verify`, `## Deferred / concerns`,
   including the plan's new path, the handoff outcome, and the
   `pending_merges.py --brief` line.

#### The culmination question

Ask **once**, only when **all** hold: `/commit-prep` green · the feature-branch
commit succeeded · the session is **interactive** · the project uses Git. Otherwise
skip it and finish to `review-needed/` with a one-line note saying why.

```text
Plan '<slug>' is done and committed on feature/<slug>. What now?
  1. Review it now (default) — /review does an AI critic pass, then you sign off
  2. Merge to dev now — I checked the work; land it without a review cycle
  3. Hold for testing — leave the branch and worktree; I'll come back to it
```

| Answer | What `/work` does |
|--------|-------------------|
| **1. Review it now** | Plan → `review-needed/`; hand off to `/review <slug>` |
| **2. Merge to `dev` now** | Run the scoped-merge gate. **Pass** → merge, plan → `completed/` with a `## Handoff` note. **Any failure** → fall back to answer 1, saying which check refused |
| **3. Hold for testing** | Plan → `review-needed/` with a `## Handoff` hold note; branch + worktree left intact |

Never infer the answer — not from an earlier “yes”, a flag, or a config default.
No answer → answer 1.

#### Scoped-merge gate (answer 2 only)

All six, else refuse and fall back to `/review`: **provenance** (branch HEAD is the
commit this run made) · **clean tree** · **file scope** (every path named
**anywhere in the range history** `base..head` — not only the net tree-to-tree
diff — is inside this run's touched set: plan `Touches` + the plan's own lane
move + what `/commit-prep` reported; add-then-delete still counts) · **mergeable**
(ff preferred, else conflict-free) · **target is integration only**
(`dev`/`develop`; mainline aborts the path) · **human answer in this session**.

```bash
python scripts/merge_feature.py --root <checkout> --slug <slug> \
  --touched <file-with-one-path-per-line> --expect-head <sha> --dry-run
# 0 would merge · 3 scope · 4 precondition · 5 conflict · 2 git error
```

`--expect-head` is **required** (provenance must hold). Point `--root` at a checkout
where the integration branch is **free** — git will not check out a branch live in
another worktree, so from `var/worktrees/<agent>` run it against the main checkout;
the gate detects the conflict up front and names the path to use.

Drop `--dry-run` to land it. Never pass the operator's answer to the helper — check
6 is yours to hold. **Rejected by design:** landing only the in-scope paths when the
scope check fails; that fabricates a commit matching no branch state.

#### `## Handoff` note formats

Appended to the plan body (never a `Status:`/`Lane:` field):

```markdown
## Handoff
merged to dev by /work 2026-08-01 — no /review sign-off
```
```markdown
## Handoff
hold — waiting on staging data — 2026-08-01
```
```markdown
## Handoff
handed to /review 2026-08-01
```

#### Answers 1 and 3

`git mv` the plan from `in-progress/` to `.plans/review-needed/` (create if needed)
and drop its lease — *agent asserts Done when*, not a final archive. Tell the human
to run **`/review`**: Approve merges `feature/<slug>` → dev then → `completed/`;
Needs Work → `bugs|features/`; Skip. Never move `review-needed/` → `completed/`
yourself.

**If the user stops mid-plan:** leave the file in **`in-progress/`** with a
brief `## Progress` note. If a checklist is present, leave unfinished bullets
`- [ ]` — do **not** check off a step you didn't actually finish; an
optional freeform line below the checklist may note why/next-action. Do
**not** move to `completed/` or `review-needed/`. Other agents must ignore it.

**If the plan is half-baked:** move to `.plans/ambiguous/` and note what is
missing (acceptance criteria, scope, etc.).

**If you cannot fix the issue:** either move to `.plans/blocked/` (out of the
ready queue) **or** return it to `bugs/`|`features/` (release for another agent).
Prefer `blocked/` when the plan should not be re-picked until a human clears the
blocker; prefer return-to-ready when another tier/agent might succeed.

## Output footer

End every substantive `/work` turn with:

```text
## Result
## How to verify
## Deferred / concerns
```

On a turn that finished a plan, `## Result` also carries the handoff outcome
(reviewed / merged to `dev` / held) and the one-line unmerged summary:

```bash
python scripts/pending_merges.py --root <repo> --brief
# handoff: 3 branch(es) ahead of dev · 1 completed awaiting merge · 1 held
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
2. Feature branch `feature/<slug>` **in your worktree**. `/work` may land it on
   **integration only** (`dev`/`develop`), and only through §6's culmination
   question + scoped-merge gate. `/work` **never** merges to `main`/`master` and
   never merges on its own initiative — mainline is reached solely through
   `/review`'s empty-queue **Promote**.
3. When plan work is complete (Done when holds / finishing `/work`):
   - Run **`/commit-prep`** first (**prep only** — tests, CHANGELOG, blog).
   - If gates are **green**: **stage + commit on the feature branch** (HEREDOC
     message). Optional `git push -u origin HEAD` when a remote feature branch is
     expected. Report branch + commit SHA — §6's provenance check needs it.
   - If gates are **red**: do not commit; fix or stop per stop rules. No commit
     means no culmination question.
   - **Never** commit on `main`/`master`/`dev`/`develop`. Merging happens only as
     §6 describes: operator asked, operator answered, gate passed. Unattended runs
     hand off to **`/review`** instead.

## Out of scope

- Creating new plans (use **`/draft`** → `.plans/drafts/`; optional `--local`)
- **Promoting** drafts → ready (use **`/draft --promote <slug>`**; never from `/work`)
- Executing every ready plan in one shot unless the user explicitly asks to
  continue to the next after finishing one
- Running `git commit` **without** `/commit-prep`, or committing when the user did
  not ask and the plan does not require it
- **Merging on your own initiative** — the culmination merge needs the operator's
  in-session answer *and* a passing scoped-merge gate. Unattended paths
  (`work_once.py`, fleet workers, the coordinator MCP) never ask and never merge
- Merging to `main`/`master` under any answer — that is `/review`'s promotion survey
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
