---
title: "/work and tracked plans"
authors: [carefree]
tags: [feature, docs]
---

Cross-model handoff is now a git-tracked tree, not chat archaeology. Ready plans live under **`.plans/`**; executors start with **`/work`**, honor each plan's **Preferred models**, and archive only when **Done when** holds.

<!-- truncate -->

Until now, the orchestrator pattern assumed you would park plans somewhere and remember which model should run them. Anchor now makes that explicit: scaffold installs an empty `.plans/` tree (lanes `bugs/`, `features/`, `drafts/`, `completed/`) plus a process contract in `.plans/README.md`. Plans are markdown; the tree is git-tracked. Private experiments use `<slug>.local.md`, ignored via scaffolded `.plans/.gitignore`.

**`/work`** is the shared entrypoint. On Claude Code it installs as `.claude/commands/work.md`; on Grok Build as `.grok/skills/work/SKILL.md`; chat platforms follow the same rules without a shell. Bare `/work` picks the highest-priority **model-fit** ready plan (bugs before features, then by `Value`). Optional flags: `/work --list`, `/work --no-fit-check`, `/work <slug>`, or a path under a ready lane.

Fit is intentional economics. Plan headers carry **Preferred models** (`small | mid | reasoner | frontier` and/or concrete names). Expensive tiers skip work that should stay on cheap boxes; small models skip architecture plans. Naming a slug or passing `--no-fit-check` overrides the skip for one plan — still not the whole backlog.

Two hard rules keep fleets honest. **Promotion is human-only** (`drafts/` → `bugs/` or `features/`). Agents may only relocate a plan when finishing: ready lane → `completed/` after Done when holds. Headless runs use `python scripts/orchestrate.py --plan-file .plans/features/foo.md`, which refuses `drafts/` and `completed/`. Optional sanity: `python scripts/check_plans.py`.

Docs put the contract in one place: the new **Skills** sidebar documents `/work` once. Platform pages stay about install and model quirks, not a second copy of the skill. Start from the [Skills → `/work`](/skills/work) page, or type `/work` in a scaffolded project.
