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
11. **Before any `git commit`:** run **`/commit-prep`** (prep only: tests, CHANGELOG, blog-if-warranted). Do not skip for “small” changes. After gates are **green**, if plan work is complete, stage + commit on the **feature branch** (worktree preferred); never on main/dev. **Never merge on your own initiative** — `/work` may land a branch on **`dev` only** via its culmination question + scoped-merge gate (operator answers in-session); `main` only via `/review`'s promotion survey.

12. **Usage limits are a scheduling problem, not a failure.** On a session/weekly cap or quota (429, `insufficient_quota`, "limit reached", a forced tier downgrade), checkpoint state, then **reroute** to the next model in priority order *that clears the task's fitness floor*, else **wait** for a near reset, else **stop and report**. Never finish work on a silently downgraded tier, and never narrow scope or weaken tests to beat a cap. See `.anchor/capacity-routing.md`.

13. **Surface the best-fit skill.** Before acting, judge whether a skill or command **available in this session** (`.grok/skills/`, harness skill roster) would do the request faster or more correctly than working by hand. If one clearly fits, prepend a **single line** naming it and offering to use it, then proceed the same turn — a suggestion, not a gate (never make the user run it first and come back). Suggest only skills actually loaded (never invent one); at most once per capability per session; only when you can name the concrete win. Surfaces cutting-edge features the user may not know exist — never a per-prompt nag.

## Grok-specific tuning

- Grok tends to compress reasoning — force it out: "Before the plan, list 3 ways this task could go wrong."
- Grok follows recent instructions over early ones in long sessions: keep sessions short, one task spec per session, restart rather than accumulate context.
- For anything security-adjacent or architectural, don't let Grok decide alone — mark the step `Route to: bigger model` in the plan.
- The reverse matters too: if a step is boilerplate/formatting/a rename, mark it `Route to: smaller/local model` instead of running it on Grok's default tier.

## Grok product notes (reviewed 2026-08-12)

### Pick 4.5 vs 4.6 (cost ladder)

Both stay first-class until 4.5 is retired. **Prefer the cheaper generation when it is enough.**

| Product | Use when | Priority token |
|---------|----------|----------------|
| **Grok 4.5** | Lighter mid: file-scoped execute, terminal/CLI, mechanical multi-file, cost-sensitive runs | `grok:4.5` |
| **Grok 4.6** | Heavier agent work: long multi-step coding, interactive/visual projects, when 4.5 quality is not enough | `grok:4.6` |

Example model-priority (cheap → expensive among Grok):
`local:qwen3,nim,grok:4.5,grok:4.6,claude:sonnet,claude:opus,claude:fable`
Bare `grok` = whatever session you opened; versioned tokens make a 4.5 sunset a one-line edit.

### Shared behavior (4.6 + 4.5)

- **Play to strengths:** terminal/CLI and multi-step agent loops. Prefer **file-scoped**
  task specs for repo-scale issues until local fitness data improves DeepSWE-class
  confidence (4.5 was measurably behind Fable-class; 4.6 still treat carefully).
- **Grok 4.6** (public 2026-08-12) — long-running agents, ambitious interactive/visual
  work; vendor composite ≈ GPT-5.6 Sol `(unverified, vendor)`.
- **Grok 4.5** (public 2026-07-09) — still the **default cheap Grok** for thin mid work
  while available; same effort map (`xhigh` coerced to `high` → reasoner, not frontier).
- **Base catalog tier = mid; reported effort sets effective Preferred tier**
  (Grok family only — see `model-fitness.md` “Effort as effective tier”):

  | Effort | Effective fit tier |
  |--------|--------------------|
  | `low` / `minimal` | `mid` |
  | `medium` / `high` (API default) | `reasoner` |
  | `xhigh` (4.6 only; opt-in) | `frontier` |

  **Omitted / unknown effort → effective `mid`** (never silent frontier from API
  default). Report yourself as `Grok 4.5|4.6 @ <effort> → effective <tier>` before fit (pick product by cost ladder above).
- **Pasteable dials:** TUI **`/effort low|medium|high|xhigh`** (or `/model <id> low`);
  CLI **`--effort …`**; fleet endpoint quirk `reasoning_effort:` in `endpoints.yaml`
  (sent by `anchor_client.py`). Prefer **low** for mechanical steps; reserve
  medium/high for architecture-ish work; reserve **xhigh** for true long-horizon frontier routing — costly, opt-in only.
- **`/work`:** pass `--effort` into `plan_fit` / `work_once` when you know the dial
  so eligibility matches. Before burning high/`xhigh` on `small`/`mid` Preferred,
  probe cheaper local/fleet capacity. Full contract: `.grok/skills/work/SKILL.md`.
- Fit check before starting any task (**dual-axis**, mythos-core rule 11): `.anchor/model-fitness.md`
  has Grok 4.5 / 4.6 rows (`terminal-agent` + `coding-agent`). **Power** poor fit →
  `SUGGEST-ESCALATE:` first line. **Specialty** mismatch (e.g. pure long multimodal
  design doc better on `multimodal`, or pure chat UI with no shell) →
  `SUGGEST-REROUTE: <target or profile> — <reason>`, not a silent attempt. Good on
  both axes → silence. Symmetrically, **mid is a floor you clear, not a ceiling you
  apologize for**: repo-scale issue resolution is Grok 4.5's documented weak spot,
  file-scoped `mid` plans are not. Do not skip a plan because its **Preferred
  models** also names a stronger product — only listed *tiers* gate power. Reported
  `high` makes Grok **effective reasoner** (skips mid-only Preferred); omitted
  `--effort` stays mid.

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
bare pick is **ready lanes only** (never scans `in-progress/`; resume is an
explicit named claim you own); bugs before features; honor **Preferred models**
and **Depends on** (skip unmet deps); never execute `drafts/` / `completed/` /
`ambiguous/` / `blocked/`; ignore foreign `in-progress/`; claim ready →
`in-progress/` (atomic move + required lease); park half-baked → `ambiguous/` or
stuck → `blocked/`; finish `in-progress/` → `review-needed/` (required; human
**`/review`** → `completed/`).
Do not promote drafts from `/work` (use `/draft --promote`). If Preferred orchestrator is unset, frontier/near-frontier
(including Grok 4.5 as session lead) may act as temporary coordinator
(`TEMPORARY-COORDINATOR:`). On Git projects: **worktree per agent**
(`scripts/worktree_for_agent.py ensure --agent-id … --slug …`); feature-branch
from **`dev`**/`develop` (**create `dev` from main/master if missing**);
**`/commit-prep` before commit**; `/work` merges only on the operator's in-session culmination answer, scoped, **`dev` only** (otherwise human `/review` does). Skill:
`.grok/skills/work/SKILL.md`.

## /review

Human sign-off for **one** plan under `.plans/review-needed/`: checkout
`feature/<slug>` when safe, fresh-context AI critic, survey (Approve / Needs
Work / Skip). **Approve merges `feature/<slug>` → `dev`**, then → `completed/`;
Needs Work → `bugs|features/`. Empty queue with `dev` ahead of `main` offers a
**promotion** survey (**Promote** merges `dev` → `main`). Skill:
`.grok/skills/review/SKILL.md`.

## /audit

Exhaustive **security audit** (first-party code + dependencies) that writes
prioritized bug plans under `.plans/bugs/` (or `--to drafts`). **Frontier /
reasoner only** by default (`--force-model` override; Grok 4.5/4.6 base catalog is mid-class for
this gate). Plans only — no auto-fix, no exploit PoCs. Skill:
`.grok/skills/audit/SKILL.md`.

## /deploy

Deploy this project with **the tooling it already uses** — CI push-to-deploy,
platform CLI (Vercel/Netlify/Fly/DO/Cloudflare), a release framework
(Deployer/Capistrano/Kamal/Fabric/Ansible), or a plain `production` git remote.
Detect first; never scaffold over existing tooling. **Nothing detected** → ask
where it should deploy, then set up the framework that fits the stack
(`--setup` writes config + dry run and **stops**). Refuses a dirty tree
(`--allow-dirty`), always prints the target and confirms before the first remote
command, never commits/merges/force-pushes, never destroys infra, and verifies
the deploy landed. `--dry-run`, `--status`, `--rollback`. Skill:
`.grok/skills/deploy/SKILL.md`.

## /optimize

Scan the project against **standards for its detected type** (web app: OG
images, `robots.txt`, `llms.txt`, sitemap; CLI/library: `CODEOWNERS`,
`SECURITY.md`, release config; any repo: dependency bot, `LICENSE`), propose
**up to 10** ranked improvement candidates, and write only checkbox-picked
ones as plans. Hygiene/DX, not security (`/audit`'s job) — soft `mid,
reasoner` preference, no refuse gate. Default write lane `.plans/drafts/`;
`--to features`/`--to bugs` opt in to a ready lane. `--dry-run`, `--write`,
`--continue`. Skill: `.grok/skills/optimize/SKILL.md`.

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
merge to `dev`/`main`). Skill: `.grok/skills/commit-prep/SKILL.md`.

## /config

`/config` lives in the **Anchor checkout**, not in this project — it is deliberately
not scaffolded. It sets *your* operator defaults (platform(s)/fleet tooling, model
priority, preferred orchestrator) by running `./config.sh`, and there is nothing for
it to act on inside a scaffolded tree. Run it from the Anchor checkout
(`.grok/skills/config/SKILL.md` there), then scaffold with `anchor <project-dir>`.
To change just this project's orchestrator: `anchor <dir> --set-orchestrator <token>`.
Wiring depends on whether your Grok Build environment supports file-based skills
— `(unverified)`, see the caveat in that file. Help:
https://carefreeinv.com/anchor
