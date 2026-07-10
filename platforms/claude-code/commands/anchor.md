---
description: Locate local Anchor checkout; update/conform this project (check/upgrade or conflict-aware scaffold)
argument-hint: "[--status|--upgrade|--dry-run] [--project PATH] [--platform keys] [--fleet]"
allowed-tools: Bash(*), Read, Edit, Write, Glob, Grep
---

# /anchor — conform **this** project to current Anchor

**Scaffolded skill** (scaffolded with Claude platform; not the Anchor-only
path-required skill). Full procedure:
**`.grok/skills/anchor/SKILL.md`** when present, else Anchor repo
`platforms/grok-build/skills/anchor/SKILL.md`.

## Summary

1. **Project default = this tree** — git root of CWD, or CWD. Optional
   `--project PATH` override. Print resolved path. If CWD is the **Anchor tree** itself, stop and use Anchor `/anchor <other-path>` instead.
2. **Locate Anchor checkout** (`bin/anchor` + `scripts/anchor.py`): resolve
   `command -v anchor`, walk parents of project/CWD, sibling `../anchor`, then
   ask once. Prefer `"$ANCHOR_ROOT/bin/anchor"`; offer `/install-anchor` only if
   PATH registration would help later.
3. **Inventory:** manifest, `.anchor/`, platform roots, `.plans/`, legacy fleet.
4. **Manifest present** → `anchor --check` / `--upgrade --dry-run`; present
   take/keep table; confirm before `--upgrade --yes`. No `--force` unless user
   accepts overwriting local mods. Fix **source missing** scaffolded skills by
   refreshing from `$ANCHOR_ROOT/platforms/…` and updating manifest src/hash.
5. **No manifest** → dry-run scaffold; on conflicts classify (identical /
   user agent config / tooling / legacy) and propose **merge / backup / skip**.
6. Confirm before writes; verify with `anchor --check`.

## Safety

- Default project is **current** project (unlike Anchor `/anchor`).
- Confirm before overwrite/merge; timestamped backups for agent roots.
- Prefer upgrade over re-scaffold when `.anchor-manifest.json` exists.

End with `## Result`, `## How to verify`, `## Deferred / concerns`.
