# Changelog

Notable, user-visible changes to Anchor. Updated by `/commit-prep` before each
commit; format loosely follows [Keep a Changelog](https://keepachangelog.com).
Newest first.

## [Unreleased]

### Added

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

### Changed

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

- Mermaid diagrams render on the docs site (theme + `markdown.mermaid: true`)
- `orchestrate.py --plan-file` rejects non-executable lanes (`drafts/`, `completed/`, parked)
- README note for editable installs on old distro pip/setuptools (PEP 660)
