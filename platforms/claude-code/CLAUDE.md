# CLAUDE.md — Anchor discipline for Claude Code

<!-- Drop this into any repo (or merge into an existing CLAUDE.md). It implements .anchor/ANCHOR.md
     for Claude Code, including the post-July-2026 model economics: Fable 5 is credit-metered,
     so it plans and reviews; Sonnet/Opus and local models execute. -->

## Model routing (cost discipline)

- Default model for execution work: **Sonnet**. Do not use the largest model for boilerplate, CSS, renames, or single-file tasks.
- Use **Opus** for: deep single-problem reasoning, architecture decisions, security-adjacent work (route there directly; don't burn Fable credits on tasks the classifier will reroute anyway).
- Use **Fable/frontier** only for: multi-hour autonomous work, large migrations, multi-service debugging — and prefer using it via plan-then-delegate (below) rather than end-to-end.
- Right-size before starting: if a request looks like boilerplate/formatting/a rename/a single well-specified function, say so and ask whether to proceed at the current tier or drop to Sonnet/a local fleet model instead of defaulting up.

## Plan-then-delegate (the orchestrator pattern)

For any task exceeding one session or one file:

1. **Plan mode first.** Enter plan mode; produce a plan following `.anchor/templates/plan.md`: numbered steps, files touched per step, verification per step, model tier per step.
2. **Delegate execution to subagents.** Each plan step becomes a Task-tool subagent with a self-contained spec per `.anchor/templates/task-spec.md`. Subagents get ONLY their spec's context — never the whole conversation.
3. **Verify each step with tooling.** Run the step's verification command before starting the next step. A subagent's success claim is not verification.
4. **Review pass at the end.** Fresh context (new subagent or the frontier model): review the merged diff against the plan using `.anchor/templates/review.md`.

## Prompt tuning before expensive runs

Before dispatching any frontier-model run, rewrite the task on a cheap model into the task-spec template (goal, files in scope, acceptance criteria, definition of done). Three attempts on credits is the silent budget killer; one tuned attempt is the fix. `scripts/prompt_tuner.py` automates this.

## Standing rules (apply to every model tier)

- Fit check first: if the pending task lands in the current model's weak column (see `.anchor/model-fitness.md` and the model-routing section of `.anchor/conventions.md`, both scaffolded into the project), open with `SUGGEST-ESCALATE: <model> — <reason>` and stop; proceed only if the user insists.
- Restate goal + acceptance criteria before acting; ask one clarifying question if ambiguous, then stop.
- One step at a time; unrelated findings go in a `## Deferred` note, never fixed opportunistically.
- Never claim success — state how to verify, then run the verification.
- Two failed fix attempts on the same error → stop, summarize attempts + hypothesis, escalate a tier.
- **Usage limits are a scheduling problem, not a failure:** on a session/weekly cap or quota (429, `insufficient_quota`, "limit reached", a forced tier downgrade), checkpoint state, then **reroute** to the next model in priority order *that clears the task's fitness floor*, else **wait** for a near reset, else **stop and report**. Never finish work on a silently downgraded tier, and never narrow scope or weaken tests to beat a cap. See `.anchor/capacity-routing.md`.
- Touch only files named in the current task spec.
- End every task with: `## Result`, `## How to verify`, `## Deferred / concerns`.
- SOLID by default; use the project's idiomatic composition mechanism (check `.anchor/conventions.md`) over deep inheritance; no dead code, no spaghetti control flow.
- **Docs describe current state, not plans:** README / `docs/` / CHANGELOG / blog / release notes cover **shipped** code and public contracts only. Never document the **contents** of `.plans/` (drafts, backlog, unfinished acceptance) as product docs or roadmap. When plan work ships, document the code — not the plan file. Documenting the `.plans/` **workflow** itself is fine when that is a shipped feature.
- **Before any `git commit`:** run **`/commit-prep`** (prep only: tests, CHANGELOG, blog-if-warranted). Do not skip prep for “small” changes. After gates are **green**, if plan work is complete (or the user asked to land the work), **stage + commit on the feature branch** (worktree preferred); optional feature-branch push; never commit on main/dev; never auto-merge.

## Hooks & automation suggestions

- PostToolUse hook on Edit/Write: run the project's linter; feed failures back verbatim.
- Pre-commit: run **`/commit-prep`**, then the step's definition-of-done command; block commit on failure.
- Use git worktrees for parallel subagent tasks to keep diffs scoped and reviewable.

## MCP

Connect `mcp/anchor-prompts` (templates + tune/critique tools) and `mcp/model-fleet` (delegate steps to local/NIM endpoints) from this repo. Prefer delegating mechanical steps to the local fleet before spending plan-limit tokens.

## /draft

**Planning mode** on **`.plans/drafts/`**: create/refine, `--list`, load existing
slug for discussion (`--load` or slug that exists), optional `--local` →
`*.local.md`. **Promote** with `/draft --promote <slug>` (infer `bugs/` vs
`features/` from the plan; user-authorized). Do not implement product code; do
not promote from `/work`. Command: `.claude/commands/draft.md`.

## /work

Execute the next (or named) ready plan from **`.plans/`** (dotdir). Contract:
resume own `in-progress/` first; bugs before features; honor **Preferred models**
and **Depends on** (skip unmet deps); never execute `drafts/` / `completed/` /
`ambiguous/` / `blocked/`; ignore foreign `in-progress/`; claim ready →
`in-progress/`; park half-baked → `ambiguous/` or stuck → `blocked/`; finish
`in-progress/` → `completed/`. Do not promote drafts from `/work` (use
`/draft --promote`). If Preferred orchestrator is unset, frontier/near-frontier
may act as temporary coordinator (`TEMPORARY-COORDINATOR:`). On Git projects: **worktree per agent**
(`scripts/worktree_for_agent.py ensure --agent-id … --slug …`); feature-branch
from **`dev`**/`develop` (**create `dev` from main/master if missing**);
**`/commit-prep` before commit**; never auto-merge. Command:
`.claude/commands/work.md`.

## /fleet-watch

Configure durable plan pollers for a project: `/fleet-watch` (CWD) or
`/fleet-watch other-app`. Watchers run a work-style claim/execute loop in the
background. Command: `.claude/commands/fleet-watch.md`. Prefer the skill over raw CLI.

## /install-anchor

Ensure the **`anchor` CLI** is on `PATH` safely (user-local symlink to
`bin/anchor`, no sudo by default). Command: `.claude/commands/install-anchor.md`.

## /anchor

Locate the local Anchor checkout and **conform this project** (CWD/git root by
default): `anchor --check` / `--upgrade` when a manifest exists, or
conflict-aware scaffold. Scaffolded scaffolded skill (source:
`platforms/claude-code/commands/anchor.md`) — different defaults from the
Anchor base skill (which requires a foreign project path). Command:
`.claude/commands/anchor.md`.

## /local-models

Probe this machine for **lean local models**, recommend fits, install links, and
optional reconfigure draft. Scaffolded into **projects** (not part of
the Anchor base skill set). Command: `.claude/commands/local-models.md`
(source: `platforms/claude-code/commands/`). Uses `scripts/fit_device.py --probe`
when available.

## /commit-prep

**Required before any `git commit`.** Run `/commit-prep` (command:
`.claude/commands/commit-prep.md`): tests → CHANGELOG → blog-if-warranted.
**Prep only** — does not commit. After a green prep, commit policy is under
**`/work`** / standing rules (feature branch + worktree; never merge to `dev`/`main`).

## /config

`/config` lives in the **Anchor checkout**, not in this project — it is deliberately
not scaffolded. It sets *your* operator defaults (platform(s)/fleet tooling, model
priority, preferred orchestrator) by running `./config.sh`, and there is nothing for
it to act on inside a scaffolded tree. Run it from the Anchor checkout
(`.claude/commands/config.md` there), then scaffold with `anchor <project-dir>`.
To change just this project's orchestrator: `anchor <dir> --set-orchestrator <token>`.
Help: https://carefreeinv.com/anchor
