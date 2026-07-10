---
name: anchor
description: >
  Scaffold or reconfigure another project with Anchor via /anchor — run the
  anchor CLI creatively, dry-run first, and when conflicts hit existing agent
  config (CLAUDE.md, .claude/, GROK.md, etc.) intelligently propose
  merge/backup/skip options instead of failing silently. Use when the user runs
  /anchor, asks to anchor a project, scaffold Anchor into a project, or resolve
  scaffold conflicts. (Anchor base: project path required. Projects use a
  scaffolded /anchor that defaults to CWD.)
argument-hint: "<project-path> [--status|--upgrade|--dry-run] [--platform keys] [--fleet]"
disable-model-invocation: false
metadata:
  short-description: "Scaffold/reconfigure another project (path required)"
---

# /anchor — scaffold or reconfigure a project with Anchor

**Home (this file):** Anchor **base** skill. Use it while working from
the Anchor tree (or with Anchor on PATH) to apply doctrine + platforms +
optional fleet tooling to **another project**.

**Projects** get a different copy (source under `platforms/…`, scaffolded
with `--platform claude|grok`) that **defaults project to CWD/git root** and
focuses on “conform **this** tree” (locate local Anchor checkout → check /
upgrade). Do not confuse the two defaults.

The raw CLI refuses the whole write when any destination already exists. Your
job is to **inspect first**, **classify conflicts**, and **help the operator
reconfigure** safely — then run `anchor` when the path is clear (or use
`--upgrade` when a manifest already exists).

## Usage

| Invocation | Behavior |
|------------|----------|
| `/anchor <project-path>` | **Required** path; inventory + recommend next action |
| `/anchor ../path/to/project` | Relative path to the target project |
| `/anchor /absolute/path/to/project --status` | Inventory + dry-run conflicts only; **no writes** |
| `/anchor <project-path> --dry-run` | Dry-run scaffold plan |
| `/anchor <project-path> --upgrade` | Prefer `anchor --upgrade` for already-scaffolded trees |
| `/anchor <project-path> --platform claude,grok --fleet` | Pass-through scaffold flags after conflict resolution |

`$ARGUMENTS` is everything after `/anchor`.

**Examples stay generic.** Never invent or name a concrete customer/client app in
skill text, status tables, or suggested commands — only the path the user supplies.

### Required project path (hard) — Anchor base only

A **project path is mandatory**. Do **not** default to CWD.

1. Parse a path from `$ARGUMENTS`: first non-flag token, or `--project PATH`.
2. Expand `~`; resolve relative to CWD (or Anchor root when the user gives an
   explicit relative path).
3. If **no path** is given → **stop** and ask once for the project directory (do not invent one; do not use CWD).
4. If the path does not exist or is not a directory → report and stop.

Print the resolved absolute path before acting. Refuse to scaffold **into the Anchor tree itself** unless the user explicitly insists (high risk of self-overwrite).

## Safety rules (hard)

1. **Never** overwrite agent config or Anchor files without **confirming** the strategy with the user (unless they already said “overwrite / replace / force”).
2. **Dry-run first** before any scaffold write.
3. Prefer **merge / backup / skip** over delete. Keep a timestamped backup when replacing (e.g. `CLAUDE.md.bak-anchor-YYYYMMDD`).
4. If `.anchor-manifest.json` exists → treat as **upgrade path** first (`anchor --check` / `--diff` / `--upgrade`), not a blind re-scaffold.
5. Do not invent platform keys; use `anchor --list` / saved `config.sh` defaults.
6. Docs rule still applies: do not write plan backlog into product docs while reconfiguring.
7. **No `--force`** on upgrade unless the user accepts overwriting locally modified managed files.

## Steps

### 1. Resolve Anchor root + CLI

```bash
# Prefer this repo
test -f scripts/anchor.py && ANCHOR_ROOT=$(pwd)
# or git top-level containing scripts/anchor.py + bin/anchor
```

Run via:

```bash
"$ANCHOR_ROOT/bin/anchor" …
# or: python3 "$ANCHOR_ROOT/scripts/anchor.py" …
```

If `anchor` is missing from PATH, mention `/install-anchor` (optional; not required if you invoke `bin/anchor` by path).

### 2. Require and resolve target project

Per **Required project path** above. Example:

```bash
PROJECT=$(realpath "$PATH_FROM_ARGS")   # must be set
test -d "$PROJECT"
```

### 3. Inventory the target (always)

```bash
ls -la "$PROJECT"
ls -la "$PROJECT"/.claude "$PROJECT"/.grok "$PROJECT"/.anchor 2>/dev/null
ls "$PROJECT"/CLAUDE.md "$PROJECT"/GROK.md "$PROJECT"/CHAT.md \
   "$PROJECT"/NEMOTRON.md "$PROJECT"/ANCHOR-CONVENTIONS.md \
   "$PROJECT"/.anchor/conventions.md "$PROJECT"/.anchor-manifest.json 2>/dev/null
ls -la "$PROJECT"/.plans 2>/dev/null | head
```

Classify presence of:

| Signal | Meaning |
|--------|---------|
| `.anchor-manifest.json` | Prior Anchor scaffold → **upgrade** first |
| `.anchor/ANCHOR.md` or `anchor/ANCHOR.md` | Doctrine present (layout may be legacy) |
| `CLAUDE.md` / `.claude/` | Existing Claude agent config — **likely conflict** |
| `GROK.md` / `.grok/` / `AGENTS.md` | Existing Grok / generic agent config |
| `.plans/` | May already use tracked plans |
| Root `scripts/` / `mcp/` that look like Anchor fleet | Legacy fleet layout |

### 4. Choose mode

| Situation | Mode |
|-----------|------|
| Has manifest | **Upgrade:** `anchor "$PROJECT" --check` then propose `--diff` / `--upgrade` |
| No manifest, empty of Anchor + agent files | **Fresh scaffold** (dry-run → confirm → write) |
| No manifest, **has agent config or partial Anchor** | **Conflict-aware reconfigure** (below) — do not dump “resolve and re-run” only |

### 5. Dry-run scaffold plan

Use saved defaults or args:

```bash
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --dry-run \
  [--platform …] [--fleet] [--framework …] [--orchestrator …]
```

If defaults pull unwanted fleet, override with explicit `--platform` without relying on FLEET=1, or tell the user.

Capture:
- Detected framework
- Platforms / fleet
- File list (should be under `.anchor/…`, `.plans/…`, root platform files only)
- **Conflict list** if exit ≠ 0

### 6. Conflict-aware reconfigure (when conflicts exist)

For **each** conflicting path, classify:

| Class | How to tell | Default offer |
|-------|-------------|---------------|
| **Identical** | `diff -q` vs Anchor source for that dest is empty | Safe to replace or leave; prefer leave + continue |
| **User-owned agent root** | `CLAUDE.md`, `GROK.md`, `AGENTS.md`, large custom body | **Merge** Anchor discipline into existing file (append or section under `## Anchor`) **or** keep user file and skip copy of that dest |
| **Tooling dirs** | `.claude/commands/*`, `.grok/skills/*` | Add **missing** Anchor commands/skills only; do not delete user commands |
| **Legacy Anchor layout** | `anchor/`, root `scripts/` fleet, `ANCHOR-CONVENTIONS.md` | Prefer `anchor --upgrade` after a minimal manifest, or migrate paths then scaffold remaining |
| **Stale Anchor copy** | Manifest missing but `.anchor/` or doctrine fragments exist | Backup → selective refresh / upgrade |
| **Manifest present** | `.anchor-manifest.json` | Do not re-scaffold; `--upgrade` |

#### Merge playbook (agent config)

When the user wants Claude/Grok **and** already has `CLAUDE.md` / `GROK.md`:

1. Read their file + the would-be Anchor platform file from `$ANCHOR_ROOT/platforms/…`.
2. Propose a concrete merge: keep their project-specific rules; add missing Anchor hard rules (fit check, `/work` paths, docs-not-plans, `/commit-prep`) without duplicating.
3. Show a short diff/summary; apply only after OK.
4. For scaffold: temporarily **exclude** that dest by leaving their merged file in place, and manually copy **non-conflicting** plan entries (or move conflict aside, run `anchor --yes`, restore merge). Prefer one clear strategy:

**Strategy A — backup and scaffold (clean):**

```bash
cp -a CLAUDE.md "CLAUDE.md.bak-anchor-$(date +%Y%m%d)"
# resolve other conflicts similarly, then:
anchor "$PROJECT" --platform claude --yes
# re-apply user-specific sections from the backup into CLAUDE.md
```

**Strategy B — skip platform root file:**

- Copy only doctrine (`.anchor/`), `.plans/`, and commands/skills that do not exist.
- Write `.anchor/conventions.md` + manifest by running scaffold after moving only non-essential conflicts, **or** construct conventions via `anchor --set-orchestrator` after partial copy.
- Document that `anchor --check` needs a proper manifest — prefer finishing with a successful `anchor … --yes` once conflicts are cleared.

**Strategy C — already scaffolded:**

```bash
anchor "$PROJECT" --check
anchor "$PROJECT" --diff
anchor "$PROJECT" --upgrade --dry-run
anchor "$PROJECT" --upgrade --yes   # after user OK; --force only if they accept overwriting managed files
```

Present a **conflict table** before acting:

| Path | Class | Recommendation |
|------|-------|----------------|
| `CLAUDE.md` | user-owned | merge Anchor section / backup+replace |
| `.claude/commands/work.md` | missing vs present | add only if missing |
| … | … | … |

Then **ask** which recommendations to apply (or “do all recommended”).

### 7. Execute after the path is clear

1. Re-run dry-run until **no conflicts** (or only intentional skips handled).
2. Run scaffold with `--yes` only after user confirmation (or explicit “just do it”).
3. If upgrade mode: `--upgrade --yes` (± `--force` only when justified).
4. Verify:

```bash
ls -la "$PROJECT"/.anchor "$PROJECT"/.plans "$PROJECT"/.anchor-manifest.json
anchor "$PROJECT" --check
```

5. Summarize: platforms, fleet, conventions path (`.anchor/conventions.md`), any backups created, leftover manual steps (PATH, MCP registration, `/local-models`).

**Source-missing scaffolded skills:** if `--check` reports source missing for files
now living under `platforms/` (e.g. old `local-models` paths), refresh from
`$ANCHOR_ROOT/platforms/…` and update manifest `src` + hash.

### 8. Creative assistance (encouraged)

- Infer platforms from existing config (`.claude` → include `claude`; `.grok` → `grok`).
- Infer framework from markers (`composer.json` → php, etc.) — CLI also detects; mention if dry-run disagrees.
- If only fleet defaults are wrong, re-run with explicit `--platform` without fleet.
- Offer `/local-models` after scaffold when they want a local executor.
- Offer `/install-anchor` if they want `anchor` on PATH for later upgrades.

## Output footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: target path, mode (fresh / reconfigure / upgrade), conflicts found + resolutions, backups, final `anchor --check` summary.

## Out of scope

- Implementing product features inside the target project
- Force-push / git history rewrite
- Scaffolding into the Anchor tree by accident
- Silently deleting the user’s existing agent instructions
- Replacing `/install-anchor` (CLI registration only) or `/local-models` (hardware fit)

## Quick commands

```bash
ANCHOR_ROOT=…   # this repo
PROJECT=…       # target project

"$ANCHOR_ROOT/bin/anchor" --list
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --dry-run
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --check
"$ANCHOR_ROOT/bin/anchor" "$PROJECT" --upgrade --dry-run
```
