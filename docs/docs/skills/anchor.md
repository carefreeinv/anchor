---
sidebar_position: 1
sidebar_label: /anchor · update project
---

# `/anchor`

**Best used:** in a **project** to conform **this** tree to current Anchor
(CWD default); or in the **Anchor** checkout to scaffold/reconfigure **another**
project (**path required**). See [Skills overview](/skills/overview).

Bring a project in line with the current Anchor checkout: **check / upgrade** an
already-scaffolded tree, or **conflict-aware scaffold** when Anchor is missing
or partial. Agents dry-run first and propose merge/backup/skip instead of
stopping at “resolve and re-run.”

## Two homes (same slash name, different defaults)

| Where the skill lives | Project default | Typical use |
|-----------------------|-----------------|-------------|
| **Project scaffold** (`platforms/…` → `.grok/skills/anchor` / `.claude/commands/anchor.md`) | **This repo** (CWD / git root) | “Update me to current Anchor” while working in a project |
| **Anchor base** (`.grok/skills/anchor`, `.claude/commands/anchor.md`) | **Path required** — never CWD | Scaffold or reconfigure **another** project from the Anchor tree |

Both locate a local Anchor checkout (`bin/anchor` + `scripts/anchor.py`: PATH
symlink, parent walk, sibling `../anchor`, or ask once). Both prefer
`anchor --check` / `--upgrade` when `.anchor-manifest.json` exists.

## Project usage

| Invocation | Behavior |
|------------|----------|
| `/anchor` | Inventory + recommend for **current** project |
| `/anchor --status` | Check / plan only; no writes |
| `/anchor --upgrade` | Prefer upgrade dry-run → confirm → apply |
| `/anchor --dry-run` | Scaffold or upgrade plan only |

## Anchor usage

| Invocation | Behavior |
|------------|----------|
| `/anchor <project-path>` | **Required** path; inventory + recommend |
| `/anchor ../path/to/project --upgrade` | Upgrade that tree from the Anchor session |

## What agents should do

1. Resolve **project** and **`ANCHOR_ROOT`**
2. Inventory manifest, platform roots, `.plans/`
3. Dry-run (`--check` / `--upgrade --dry-run` or scaffold `--dry-run`)
4. Table of take / keep / conflict recommendations
5. Confirm before writes; avoid `--force` unless the operator accepts overwriting
   local managed files (e.g. project facts in `CLAUDE.md`)
6. Fix **source missing** managed files when sources moved under `platforms/`
   (copy current source + update manifest `src`/hash)

## Install paths

| Variant | Scaffolded to | Source in Anchor repo |
|---------|---------------|------------------------|
| Project (Grok) | `.grok/skills/anchor/SKILL.md` | `platforms/grok-build/skills/anchor/SKILL.md` |
| Project (Claude) | `.claude/commands/anchor.md` | `platforms/claude-code/commands/anchor.md` |
| Anchor only | `.grok/skills/anchor/SKILL.md` / `.claude/commands/anchor.md` | same paths in Anchor base (not via `platforms/` map) |

Scaffolded with `--platform claude` and/or `grok`. After an older scaffold,
`anchor --upgrade` (or project `/anchor`) can add the new skill files.

## Related

- [CLI — check, diff, upgrade](/tooling/cli#check-diff-and-upgrade)
- [`/install-anchor`](/skills/install-anchor) — register CLI on PATH
- [`/local-models`](/skills/local-models) — host fit for local executors
