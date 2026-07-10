---
description: Scaffold or reconfigure another project with Anchor (path required; dry-run first; conflict-aware)
argument-hint: "<project-path> [--status|--upgrade|--dry-run] [--platform keys] [--fleet]"
allowed-tools: Bash(*), Read, Edit, Write, Glob, Grep
---

# /anchor — scaffold or reconfigure a project with Anchor

**This command is the Anchor base skill** (path to **another** project is
required). Full procedure: **`.grok/skills/anchor/SKILL.md`**.

**Projects** get a different scaffolded `/anchor` (source under
`platforms/claude-code/commands/anchor.md`) that **defaults to the current
tree** and focuses on check/upgrade. Do not use Anchor-base defaults when working
inside a project that has the scaffolded skill.

## Summary

1. Resolve **Anchor root** (`scripts/anchor.py` + `bin/anchor`).
2. **Require a project path** from `$ARGUMENTS` (first non-flag token or
   `--project PATH`). If missing → stop and ask; **do not default to CWD**.
   Use only the path the user supplied — never invent a concrete project name
   in examples or replies.
3. Inventory target: manifest, `.anchor/`, `CLAUDE.md` / `.claude/`, `GROK.md` /
   `.grok/`, `.plans/`, legacy layout.
4. If **manifest** exists → prefer `anchor --check` / `--diff` / `--upgrade`.
5. Else **dry-run** scaffold (`bin/anchor "$PROJECT" --dry-run …`).
6. On **conflicts**: classify each path (identical / user agent config / tooling
   dir / legacy Anchor). Propose **merge, backup+replace, or skip** — never only
   “resolve and re-run”. Show a conflict table; get confirmation before writes.
7. Merge playbook for existing `CLAUDE.md`/`GROK.md`: keep project rules; add
   missing Anchor discipline; backup before replace.
8. Re-run dry-run until clear; then `anchor … --yes` or `--upgrade --yes`.
9. Verify with `ls` + `anchor --check`.

## Safety

- Project path is **mandatory** (Anchor base).
- Confirm before overwrite/merge.
- Timestamped backups when replacing agent config.
- Do not scaffold into the Anchor tree unless the user insists.

End with `## Result`, `## How to verify`, `## Deferred / concerns`.
