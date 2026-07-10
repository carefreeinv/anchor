---
description: Ensure the `anchor` CLI is safely registered on PATH (user-local symlink; no sudo by default)
allowed-tools: Bash(*)
---

# /install-anchor — register the `anchor` CLI on PATH

Follow the full procedure in the Anchor repo skill (same contract as Grok):

**`.grok/skills/install-anchor/SKILL.md`** (or, when working inside the Anchor
checkout, that path under the repo root).

If that file is not present (project scaffolded without it), use this
abbreviated procedure:

## Goal

Make `anchor` available on PATH **without sudo**, without clobbering a foreign
binary, preferably via symlink to `$ANCHOR_ROOT/bin/anchor`.

## Arguments

`$ARGUMENTS` may include `--status`, `--fix`, and/or `--bin-dir PATH`.

## Steps

1. **System:** `uname -s`, `$SHELL`, `$PATH`, `python3 --version`.
2. **Find Anchor root** containing both `bin/anchor` and `scripts/anchor.py`
   (git root, parents, or ask once).
3. **Status:** `command -v anchor`, `type -a anchor`, `anchor --list` if present.
   Classify: **ok** / **missing** / **broken** / **foreign**.
4. If **ok** and not `--fix`: report and stop.
5. If writing is needed: prefer `$HOME/.local/bin` (or `--bin-dir`); **confirm**
   before `ln -sfn "$ANCHOR_ROOT/bin/anchor" "$BINDIR/anchor"`. Never sudo unless
   the user explicitly asks. Never overwrite **foreign** without explicit OK.
6. If bindir not on PATH: propose (and only with confirm) a shell-rc export.
7. **Verify:** `command -v anchor` && `anchor --list`.

`--status` never writes. `--fix` applies after a short recap when the user
asked to install/fix.

End with `## Result`, `## How to verify`, `## Deferred / concerns`.
