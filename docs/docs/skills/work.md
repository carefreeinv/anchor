---
sidebar_position: 1
sidebar_label: /work
---

# `/work`

Execute the next (or named) ready plan from **`.plans/`**. Same contract on every platform — only install paths and “no shell” adaptations differ.

Plans are git-tracked markdown under the **`.plans/`** dotdir. Do not gitignore the whole tree (scaffold ignores only `*.local.md`). Many UIs hide dotfolders — use the explicit path.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/work` | Pick highest-priority **model-fit** ready plan and execute it |
| `/work --list` | List ready plans (Preferred models + fit); **do not** implement |
| `/work --no-fit-check` | Same priority as bare `/work`, skip model-fit filtering (still **one** plan) |
| `/work --no-fit-check <slug>` | Execute that plan even if Preferred models say otherwise |
| `/work <slug>` | Match `slug.md` or `slug.local.md` under ready lanes |
| `/work .plans/features/foo.md` | Execute that path if it is a ready-lane file |

## Lanes

| Path | Execute? | Complete (`git mv` → `completed/`)? |
|------|----------|-------------------------------------|
| `.plans/bugs/` | **yes** (highest priority) | **yes** |
| `.plans/features/` | **yes** (after all bugs) | **yes** |
| `.plans/drafts/` | **no** (edit only) | **no** |
| `.plans/completed/` | **no** (archive) | n/a |

**Never** implement from `drafts/` or `completed/`. If a draft is named for execution: refuse; offer edit-only.

### Agent move rule (hard)

The **only** relocate an agent may perform under `.plans/` is ready-lane → `completed/` when **Done when** holds:

```text
.plans/bugs|features/<slug>.md  →  .plans/completed/
```

Agents must **never** promote, demote, or swap between `drafts/`, `bugs/`, and `features/`. **Promotion is human-only.**

## Priority (bare `/work`)

1. All of `.plans/bugs/*.md` before any feature
2. Then `.plans/features/*.md` by header `Value: high | medium | low` (default medium)
3. Among those, keep only **model-fit** plans — unless `--no-fit-check` or the user names a plan
4. Skip `drafts/`, `completed/`, and `README.md`

## Model fit

Plan headers SHOULD include **Preferred models** (tiers `small | mid | reasoner | frontier` and/or concrete names). Bare `/work` skips plans that are a poor fit for the current model (overqualified or underqualified). Named slug/path or `--no-fit-check` overrides the skip; still state fit in one line when mismatched. See [model fitness](../model-fitness) and the [plan template](https://github.com/carefreeinv/anchor/blob/main/anchor/templates/plan.md).

## Lifecycle

```text
Write:    agents/humans → .plans/drafts/<slug>.md until ready
Promote:  **human only** → git mv drafts/ → bugs/ or features/; Status: ready
Execute:  /work → follow Steps; verify each step
Finish:   agent: Status: done → git mv → .plans/completed/
```

Mid-session stop: leave the file in its ready lane with `Status: in_progress` and a short `## Progress` note. Do **not** move to `completed/`.

## Install (platform wiring)

The behavior above is identical everywhere. Only how the agent loads the skill differs:

| Platform | Install |
|----------|---------|
| **Claude Code** | Scaffold installs `.claude/commands/work.md` |
| **Grok Build** | Scaffold installs `.grok/skills/work/SKILL.md` (or use `platforms/grok-build/commands/work.md`) |
| **Generic Chat** | No command file — follow the no-shell adaptation below (and in `CHAT.md`) |
| **Local / NIM** | Same contract when the harness has shell; headless: `orchestrate.py --plan-file` |

Scaffold always creates the empty `.plans/` tree + README. Process contract also lives in `.plans/README.md` once scaffolded.

### Chat / no shell

When the user types `/work` without tool access: ask them to `ls .plans/bugs .plans/features` (and related lanes) and paste output; pick by the same priority and model-fit rules; dictate one step at a time with verify commands for the human; on finish dictate the exact `git mv` into `.plans/completed/`. Never dictate a promote move.

### Headless / fleet

```bash
python scripts/orchestrate.py --plan-file .plans/features/foo.md
```

Refuses paths under `drafts/` or `completed/`.

## Related

- [Doctrine — tracked plans](../doctrine)
- [Playbook — orchestrator pattern](../playbook)
- [Platforms](../platforms/claude-code) — install and model-specific notes
- Source skill: `.grok/skills/work/SKILL.md` / `.claude/commands/work.md` in the [Anchor repo](https://github.com/carefreeinv/anchor)
