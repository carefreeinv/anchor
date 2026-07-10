# Changelog

Notable, user-visible changes to Anchor. Updated by `/commit-prep` before each
commit; format loosely follows [Keep a Changelog](https://keepachangelog.com).
Newest first.

## [Unreleased]

### Added

- **`scripts/roles.py`** — planner / executor / critic as **harness-enforced capability sets** (single role→capability map): writable-path allow/deny globs per role (planner only `.plans/**`; executor everything except `.plans/**` and its own spec; critic read-only), `can_dispatch` (orchestrator only), and per-role MCP toolsets. Reuses `scope_gate.path_matches` — one glob implementation
- **`orchestrate.py` role enforcement** — each phase's worktree writes are checked against its role's capability map (only changes made *during* a phase are attributed to it); a violation is a hard error: logged as an event, task marked `failed-role`, run still emits its outputs then exits `4`. Role transitions (plan approved → executors spawned → review) are explicit logged events in the run JSON
- **project-orchestrator MCP `--role`** — `--role planner|executor|critic|orchestrator` scopes the registered toolset: planner/critic sessions never see `plans_claim`/`plans_release`/`plans_complete` (deny by omission); no `--role` keeps the full surface. ANCHOR.md role-separation bullet + mythos-core rule 2 now note the harness guarantee (orchestrated path only; single-model sessions stay prompt-bound)
- **Project `/anchor` skill** (scaffolded via `claude`/`grok`; source under `platforms/…`) — while in a project, locate the local Anchor checkout and **conform this project** (CWD/git root default): check/upgrade or conflict-aware scaffold; fix source-missing managed files when paths moved under `platforms/`. Anchor base `/anchor` remains path-required for operating on another tree.
- **`/anchor` skill** (Anchor base — Grok + Claude) — agent-driven scaffold/reconfigure of a **target** project: path required; dry-run first; merge/backup/skip on conflicts; prefer `--upgrade` when a manifest exists.
- **`/install-anchor` skill** (Claude + Grok; scaffolded) — safely put the `anchor` CLI on `PATH` via a user-local symlink to `bin/anchor` (no sudo by default); status / fix / optional bindir.
- **`/local-models` skill** (scaffolded via `claude`/`grok` platforms; source under `platforms/…`, **not** Anchor base skills) + **`fit_device.py --probe`** — evaluate this machine for lean local models; install links; optional reconfigure draft; WSL host probe + routing policy.
- **WSL host probe** — from WSL, `--probe` calls `powershell.exe` for bare-metal RAM/CPU/GPU (no user-run `.ps1`); sizes fits to host budget; recommends running the model server on **Windows bare metal** with Anchor remaining in WSL.
- **`/local-models` draft offer** — after the probe report, agents ask whether to create a `.plans/drafts/` plan to wire the project to the detected local model(s); install process lives in **`## Prerequisites`** for later `/work` once deps are installed.
- **`/local-models` routing policy** — reconfigure drafts: user model-priority order is primary; small locals stay on light tiers; when the host can run heavy local inference, prefer fit locals for heavy work within that priority (no promoting tiny locals to frontier roles).
- **`anchor --upgrade` / `--update`** — refresh an already-scaffolded project to current scaffold patterns: layout migration (`anchor/…` doctrine → `.anchor/…`), take clean upstream updates, restore missing managed files, add newly introduced scaffold files for recorded platforms; keeps locally modified files unless `--force`. **`--diff`** prints unified diffs; **`--check`** remains a short status summary. Non-interactive: `--yes` (required off a tty).
- **`scripts/scope_gate.py`** — machine-enforced scope gate (mythos-core rule 7): rejects any worktree change outside a task spec's `## Files in scope` **before** tests run. Pure `check_scope` + git-backed `worktree_changes`/`enforce_scope`; gitignore-style globs; `Allowed generated files:` allowlist. Wired into `orchestrate.py --scope-spec` (out-of-scope → `failed-scope`, tests skipped, routed back to planner) and usable standalone as a verify pre-step (`scope_gate.py --root . --spec spec.md && pytest -q`, exit `3` = violation). Task-spec template + docs updated
- **`scripts/pending_merges.py`** — surfaces finished work committed but **not yet merged** into integration: counts each local branch's commits ahead of its merge target (`feature/*` → `dev`/`develop` → mainline) and flags `feature/<slug>` branches matching a plan under `.plans/completed/` as *completed work awaiting merge*. Advisory table by default; `--json`, `--exit-code` (exit `1` when pending) for coordinators/monitors/CI
- **Plan `Priority:` header** (`P1` > `P2` > `P3`, default `P2`) — orders ready plans **within a lane** ahead of `Value`; parsed by `scripts/plan_select.py` (`parse_priority` + `plan_sort_key`), shown in `work_once.py --list`; documented in the plan template, `.plans/` README, `/work` (Claude/Grok/Chat), ANCHOR.md, and docs
- **`scripts/worktree_for_agent.py`** — per-`agent-id` git worktrees under `var/worktrees/` (ensure/list/path/remove; auto-create `dev` from main/master); `work_once.py --ensure-worktree` after claim
- **Scaffold / project config ensures `var/`** — creates `var/` + `var/worktrees/`, appends `var/` to root `.gitignore` (scaffold + `--set-orchestrator`)
- **`mcp/project-orchestrator/`** — per-project limited orchestrator MCP (L0+L1): `plans_list` / `plans_claim` / `plans_complete` (move-only), heuristic `plans_suggest_dependencies` (propose-only), `plans_stale_report` (tier-gap / age warnings); reuses `plan_select` + `plan_lease`; config `.anchor/mcp.yaml`
- Docs: MCP servers page documents project-orchestrator alongside anchor-prompts and model-fleet
- Blog: [Per-project plan orchestration via MCP](docs/blog/2026-07-09-project-orchestrator-mcp.md)
- Blog: [Parallel agents get their own git worktrees](docs/blog/2026-07-09-agent-worktrees.md)
- **`/draft`** skill (Claude `.claude/commands/draft.md`, Grok `.grok/skills/draft/SKILL.md`, Chat) — planning mode under `.plans/drafts/`; `--list`, `--load`, create/refine, optional `--local` → `*.local.md`; **`--promote <slug>`** infers `bugs/` vs `features/` from the plan (never from `/work`/fleet)
- **`/fleet-watch`** skill + `scripts/fleet_watch.py` — durable multi-tier plan watchers (status/list/once, emit/install systemd user timers with linger, cron fallback); scaffolded for Claude/Grok
- **`scripts/work_once.py`** — headless one-shot / bounded-loop puller (same priority, Preferred models, and Depends on as `/work`); leases in `.plans/.leases/`; shared `scripts/plan_select.py` + `scripts/plan_lease.py`
- Docs: **[Savings](docs/docs/savings.md)** — inference-cost framing, 12-month adoption curves (Q1 ramp), solar-for-local-compute section, humble plain-text donate links; navbar + intro + playbook
- Docs: **Multi-agent fleet workers** (`docs/docs/tooling/fleet-workers.md`) and Skills pages for `/work`, `/draft`, `/fleet-watch`
- Docs site: **Mermaid** (`@docusaurus/theme-mermaid`) plus mid/high-value section graphs across doctrine, playbook, intro, platforms, tooling, hardware
- Docs: local model names link to **official quick-start** pages (Qwen3, Gemma 3, Mistral Small, DeepSeek-R1, Llama 3.3)
- Blog: [Plans, fleet workers, and inference savings](docs/blog/2026-07-08-plans-fleet-savings.md)
- **Preferred orchestrator** (per project): `config.sh --orchestrator`, `anchor --orchestrator` / `--set-orchestrator`, `ANCHOR-CONVENTIONS.md`
- Tracked **`.plans/`** workflow: path-authoritative lanes (`bugs/`, `features/`, `in-progress/`, `ambiguous/`, `blocked/`, `drafts/`, `completed/`); `*.local.md` via `.plans/.gitignore`; scaffold tree under `anchor/scaffold/plans/`
- **`/work`** entrypoint (Claude, Grok, Chat) — pick/execute ready plans; `--list`, `--no-fit-check`; Preferred models + Depends on
- Plan template: Value, Slug, Preferred models, Depends on (no in-file Lane/Status)
- `scripts/check_plans.py` — path-lane + section sanity for `.plans/`
- `anchor/model-fitness.md` + fit check (mythos-core rule 11); scaffolded into projects
- `scripts/fit_device.py` and `hardware/personal-devices/` serve helpers
- Model-priority preference via `./config.sh --model-priority`
- `/commit-prep` command (Claude, Grok, chat)

### Fixed

- **Docs internal links** — rewrite relative cross-page links to absolute `/…` paths so they resolve correctly with Docusaurus `trailingSlash: true` (was producing broken `/anchor/tooling/skills/…`-style URLs)
- **Wording** — prefer **project** over “consumer app” / “consumer project”, and **Anchor** (or **Anchor base**) over “Anchor monorepo”, in skills, platform docs, README, and CLI docs

### Changed

- **Docs Skills sidebar** — category landing [Skills overview](docs/docs/skills/overview.md) lists every skill with **where it’s best used**, packaging (project vs Anchor), and a quick chooser; sidebar labels include short use-hints (`/anchor · update project`, …)
- Blog: [Agent skills for scaffold, PATH, and local models](docs/blog/2026-07-09-agent-skills-scaffold-local-models.md)
- **`.local.md` suffix is sticky** — plans that start as `*.local.md` keep that basename on `/draft --promote` and on later agent lane moves; agents must **never** drop `.local`. Only a **human manual rename** (or create with `/draft --shared`) makes a plan git-tracked. Replaces the old “promotion publishes” rule that stripped `.local` by default.
- **Scaffold doctrine dest is `.anchor/`** — core doctrine files copy from this repo’s `anchor/` package into the project’s **`.anchor/`** tree (e.g. `.anchor/ANCHOR.md`, `.anchor/templates/…`). Root **`.plans/`** is unchanged. Platform docs and generated `ANCHOR-CONVENTIONS.md` point at `.anchor/…`. Fleet `load_prompt` resolves both `anchor/` (source tree) and `.anchor/` (scaffold). Coexists with `.anchor/mcp.yaml`.
- **Fleet scaffold dest is `.anchor/scripts/` + `.anchor/mcp/`** — with `--fleet` (or saved FLEET=1), Anchor no longer writes project-root `scripts/` or `mcp/` (avoids colliding with app-owned trees). `anchor --upgrade` can migrate legacy root fleet copies. Script/MCP entrypoints resolve project root for both layouts.
- **Conventions file is `.anchor/conventions.md`** — scaffold and `--set-orchestrator` no longer write root `ANCHOR-CONVENTIONS.md`; readers dual-read the legacy name; upgrade migrates it.
- **Fresh drafts are private by default** — `/draft` creates `<slug>.local.md` (gitignored); `/draft --shared` creates a tracked `<slug>.md`. Applies to Claude, Grok, and Chat `/draft`
- **`/work` selection order now honors `Priority`** — own in-progress → bugs before features → `Priority` (`P1`>`P2`>`P3`, default `P2`) → `Value` → oldest first; applied consistently across `/work`, `scripts/work_once.py`, and fleet pullers
- **`/work` just-picks on ties by default** — when multiple ready plans share the top priority, `/work` takes the first in sorted order (Priority → Value → oldest → filename) and starts, instead of printing a menu and asking; it names the other tied plans so the user can redirect. Only pauses to ask when the user explicitly asks to choose (Claude + Grok `/work`)
- **Agents must run `/commit-prep` before any `git commit`** — standing rule on Claude/Grok/Chat platforms, `/work`, `/commit-prep` itself, and `.plans/` README (tests + CHANGELOG + blog-if-warranted gates)
- **`/commit-prep` is project-agnostic:** discover CI/tests per repo; no assumed Docusaurus build; blog posts are plain Markdown under `docs/blog/` (create the directory if missing)
- **After green `/commit-prep`, agents finishing plan work commit on the feature branch** (`/work` + platform rules — not inside `/commit-prep` itself; prep stays prep-only)
- **Agent Git:** if neither `dev` nor `develop` exists, **create `dev` from `main` (else `master`)** before feature branches (`/work`, scaffold `.plans/` README, platforms)
- **Docs rule (framework-wide):** docs describe **current shipped state**, not `.plans/` backlog — mythos-core rule 12, `ANCHOR.md`, platforms, scaffold, commit-prep
- **`.plans/` path is authoritative:** agents claim → `in-progress/`, park → `ambiguous/`|`blocked/`, finish → `completed/`; promotion via **`/draft --promote`** or human move only
- **Plan `Depends on`:** `plan_select` satisfaction checks; `/work` and `work_once` skip unmet deps
- **Temporary coordinator:** frontier/near-frontier may announce `TEMPORARY-COORDINATOR:` when Preferred orchestrator is unset; mid/small/local escalate
- Scaffold fleet install includes `work_once` / `plan_select` / `plan_lease` / `fleet_watch`
- Mid-page donate asks are **humble plain text** (link to [Savings](docs/docs/savings.md) + Stripe), not button CTA blocks
- Docs platforms, intro, playbook, MCP, scripts aligned with fleet + plans workflow

### Fixed

- Docs social cards for non-home routes: `trailingSlash: true` so GitHub Pages serves `/blog/`, `/doctrine/`, etc. (not 404); stronger global OG/Twitter image tags and blog description
- Mermaid diagrams render on the docs site (theme + `markdown.mermaid: true`)
- `orchestrate.py --plan-file` rejects non-executable lanes (`drafts/`, `completed/`, parked)
- README note for editable installs on old distro pip/setuptools (PEP 660)
