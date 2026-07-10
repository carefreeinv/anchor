---
title: Agent skills for scaffold, PATH, and local models
authors: [carefree]
tags: [feature, skills, tooling]
---

Operators can now keep an app on current Anchor, register the CLI, and size lean local models — from the coding agent, without memorizing flag soup.

<!-- truncate -->

## Conform this project (or that one)

Two `/anchor` variants share a slash name and different defaults:

- **In a scaffolded project** (`platforms/…` → `.claude/commands/anchor.md` / `.grok/skills/anchor/`): **`/anchor`** means *this* tree (CWD / git root). The agent finds a local Anchor checkout, runs `anchor --check` / `--upgrade`, and only writes after dry-run confirmation.
- **In Anchor** (base skill): **`/anchor <project-path>`** is required so you never accidentally re-scaffold Anchor into itself.

Already-scaffolded trees prefer **`anchor --upgrade`**: take clean upstream updates, add newly introduced scaffold files (for example project `/anchor` itself), keep locally modified managed files unless you pass **`--force`**. Status and diffs stay read-only: `--check`, `--diff`, `--upgrade --dry-run`.

```bash
# From the Anchor repo
anchor /path/to/app --check
anchor /path/to/app --upgrade --dry-run
anchor /path/to/app --upgrade --yes

# In the project (after upgrade installs the scaffolded skill)
# /anchor
# /anchor --upgrade
```

## Put `anchor` on PATH safely

**`/install-anchor`** inspects the OS/shell, locates a checkout that has `bin/anchor` and `scripts/anchor.py`, and proposes a **user-local symlink** (usually `~/.local/bin/anchor`) — no sudo by default, no silent overwrite of a foreign binary.

## What can this box run?

**`/local-models`** (scaffolded into projects only; source under `platforms/`) probes the machine with `scripts/fit_device.py --probe`. On WSL it can read bare-metal host facts via `powershell.exe`, recommend fits from Anchor’s lean catalog, and print clickable install links. After the report it can offer a **draft** under `.plans/drafts/` to wire endpoints later (install steps live in **Prerequisites**). Routing keeps the operator’s **model-priority** order primary and never promotes a tiny local into frontier roles.

## Docs

The Skills section of the docs site opens on an **overview** that states where each skill is best used (sidebar labels include short use-hints). See [Skills overview](/skills/overview), [CLI check/upgrade](/tooling/cli), and [personal devices](/hardware/personal-devices).
