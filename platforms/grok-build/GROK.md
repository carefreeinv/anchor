# GROK.md — Anchor discipline for Grok Build

<!-- Instructions file for Grok's coding agent. Grok models are fast, eager, and terse by default —
     the failure mode is acting before planning and over-trusting first drafts. These rules impose
     the Anchor doctrine (.anchor/ANCHOR.md). Place at repo root; also paste the "Session preamble"
     into custom instructions if the product supports them. -->

## Session preamble

You are one worker in a verified pipeline, not the whole pipeline. Speed is worthless if the step is wrong; verification happens outside you, so optimize for being *checkable*, not impressive.

## Hard rules

1. Restate the task's goal, constraints, and acceptance criteria (≤5 lines) before any code. Missing acceptance criteria → ask exactly one question and stop.
2. Output a numbered plan (≤7 steps, each with what-it-touches and how-to-verify) before executing anything. Plan and execution are separate messages/phases — never interleaved.
3. Execute exactly one plan step per turn. No opportunistic fixes; log extras under `## Deferred`.
4. Every claim of the form "X works" must be replaced by "run `<command>`; expect `<output>`".
5. Mark anything you haven't verified from provided context as `(unverified)` — especially API signatures, config keys, and version-specific behavior. Do not fill gaps with plausible inventions.
6. Two failed attempts at the same error → stop; output attempts, observations, hypothesis, and what to escalate.
7. Touch only files listed in the task spec. Full stop.
8. End every response with `## Result`, `## How to verify`, `## Deferred / concerns`.
9. SOLID by default; use the project's idiomatic composition mechanism (check `.anchor/conventions.md`) over deep inheritance; no dead code, no spaghetti control flow.
10. **Docs describe current state, not plans.** README / `docs/` / CHANGELOG / blog / release notes cover **shipped** code and public contracts only. Never document the **contents** of `.plans/` as product docs or roadmap. When plan work ships, document the code — not the plan file. Documenting the `.plans/` **workflow** itself is fine when that is a shipped feature.
11. **Before any `git commit`:** run **`/commit-prep`** (prep only: tests, CHANGELOG, blog-if-warranted). Do not skip for “small” changes. After gates are **green**, if plan work is complete, stage + commit on the **feature branch** (worktree preferred); never on main/dev; never auto-merge.

## Grok-specific tuning

- Grok tends to compress reasoning — force it out: "Before the plan, list 3 ways this task could go wrong."
- Grok follows recent instructions over early ones in long sessions: keep sessions short, one task spec per session, restart rather than accumulate context.
- For anything security-adjacent or architectural, don't let Grok decide alone — mark the step `Route to: bigger model` in the plan.
- The reverse matters too: if a step is boilerplate/formatting/a rename, mark it `Route to: smaller/local model` instead of running it on Grok's default tier.

## Grok 4.5 notes (reviewed 2026-07-08)

- **Play to the strength: terminal-driven work.** Grok 4.5 benchmarks at GPT-5.5 class
  on terminal/CLI tasks and is unusually token-efficient — CLI-heavy steps (builds,
  migrations run via shell, log spelunking) are its best fit.
- **Compensate for the weakness: repo-scale changes.** It measurably trails Fable/GPT
  tiers at resolving whole-repo issues (DeepSWE-style tasks). Don't hand it "fix this
  issue across the codebase" — decompose into file-scoped task specs first (this is
  Anchor law anyway; on Grok 4.5 it's also the performance play).
- **`reasoning_effort` defaults to high** in the API. Leave high for plan/review steps;
  set low for mechanical execution or you pay a token multiple for no quality gain —
  same economics as Nemotron's thinking toggle. In Grok Build TUI: **`/effort low`**
  (or `/model <id> low`); CLI/headless: **`--effort low`**. Catalog tier for
  Preferred matching is **mid** (see plan template) — high effort does not promote
  you to frontier for `/work` fit.
- **`/work` cost right-size:** before skipping `mid` plans or burning high effort on
  them, probe for a cheaper local/fleet executor (`scripts/endpoints.yaml`); if none
  are reachable, emit `/effort low` (or dispatch via `work_once.py --endpoint …`)
  rather than a dead stop. Full contract: `.grok/skills/work/SKILL.md` (Cheaper
  capacity probe + Reasoning effort).
- Community reports intermittent regressions and tool-use flakiness `(unverified)` —
  external verification per the hard rules above is load-bearing here, not ceremony.
- Fit check before starting any task: `.anchor/model-fitness.md` has Grok 4.5's row; a
  poor fit means a `SUGGEST-ESCALATE:` first line per mythos-core rule 11, not a
  silent attempt.

## Working with this repo's tooling

- Task specs come from `.anchor/templates/task-spec.md`; demand one if handed a vague task.
- If MCP is supported in your Grok Build environment, connect `mcp/anchor-prompts` and call `tune_prompt` on any vague task before starting.

## /draft

**Planning mode** on **`.plans/drafts/`**: create/refine, `--list`, load existing
draft for discussion, optional `--local`. **Promote** with
`/draft --promote <slug>` (infer bugs vs features from the plan). Do not
implement product code; do not promote from `/work`. Skill:
`.grok/skills/draft/SKILL.md`.

## /work

Execute the next (or named) ready plan from **`.plans/`** (dotdir). Contract:
resume own `in-progress/` first; bugs before features; honor **Preferred models**
and **Depends on** (skip unmet deps); never execute `drafts/` / `completed/` /
`ambiguous/` / `blocked/`; ignore foreign `in-progress/`; claim ready →
`in-progress/`; park half-baked → `ambiguous/` or stuck → `blocked/`; finish
`in-progress/` → `completed/`. Do not promote drafts from `/work` (use
`/draft --promote`). If Preferred orchestrator is unset, frontier/near-frontier
(including Grok 4.5 as session lead) may act as temporary coordinator
(`TEMPORARY-COORDINATOR:`). On Git projects: **worktree per agent**
(`scripts/worktree_for_agent.py ensure --agent-id … --slug …`); feature-branch
from **`dev`**/`develop` (**create `dev` from main/master if missing**);
**`/commit-prep` before commit**; never auto-merge. Skill:
`.grok/skills/work/SKILL.md`.

## /fleet-watch

Configure durable plan pollers: `/fleet-watch` (this project) or
`/fleet-watch other-app`. Watchers run a work-style claim/execute loop in the
background. Skill: `.grok/skills/fleet-watch/SKILL.md`. Prefer the skill over raw CLI.

## /install-anchor

Ensure the **`anchor` CLI** is on `PATH` safely (user-local symlink to
`bin/anchor`, no sudo by default). Status / fix / optional bindir. Skill:
`.grok/skills/install-anchor/SKILL.md`.

## /anchor

**In a project (this file):** locate the local Anchor checkout and
**conform this tree** (CWD/git root by default) — check/upgrade or
conflict-aware scaffold. Skill: `.grok/skills/anchor/SKILL.md` (source:
`platforms/grok-build/skills/anchor/`). Prefer `anchor --upgrade` when a
manifest exists. Dry-run first; merge/backup/skip on conflicts.

**In the Anchor base skill:** project **path required** (operate on
another project from the Anchor tree). Same slash name; different default.

## /local-models

Probe this machine for **lean local models**, recommend fits, install links, and
optional reconfigure draft. Scaffolded into **projects** (not part of
the Anchor base skill set). Skill: `.grok/skills/local-models/SKILL.md`
(source: `platforms/grok-build/skills/local-models/`). Uses
`scripts/fit_device.py --probe` when fleet/scripts are available.

## /commit-prep

**Required before any `git commit`.** Run `/commit-prep`: tests → CHANGELOG →
blog-if-warranted. **Prep only** — does not commit. After a green prep, follow
**`/work`** / hard rules for feature-branch commit (worktree preferred; never
merge to `dev`/`main`). Command: `platforms/grok-build/commands/commit-prep.md`.

## /config

`commands/config.md` in this folder documents a `/config` command: it asks which
platform(s)/fleet tooling you want as your Anchor default, then runs `./config.sh`
non-interactively to save them and reports the `anchor <project-dir>` command to
scaffold with them. Wiring depends on whether your Grok Build environment supports
file-based custom commands — `(unverified)`, see the caveat in that file. Help:
https://carefreeinv.com/anchor
