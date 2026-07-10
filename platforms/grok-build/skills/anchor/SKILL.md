---
name: anchor
description: >
  Conform this project to current Anchor via /anchor — locate the local Anchor
  checkout, default project to CWD/git root, dry-run first, then check/upgrade
  or conflict-aware scaffold. Use when the user runs /anchor, asks to update
  Anchor in this repo, upgrade scaffold, re-anchor the project, or resolve
  scaffold drift.
argument-hint: "[--status|--upgrade|--dry-run] [--project PATH] [--platform keys] [--fleet]"
disable-model-invocation: false
metadata:
  short-description: "Update this project to match current Anchor"
---

# /anchor — conform **this** project to current Anchor

**Scaffolded skill:** scaffolded into projects via `anchor … --platform claude|grok`.
Source of truth: `platforms/grok-build/skills/anchor/` (and Claude
`platforms/claude-code/commands/anchor.md`) in the Anchor repo — **not** the
Anchor-only skill that requires a foreign project path.

While working **inside a project**, look up the local Anchor checkout
and bring **the current tree** up to date (or finish a partial install). Prefer
**check / upgrade** over blind re-scaffold.

There is a separate **Anchor** `/anchor` (Anchor repo base skills) for
scaffolding **another** project from the Anchor tree — path required there.
This skill defaults to **this** project.

The raw CLI refuses writes when destinations already exist. Your job is to
**inspect first**, **classify conflicts**, and **help the operator reconfigure**
safely — then run `anchor` when the path is clear (or use `--upgrade` when a
manifest already exists).

## Usage

| Invocation | Behavior |
|------------|----------|
| `/anchor` | Project = **this** repo (CWD / git root); locate Anchor; inventory + recommend |
| `/anchor --status` | Inventory + check/diff only; **no writes** |
| `/anchor --upgrade` | Prefer upgrade path when a manifest exists |
| `/anchor --dry-run` | Dry-run scaffold or upgrade plan |
| `/anchor --project PATH` | Override project (rare; default is this tree) |
| `/anchor --platform claude,grok --fleet` | Pass-through scaffold flags after conflict resolution |

`$ARGUMENTS` is everything after `/anchor`.

**Examples stay generic.** Never invent concrete customer/client app names in
skill text — only the path the user supplies or the resolved current project.

## Safety rules (hard)

1. **Never** overwrite agent config or Anchor files without **confirming** the
   strategy (unless they already said “overwrite / replace / force”).
2. **Dry-run first** before any scaffold/upgrade write.
3. Prefer **merge / backup / skip** over delete. Timestamped backups when
   replacing (e.g. `CLAUDE.md.bak-anchor-YYYYMMDD`).
4. If `.anchor-manifest.json` exists → **upgrade path** first
   (`--check` / `--diff` / `--upgrade`), not a blind re-scaffold.
5. Do not invent platform keys; use `anchor --list` / saved defaults.
6. Docs rule: do not write plan backlog into product docs while reconfiguring.
7. **No `--force`** on upgrade unless the user accepts overwriting locally
   modified managed files (project facts in `CLAUDE.md` / `GROK.md` often live there).

## Steps

### 1. Resolve project (default: current tree)

Apply in order:

1. Explicit `--project PATH` or first non-flag path token in `$ARGUMENTS`.
2. Else **git root** of CWD if `git rev-parse --show-toplevel` works.
3. Else **CWD**.

```bash
PROJECT=$(realpath "$RESOLVED")
test -d "$PROJECT"
```

Print the resolved absolute path before acting.

**Refuse** to treat the **Anchor tree itself** as a scaffold target unless
the user explicitly insists (self-overwrite risk). Detect Anchor source tree: directory
contains both `bin/anchor` and `scripts/anchor.py` **and** is the source tree
(not a project that only has `.anchor/scripts`). If CWD *is* Anchor,
stop and point them at Anchor `/anchor <other-project-path>` instead.

### 2. Locate Anchor checkout (quietly)

Find a directory with **both** `bin/anchor` and `scripts/anchor.py`:

1. `command -v anchor` → if a working symlink/script, resolve to checkout
   (`readlink -f`, or parent of `scripts/anchor.py` next to the wrapper).
2. Git root of CWD if it has those files (operator working from Anchor — rare
   for this skill; usually the Anchor base skill applies).
3. Walk **parents** of `$PROJECT` and CWD for `bin/anchor` + `scripts/anchor.py`.
4. Common sibling: `$PROJECT/../anchor` (and `../Anchor`).
5. Ask once for the Anchor repo path if still missing.

Set `ANCHOR_ROOT`. Verify:

```bash
test -x "$ANCHOR_ROOT/bin/anchor" || test -f "$ANCHOR_ROOT/scripts/anchor.py"
"$ANCHOR_ROOT/bin/anchor" --list >/dev/null
# or: python3 "$ANCHOR_ROOT/scripts/anchor.py" --list >/dev/null
```

If `anchor` is not on PATH, invoke via `"$ANCHOR_ROOT/bin/anchor"` and optionally
offer `/install-anchor` later — do not block on PATH.

### 3. Inventory the project (always)

```bash
ls -la "$PROJECT"
ls -la "$PROJECT"/.claude "$PROJECT"/.grok "$PROJECT"/.anchor 2>/dev/null
ls "$PROJECT"/CLAUDE.md "$PROJECT"/GROK.md "$PROJECT"/CHAT.md \
   "$PROJECT"/NEMOTRON.md "$PROJECT"/ANCHOR-CONVENTIONS.md \
   "$PROJECT"/.anchor/conventions.md "$PROJECT"/.anchor-manifest.json 2>/dev/null
ls -la "$PROJECT"/.plans 2>/dev/null | head
```

| Signal | Meaning |
|--------|---------|
| `.anchor-manifest.json` | Prior scaffold → **upgrade** first |
| `.anchor/ANCHOR.md` or `anchor/ANCHOR.md` | Doctrine present (layout may be legacy) |
| `CLAUDE.md` / `.claude/` | Existing Claude config — **likely conflict** if fresh scaffold |
| `GROK.md` / `.grok/` / `AGENTS.md` | Existing Grok / generic agent config |
| `.plans/` | May already use tracked plans |
| Root `scripts/` / `mcp/` that look like Anchor fleet | Legacy fleet layout |

### 4. Choose mode

| Situation | Mode |
|-----------|------|
| Has manifest | **Upgrade:** `--check` then propose `--diff` / `--upgrade` |
| No manifest, empty of Anchor + agent files | **Fresh scaffold** (dry-run → confirm → write) |
| No manifest, **has agent config or partial Anchor** | **Conflict-aware reconfigure** |

### 5. Manifest present → upgrade path (default “conform me”)

```bash
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --check
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --upgrade --dry-run
# optional detail:
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --diff
```

Present a short table:

| Path | State | Recommendation |
|------|-------|----------------|
| … | upstream updated | **TAKE** |
| … | locally modified | **KEEP** (unless user wants merge/`--force`) |
| … | source missing / new | refresh from current platforms; fix manifest if needed |

Then **ask** before writes. On OK:

```bash
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --upgrade --yes
# --force only with explicit user acceptance of overwriting local mods
```

**Special case — scaffolded-only skills** (e.g. `/local-models`, this `/anchor`
skill) whose manifest `src` still points at old Anchor-source paths: if
`--check` says **source missing** but the file lives under
`$ANCHOR_ROOT/platforms/…`, copy the current platforms source to the project
dest, update manifest `src` + hash to the platforms path, and re-check. Do not
leave broken “source missing” without offering that fix.

### 6. No manifest → dry-run scaffold

Infer platforms when useful (`.claude` → `claude`; `.grok` → `grok`). Use saved
defaults or `$ARGUMENTS`:

```bash
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --dry-run \
  [--platform …] [--fleet] [--framework …] [--orchestrator …]
```

Capture framework, platforms/fleet, file list, **conflicts**.

### 7. Conflict-aware reconfigure

For each conflicting path:

| Class | Default offer |
|-------|----------------|
| **Identical** | Leave or safe replace |
| **User-owned agent root** (`CLAUDE.md`, `GROK.md`, …) | **Merge** project facts + Anchor discipline, or skip that dest |
| **Tooling dirs** (commands/skills) | Add **missing** Anchor entries only |
| **Legacy layout** | Prefer migrate + upgrade |
| **Stale fragments** | Backup → selective refresh |

Merge playbook for existing `CLAUDE.md` / `GROK.md`:

1. Read user file + would-be source under `$ANCHOR_ROOT/platforms/…`.
2. Keep project-specific rules; add missing Anchor hard rules (fit check,
   `/work` paths, docs-not-plans, `/commit-prep`) without duplicating.
3. Show summary; apply only after OK.
4. Prefer backup before replace; re-apply project sections after clean scaffold
   if needed.

Show a **conflict table**, then ask which recommendations to apply.

### 8. Execute after the path is clear

1. Dry-run until clear (or intentional skips handled).
2. Scaffold `--yes` or `--upgrade --yes` only after confirmation (or clear
   “just do it”).
3. Verify:

```bash
ls -la "$PROJECT"/.anchor "$PROJECT"/.plans "$PROJECT"/.anchor-manifest.json
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --check
```

4. Summarize: platforms, fleet, conventions (`.anchor/conventions.md`), backups,
   leftover steps (`/install-anchor`, `/local-models`, MCP registration).

## Output footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: `PROJECT`, `ANCHOR_ROOT`, mode (upgrade / reconfigure / fresh),
conflicts + resolutions, whether writes ran.

## Out of scope

- Implementing product features in the project
- Force-push / history rewrite
- Scaffolding the Anchor tree by accident
- Silently deleting user agent instructions
- Replacing `/install-anchor` (PATH only) or `/local-models` (hardware fit)

## Quick commands

```bash
ANCHOR_ROOT=…   # local Anchor checkout
PROJECT=…       # this project (default)

"$ANCHOR_ROOT/bin/anchor" --list
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --check
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --upgrade --dry-run
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --upgrade --yes
```
