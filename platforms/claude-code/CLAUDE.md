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

Before dispatching any frontier-model run, rewrite the task on a cheap model into the task-spec template (goal, files in scope, acceptance criteria, definition of done). Three attempts on credits is the silent budget killer; one tuned attempt is the fix. `.anchor/scripts/prompt_tuner.py` automates this.

## Standing rules (apply to every model tier)

- Fit check first (**dual-axis**): (1) **Power** — if the pending task lands in the current model's weak column or is orchestration-class work you should not own (see `.anchor/model-fitness.md` and the model-routing section of `.anchor/conventions.md`), open with `SUGGEST-ESCALATE: <model> — <reason>` and stop. (2) **Specialty** — if power is OK but you are the wrong *kind* of model (e.g. pure chat for multi-file software, critic for bulk implement), open with `SUGGEST-REROUTE: <model or profile> — <reason>` (profiles: `coding-agent`, `terminal-agent`, `critic`, `planner`, `general-chat`, `multimodal`, `swarm-local`) and stop. Proceed only if the user insists. Good fit on both axes → silence. Do not escalate/re-route because a stronger model exists, because a plan's **Preferred models** names one (only listed *tiers* set the power floor), or because one step looks hard. Declining work that fits you stalls the backlog just as badly as overreaching.
- **Surface the best-fit skill:** before acting, judge whether a skill or slash-command **available in this session** (harness skill roster, `.claude/commands/`) would do the request faster or more correctly than working by hand. If one clearly fits, prepend a **single line** naming it and offering to use it, then proceed the same turn — a suggestion, not a gate (never make the user run it first and come back). Only suggest commands actually loaded (never invent one); at most once per capability per session; only when you can name the concrete win. This surfaces cutting-edge features the user may not know exist — it is not a pre-flight item and never a per-prompt nag.
- Restate goal + acceptance criteria before acting; ask one clarifying question if ambiguous, then stop.
- One step at a time; unrelated findings go in a `## Deferred` note, never fixed opportunistically.
- Never claim success — state how to verify, then run the verification.
- Two failed fix attempts on the same error → stop, summarize attempts + hypothesis, escalate a tier.
- **Usage limits are a scheduling problem, not a failure:** on a session/weekly cap or quota (429, `insufficient_quota`, "limit reached", a forced tier downgrade), checkpoint state, then **reroute** to the next model in priority order *that clears the task's fitness floor*, else **wait** for a near reset, else **stop and report**. Never finish work on a silently downgraded tier, and never narrow scope or weaken tests to beat a cap. See `.anchor/capacity-routing.md`.
- Touch only files named in the current task spec.
- End every task with: `## Result`, `## How to verify`, `## Deferred / concerns`.
- SOLID by default; use the project's idiomatic composition mechanism (check `.anchor/conventions.md`) over deep inheritance; no dead code, no spaghetti control flow.
- **Docs describe current state, not plans:** README / `docs/` / CHANGELOG / blog / release notes cover **shipped** code and public contracts only. Never document the **contents** of `.plans/` (drafts, backlog, unfinished acceptance) as product docs or roadmap. When plan work ships, document the code — not the plan file. Documenting the `.plans/` **workflow** itself is fine when that is a shipped feature.
- **Before any commit that touches a path outside `.plans/`, and before any merge commit:** run **`/commit-prep`** (prep only: tests, CHANGELOG, blog-if-warranted). Do not skip prep for “small” changes outside `.plans/` — the test is the **path**, not whether the change is code; a one-line docs or config edit outside `.plans/` is gated exactly the same. A commit whose paths are *entirely* under `.plans/` (lane move, review notes, `## Handoff`) takes the **light path** — state what moved and why, then commit; no CHANGELOG, no blog, no test run. Skills that rearrange `.plans/` commit that themselves rather than leaving it staged. A **merge commit** is gated *before* it exists: `git merge --no-ff --no-commit`, run prep against the merged tree, then **`git add -A && git commit`** if green (prep edits the *working tree*; a bare `git commit` commits only the index and drops its output) or **`git merge --abort || git reset --hard HEAD`** if red (`--abort` refuses once prep has touched a merged file; either way prep's edits to *tracked* files go with the merge, while anything prep **created** — a new blog post — is untracked and survives `reset --hard`; check `git status` and remove or keep it deliberately). A fast-forward creates no commit and needs none. After gates are **green**, if plan work is complete (or the user asked to land the work), **stage + commit on the feature branch** (worktree preferred); optional feature-branch push; never commit on main/dev — **except** the plans-only lane-move commit above, which **`/review`**, **`/work`** and **`/draft --promote`** make on whichever branch the lane move exists on, including an integration branch. **Never merge on your own initiative** — `/work` may land a branch on **`dev` only** via its culmination question + scoped-merge gate (operator answers in-session); `main` only via `/review`'s promotion survey.

## Hooks & automation suggestions

- PostToolUse hook on Edit/Write: run the project's linter; feed failures back verbatim.
- Pre-commit: run **`/commit-prep`**, then the step's definition-of-done command; block commit on failure.
- Use git worktrees for parallel subagent tasks to keep diffs scoped and reviewable.

## MCP

Connect `.anchor/mcp/anchor-prompts` (templates + tune/critique tools) and `.anchor/mcp/model-fleet` (delegate steps to local/NIM endpoints) from this repo. Prefer delegating mechanical steps to the local fleet before spending plan-limit tokens.

## /draft

**Planning mode** on **`.plans/drafts/`**: create/refine, `--list`, load existing
slug for discussion (`--load` or slug that exists), optional `--local` →
`*.local.md`. **Promote** with `/draft --promote <slug>` (infer `bugs/` vs
`features/` from the plan; user-authorized). Do not implement product code; do
not promote from `/work`. Command: `.claude/commands/draft.md`.

## /work

Execute the next (or named) ready plan from **`.plans/`** (dotdir). Contract:
bare pick is **ready lanes only** (never scans `in-progress/`; resume is an
explicit named claim you own); bugs before features; honor **Preferred models**
and **Depends on** (skip unmet deps); never execute `drafts/` / `completed/` /
`ambiguous/` / `blocked/`; ignore foreign `in-progress/`; claim ready →
`in-progress/` (atomic move + required lease); park half-baked → `ambiguous/` or
stuck → `blocked/`; finish `in-progress/` → `review-needed/` (required; human
**`/review`** → `completed/`).
Do not promote drafts from `/work` (use `/draft --promote`). If Preferred orchestrator is unset, frontier/near-frontier
may act as temporary coordinator (`TEMPORARY-COORDINATOR:`). On Git projects: **worktree per agent**
(`.anchor/scripts/worktree_for_agent.py ensure --agent-id … --slug …`); feature-branch
from **`dev`**/`develop` (**create `dev` from main/master if missing**);
**`/commit-prep` before commit**; `/work` merges only on the operator's in-session culmination answer, scoped, **`dev` only** (otherwise human `/review` does). Command:
`.claude/commands/work.md`.

## /review

Human sign-off for **one** plan under `.plans/review-needed/`: checkout
`feature/<slug>` when safe, fresh-context AI critic, survey (Approve / Needs
Work / Skip). **Approve merges `feature/<slug>` → `dev`**, then → `completed/`;
Needs Work → `bugs|features/`. Empty queue with `dev` ahead of `main` offers a
**promotion** survey (**Promote** merges `dev` → `main`). Command:
`.claude/commands/review.md`.

## /audit

Exhaustive **security audit** (first-party code + dependencies) that writes
prioritized bug plans under `.plans/bugs/` (or `--to drafts`). **Frontier /
reasoner only** by default (`--force-model` override). Plans only — no auto-fix,
no exploit PoCs. Command: `.claude/commands/audit.md`.

## /deploy

Deploy this project with **the tooling it already uses** — CI push-to-deploy,
platform CLI (Vercel/Netlify/Fly/DO/Cloudflare), a release framework
(Deployer/Capistrano/Kamal/Fabric/Ansible), or a plain `production` git remote.
Detect first; never scaffold over existing tooling. **Nothing detected** → ask
where it should deploy, then set up the framework that fits the stack
(`--setup` writes config + dry run and **stops**). Refuses a dirty tree
(`--allow-dirty`), always prints the target and confirms before the first remote
command, never commits/merges/force-pushes, never destroys infra, and verifies
the deploy landed. `--dry-run`, `--status`, `--rollback`. Command:
`.claude/commands/deploy.md`.

## /optimize

Scan the project against **standards for its detected type** (web app: OG
images, `robots.txt`, `llms.txt`, sitemap; CLI/library: `CODEOWNERS`,
`SECURITY.md`, release config; any repo: dependency bot, `LICENSE`), propose
**up to 10** ranked improvement candidates, and write only checkbox-picked
ones as plans. Hygiene/DX, not security (`/audit`'s job) — soft `mid,
reasoner` preference, no refuse gate. Default write lane `.plans/drafts/`;
`--to features`/`--to bugs` opt in to a ready lane. `--dry-run`, `--write`,
`--continue`. Command: `.claude/commands/optimize.md`.

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
optional reconfigure draft. **Dual-use:** lives in the Anchor checkout base
**and** scaffolded into projects. Command: `.claude/commands/local-models.md`
(full procedure: `.grok/skills/local-models/SKILL.md`).
Uses `fit_device.py --probe` when available — `scripts/` in the Anchor
checkout, `.anchor/scripts/` in a scaffolded project.

## /tag

Cut an **annotated** version tag on the current commit. Detects the repo's
existing tag scheme rather than inventing one (`--suggest` proposes the next
version from the last tag + CHANGELOG). Refuses a dirty tree, a tag that
already exists, and any tag not on the intended base. Does **not** push.
Command: `.claude/commands/tag.md`.

## /push

Push the current branch (and optionally its tags) with the ceremony a shared
branch deserves: confirms the remote and branch, names the protected-branch
risk, and uses `--force-with-lease` when a force is genuinely required —
never a bare `--force`. Does **not** create tags. Command:
`.claude/commands/push.md`.

## /release

Intentional product ship: report finished work **not** on the release base,
plan–diff review what *is* on it, then `/tag` + `/push`. **`/release` never
merges** — branches reach `dev` via `/review` Approve or a `/work` scoped
merge, and `main` only via `/review`'s promotion survey. Command:
`.claude/commands/release.md`.

## /commit-prep

**Required before any commit that touches a path outside `.plans/`, and before any merge commit.** A commit whose paths are *entirely* under `.plans/` takes the **light path** instead: state what moved and why, then `git add .plans/` and `git commit -m "…" -- .plans/`; no CHANGELOG, no blog, no test run. Run `/commit-prep` (command:
`.claude/commands/commit-prep.md`): tests → CHANGELOG → blog-if-warranted.
**Prep only** — does not commit. After a green prep, commit policy is under
**`/work`** / standing rules (feature branch + worktree; merge to `dev` only via `/work`'s culmination answer + scoped gate; never to `main`).

## /config

`/config` lives in the **Anchor checkout**, not in this project — it is deliberately
not scaffolded. It sets *your* operator defaults (platform(s)/fleet tooling, model
priority, preferred orchestrator) by running `./config.sh`, and there is nothing for
it to act on inside a scaffolded tree. Run it from the Anchor checkout
(`.claude/commands/config.md` there), then scaffold with `anchor <project-dir>`.
To change just this project's orchestrator: `anchor <dir> --set-orchestrator <token>`.
Help: https://carefreeinv.com/anchor
