# CLAUDE.md — Anchor discipline for Claude Code

<!-- Drop this into any repo (or merge into an existing CLAUDE.md). It implements anchor/ANCHOR.md
     for Claude Code, including the post-July-2026 model economics: Fable 5 is credit-metered,
     so it plans and reviews; Sonnet/Opus and local models execute. -->

## Model routing (cost discipline)

- Default model for execution work: **Sonnet**. Do not use the largest model for boilerplate, CSS, renames, or single-file tasks.
- Use **Opus** for: deep single-problem reasoning, architecture decisions, security-adjacent work (route there directly; don't burn Fable credits on tasks the classifier will reroute anyway).
- Use **Fable/frontier** only for: multi-hour autonomous work, large migrations, multi-service debugging — and prefer using it via plan-then-delegate (below) rather than end-to-end.
- Right-size before starting: if a request looks like boilerplate/formatting/a rename/a single well-specified function, say so and ask whether to proceed at the current tier or drop to Sonnet/a local fleet model instead of defaulting up.

## Plan-then-delegate (the orchestrator pattern)

For any task exceeding one session or one file:

1. **Plan mode first.** Enter plan mode; produce a plan following `anchor/templates/plan.md`: numbered steps, files touched per step, verification per step, model tier per step.
2. **Delegate execution to subagents.** Each plan step becomes a Task-tool subagent with a self-contained spec per `anchor/templates/task-spec.md`. Subagents get ONLY their spec's context — never the whole conversation.
3. **Verify each step with tooling.** Run the step's verification command before starting the next step. A subagent's success claim is not verification.
4. **Review pass at the end.** Fresh context (new subagent or the frontier model): review the merged diff against the plan using `anchor/templates/review.md`.

## Prompt tuning before expensive runs

Before dispatching any frontier-model run, rewrite the task on a cheap model into the task-spec template (goal, files in scope, acceptance criteria, definition of done). Three attempts on credits is the silent budget killer; one tuned attempt is the fix. `scripts/prompt_tuner.py` automates this.

## Standing rules (apply to every model tier)

- Fit check first: if the pending task lands in the current model's weak column (see `anchor/model-fitness.md` and the model-routing section of `ANCHOR-CONVENTIONS.md`, both scaffolded into the project), open with `SUGGEST-ESCALATE: <model> — <reason>` and stop; proceed only if the user insists.
- Restate goal + acceptance criteria before acting; ask one clarifying question if ambiguous, then stop.
- One step at a time; unrelated findings go in a `## Deferred` note, never fixed opportunistically.
- Never claim success — state how to verify, then run the verification.
- Two failed fix attempts on the same error → stop, summarize attempts + hypothesis, escalate a tier.
- Touch only files named in the current task spec.
- End every task with: `## Result`, `## How to verify`, `## Deferred / concerns`.
- SOLID by default; use the project's idiomatic composition mechanism (check `ANCHOR-CONVENTIONS.md`) over deep inheritance; no dead code, no spaghetti control flow.

## Hooks & automation suggestions

- PostToolUse hook on Edit/Write: run the project's linter; feed failures back verbatim.
- Pre-commit: run the step's definition-of-done command; block commit on failure.
- Use git worktrees for parallel subagent tasks to keep diffs scoped and reviewable.

## MCP

Connect `mcp/anchor-prompts` (templates + tune/critique tools) and `mcp/model-fleet` (delegate steps to local/NIM endpoints) from this repo. Prefer delegating mechanical steps to the local fleet before spending plan-limit tokens.

## /config

`.claude/commands/config.md` (scaffolded alongside this file) wires up a `/config`
command: it asks which platform(s)/fleet tooling you want as your default, runs
`./config.sh` non-interactively to save them, and shows the `anchor <project-dir>`
command to scaffold with them. Help: https://carefreeinv.com/anchor
