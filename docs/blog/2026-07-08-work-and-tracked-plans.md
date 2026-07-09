---
title: "/work and tracked plans"
authors: [carefree]
tags: [feature, docs]
---

Cross-model handoff is now a git-tracked tree, not chat archaeology. Ready plans live under **`.plans/`**; executors start with **`/work`**, honor each plan's **Preferred models**, and archive only when **Done when** holds.

<!-- truncate -->

Until now, the orchestrator pattern assumed you would park plans somewhere and remember which model should run them. Anchor makes that explicit: scaffold installs a `.plans/` tree (`bugs/`, `features/`, `in-progress/`, `ambiguous/`, `blocked/`, `drafts/`, `completed/`) plus a process contract in `.plans/README.md`. Plans are markdown; the tree is git-tracked. Private experiments use `<slug>.local.md`.

**`/work`** is the shared entrypoint (Claude: `.claude/commands/work.md`; Grok: `.grok/skills/work/SKILL.md`). Bare `/work` resumes own `in-progress/`, then picks the highest-priority **model-fit** ready plan whose **Depends on** are met. Flags: `/work --list`, `/work --no-fit-check`, `/work <slug>`. For always-on pullers, **`/fleet-watch`** installs reboot-persistent timers.

Fit and dependencies are intentional economics. Headers carry **Preferred models** and **Depends on** (other plan slugs, or `none`). Expensive tiers skip cheap work; small models skip architecture; nobody starts a plan while a dependency is still open. Set a **Preferred orchestrator** per project; if unset, frontier/near-frontier may act as temporary coordinator.

**Promotion is human-only** (`drafts/` → ready). Agents claim ready → `in-progress/`, finish → `completed/`, and may park half-baked or stuck work in `ambiguous/` / `blocked/`. Headless: `work_once.py` or `orchestrate.py --plan-file` (refuses non-executable lanes). Optional: `python scripts/check_plans.py`.

Start from [Skills → `/work`](/skills/work) and [Tooling → Fleet workers](/tooling/fleet-workers).
