# The Anchor Doctrine

How to make a lesser model approach problems the way a Mythos-class model does. Every platform file and script in this repo is an implementation of this document.

## What actually separates Mythos-class behavior

Not smarter tokens — better *process*. Six behaviors:

1. **Clarify before acting.** State the goal, constraints, and acceptance criteria in its own words. If ambiguous, ask one precise question rather than guessing.
2. **Plan before executing.** Produce an explicit plan with ordered steps, files/resources in scope, and risks. Never interleave planning and doing.
3. **Decompose ruthlessly.** Break work into tasks that each fit in one short context window and touch one concern. A task that can't be verified independently is decomposed wrong.
4. **Execute one step, then verify.** After each step: does it compile/run/pass? Does it match the spec? Only then proceed.
5. **Self-review as a separate pass.** Re-read the whole result *as a critic*, against the original acceptance criteria, before declaring done.
6. **Know when to stop.** Report blockers honestly instead of hallucinating around them. Two failed attempts at the same fix = stop and escalate.

## Why lesser models fail at this by default

Small models drift: they forget constraints mid-task, conflate planning with doing, declare success without checking, and fill knowledge gaps with plausible fabrication. The fix is never "ask it to think harder." The fix is **externalizing the discipline**:

- **Forced structure** — require fixed output formats (the templates in `templates/`). A model that must fill in an `## Acceptance criteria` section cannot skip thinking about acceptance criteria.
- **One task per context** — never give a small model the whole project. Give it one task spec with exactly the context it needs. Fresh context per task; context rot is real and hits small models hardest.
- **Declared budget + a fixed pre-flight gate** — every task spec carries an explicit `## Budget` (context window, output ceiling, computed by tooling, never guessed) so "does this fit" is a number, not a vibe. Mythos-core rule 13 makes every executor print a fixed 6-item pass/fail block before doing any work — goal, acceptance criteria, files-in-scope, budget, tier fit, task size — so a model that would otherwise plow ahead on a poorly-specified or oversized task has to notice and stop first.
- **Planned continuation instead of context rot** — a task that outgrows its window does not have to fail. Approaching its declared ceiling, the executor emits a **structured handoff** (`templates/handoff.md`: what is done and how it was checked, what remains as ready-to-dispatch sub-specs, decisions made, files touched, open concerns) and the orchestrator respawns a **fresh** context seeded with that handoff — not a longer conversation, which is the thing that rots in the first place. Mythos-core rule 15 makes the handoff mandatory near budget; `scripts/orchestrate.py` decides when one is needed from its own token accounting rather than trusting the model's sense of how much room it has left, rejects remaining work that carries no verify command, and refuses a continuation whose scope grew. The cap is **2 continuations per task** — a task that still does not fit goes back to the planner, because needing a fourth window is a decomposition error, not a large task.
- **External verification** — tooling (not the model) runs tests, linters, and diffs. The model's claim of success is an input to verification, never a substitute. Fleet runs record that pairing in `var/fleet-metrics/outcomes.jsonl` (`scripts/fleet_metrics.py`); aggregate with `python scripts/fitness_report.py` and prefer those rates over vendor claims when updating `model-fitness.md`.
- **Role separation** — the same small model performs better as three sequential roles (planner → executor → critic) than as one conversational blob, because each role gets a clean context and a narrow job. In the orchestrated path the split is harness-enforced, not just prompted: `scripts/roles.py` is the single role→capability map (planner writes only `.plans/**`; executor never writes `.plans/**` or its own spec; critic writes nothing), applied per phase by `scripts/orchestrate.py` and by the project-orchestrator MCP server's role-scoped toolsets (a `--role planner` session never even sees lifecycle tools). Role transitions are explicit, logged orchestrator events — no self-promotion. Single-model sessions with no orchestrator keep the discipline by prompt alone.
- **Escalation paths** — define upfront what gets escalated to a bigger model: ambiguous requirements, architectural decisions, twice-failed tasks, final review. The twice-failed-task path is harness-enforced, not only prompted: `scripts/fleet_metrics.py`'s `should_stop` reads the outcome ledger (not an in-memory attempt count) and refuses a third dispatch to the same model for the same task, so this no longer depends on a flailing model counting its own failures. `scripts/orchestrate.py` consults it before every (re)dispatch — two recorded failures escalate one tier with both failures' evidence attached to the escalated spec; two failures at the top available tier produce a structured human report (rule 6's shape) that the orchestrator writes even if the model never did.

## The orchestrator pattern

From the Fable 5 playbook — pay frontier prices for judgment, not keystrokes:

```
BIG model (or human):   read codebase → write plan → decompose into task specs
SMALL models:           execute each task spec independently, fresh context each
TOOLING:                verify each task (tests, lint, build) before accepting
BIG model (or human):   review the merged result against the plan
```

The expensive model touches the project twice. Everything between runs on cheap/local models. `scripts/orchestrate.py` implements this loop; the `model-fleet` MCP server exposes it to any MCP-capable agent.

## Prompt tuning (always, before expensive or weak runs)

A sloppy prompt costs a frontier model money and costs a small model *correctness*. Before dispatch, rewrite every task with `scripts/prompt_tuner.py` (or the `tune_prompt` MCP tool) into the task-spec template: goal, files in scope, constraints, acceptance criteria, definition of done. Small models are prompt-fragile; this one step buys more quality than any sampling parameter.

## Routing rules of thumb

| Task | Route to |
|---|---|
| Multi-hour autonomous build, large migration | Frontier (Fable-class) — or orchestrated fleet if unavailable |
| Deep single-problem reasoning, architecture | Best available reasoner (Opus-class, Nemotron reasoning-on, R1 distill) |
| Standard features, UI, refactors, reviews | Mid/local (Sonnet-class, Qwen3 32B/30B-A3B) |
| Boilerplate, renames, formatting, summaries | Smallest thing that works (Qwen3 4–8B, Gemma 3 12B) |

80% of a typical build never needed the frontier model. The skill is knowing which 20% does.

### Right-size before you start

Before spending an expensive tier's tokens — **and on every user prompt that sets
or redirects work** — judge fit both ways (detail: `model-fitness.md`):

| Direction | First line | When |
|-----------|------------|------|
| Too hard | `SUGGEST-ESCALATE: <target> — <reason>` | Weak column, orchestration-class, under-tier |
| Too easy | `SUGGEST-DOWNGRADE: <cheaper target> — <reason>` | Clear over-tier (boilerplate, rename, format-only) |
| Good fit | *(silence)* | Proceed — no model pitch |

Stop after a suggest line unless the operator insists. Prefer project model-priority
/ Preferred orchestrator for targets. `scripts/router.py` helps fleet role pick;
interactive agents use the first-line protocol, not silent model swap.


### When the tier you want is rationed

Subscription caps — session, rolling-window, weekly — are a scheduling problem, not a failure. The order is: **reroute** to the next model in priority order *that clears the task's fitness floor*, else **wait** for a near reset, else **stop and report** with a checkpoint. The trap is the middle column of `model-fitness.md`: rerouting boilerplate down a tier is free, rerouting architecture or security work down a tier buys confident wrong answers. Never let a quota reset set the quality bar, and never let a harness downgrade you silently. Full doctrine: `capacity-routing.md`.

## Code quality defaults

Every tier defaults to these regardless of task size — they're cheap to apply and expensive to skip:

- **SOLID principles** by default: single responsibility, small interfaces, depend on abstractions over concretions.
- **Use the language's own composition idiom** instead of deep inheritance or copy-pasted variants:

  | Language/framework | Prefer |
  |---|---|
  | Rust | traits |
  | Python | Protocols (PEP 544) / narrow ABCs |
  | TypeScript, Go, Java, C# | interfaces |
  | Ruby | modules (mixins) |
  | PHP | interfaces/traits |
  | anything else | that language's standard composition mechanism — never a deep inheritance tree |

- **No spaghetti, no dead code.** Unreachable branches, commented-out blocks, and unused abstractions don't get left "just in case" — delete them or don't add them.
- **Technical debt is tracked, not silent.** A shortcut taken under time pressure gets named in the task's `## Deferred / concerns`, not buried.

`scripts/anchor.py` detects a scaffolded project's language/framework from marker files (`composer.json`, `package.json`, `Cargo.toml`, `go.mod`, etc.) and writes the resolved choice — plus its idiom — to **`.anchor/conventions.md`**. When several markers match, a backend language beats co-located `package.json` (common for PHP/Python apps with frontend or Playwright tooling); use `--framework` to force a choice. When detection fails (blank or ambiguous project), it asks, proposing the user's saved `config.sh` language default (if any) as the suggested answer. The same file carries the project's **Preferred orchestrator** (set via `./config.sh --orchestrator`, `anchor --orchestrator` / `--set-orchestrator`, or one-line edit). Lesser models must recommend that orchestrator for planning and fleet coordination instead of attempting it themselves. If Preferred orchestrator is **unset** and no project MCP coordinator is running, a **frontier or near-frontier** model in-session may act as **temporary coordinator** (announce `TEMPORARY-COORDINATOR: …`; inventory plans; propose **Depends on**); mid/small/local models still escalate rather than self-appoint.

## Templates

- `templates/plan.md` — planner output format (header: Value / Slug / Preferred models when using `./.plans`; **path** is lane/status — no in-file Lane/Status)
- `templates/task-spec.md` — the unit of work handed to an executor; its `## Budget` section (context window / output ceiling) is what mythos-core rule 13's pre-flight check reads before work starts
- `templates/handoff.md` — what an executor emits instead of truncating when it approaches its `## Budget`: done (with verification status) / remaining as ready-to-dispatch sub-specs / decisions made / files touched / open concerns. Parsed by `scripts/handoff.py` into the next window's spec (mythos-core rule 15)
- `templates/review.md` — critic pass format
- `templates/verification.md` — machine-checkable done-ness checklist

## Tracked plans (`./.plans`)

### Hard rule: docs describe current state, not plans

**For every project following Anchor:** documentation (README, `docs/`, CHANGELOG,
blog, release notes, public prose) describes the **project as it exists now** —
shipped code and public contracts. **Never** document the **contents** of
`.plans/` (especially `drafts/`, ready backlog, in-progress bodies, unfinished
acceptance items) as product docs or roadmap. When a plan’s work **ships**,
document the code and public contract — not the plan file. **Allowed:**
documenting how the `.plans/` **workflow** works when that is a shipped feature
of the product. **Forbidden:** “coming soon” from plan files; changelog/blog of
unshipped backlog; citing plan slugs/paths as documentation.

In projects that use them, committed work plans live under **`.plans/`** (dotdir —
git-tracked; do not gitignore the whole tree). Optional **local-only** plans use the
`<slug>.local.md` suffix and are ignored via `.plans/.gitignore`. The **`.local`
suffix is sticky:** promote and agent lane moves keep the same basename; agents
must never drop it — only a **human manual rename** (or create with `/draft --shared`)
makes a local plan tracked. **Path is
authoritative:** `bugs/` and `features/` are ready; agents move claimed work to
`in-progress/` (only the claimer continues — others **ignore**); may park to
`ambiguous/` (half-baked) or `blocked/` (cannot fix), or return in-progress to
ready; agents finish claimed work to `review-needed/` (human sign-off via
**`/review`** → `completed/`) — or, when the operator answers `/work`'s end-of-run
culmination question with **merge to `dev` now** and the branch passes the
scoped-merge gate, straight to `completed/` with a `## Handoff` note recording the
skipped review; never execute `drafts/` / `ambiguous/` /
`blocked/` / `review-needed/`. Do not put `Lane:` or `Status:` inside plan files.
**Promotion** from `drafts/` → ready is via explicit **`/draft --promote <slug>`**
(user-authorized; agent infers `bugs/` vs `features/` from the plan; **keeps**
`.local.md` if present) or a human filesystem move — never from `/work` or fleet pullers. Selection order: own
in-progress, then bugs before features; within a lane by **`Priority`**
(`P1`>`P2`>`P3`, default `P2`) then `Value`, then oldest first. Plan headers
include **Priority**, **Preferred models** and **Depends on**.

**Draft with `/draft`** (list / load / create / promote). **Start execution with
`/work`** (Claude: `.claude/commands/work.md`; Grok: `.grok/skills/work/SKILL.md`;
Chat: follow the `/work` section in `CHAT.md`). **Human sign-off with `/review`**
for `review-needed/` plans. Optional: `/work --list`, `/work <slug>`,
`/work --no-fit-check`. Headless pull: `scripts/work_once.py --once --tier mid`
(claim + print path; same fit rules). Multi-tier always-on pollers:
`docs/docs/tooling/fleet-workers.md`. Operator-named:
`scripts/orchestrate.py --plan-file .plans/features/<slug>.md` (refuses `drafts/`
and `completed/`). Process contract: `.plans/README.md` in repos that use the tree.

## System prompts

`system-prompts/mythos-core.md` is the model-agnostic behavioral prompt. Per-model adaptations (chat-template quirks, thinking toggles, context budgets) live alongside it and in `platforms/`.
