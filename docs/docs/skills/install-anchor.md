---
sidebar_position: 5
sidebar_label: /install-anchor · CLI on PATH
---

# `/install-anchor`

**Best used:** first-time machine setup or any session where `anchor` is
missing/broken on **PATH**. See [Skills overview](/skills/overview).

Ensure the **`anchor` CLI** is available as a shell command on your machine.

## Why

Scaffolding (`anchor <project>` or `cd project && anchor`) is awkward if the
command is not on `PATH`. This skill inspects the OS/shell, finds your Anchor
checkout, and **safely** registers `anchor` — prefer a **user-local symlink**,
no sudo by default.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/install-anchor` | Status + recommended install; **confirm** before writing |
| `/install-anchor --status` | Inspect only |
| `/install-anchor --fix` | Apply the safe fix after recap |
| `/install-anchor --bin-dir ~/bin` | Put the symlink in that directory |

## What “safe” means

- **User-writable bindir** first: `~/.local/bin` (or `~/bin` / `--bin-dir`)
- **Symlink** to `$ANCHOR_ROOT/bin/anchor` (tracks the git checkout)
- **No sudo** / no `/usr/local/bin` unless you explicitly ask
- **No silent overwrite** of a different tool also named `anchor`
- **Confirm** before creating symlinks or editing shell rc for PATH

Packaged install (`pip install -e .` / `pipx`) is optional and only if you
request it — see [The anchor CLI](/tooling/cli#install).

## Install paths

| Platform | Location |
|----------|----------|
| Grok Build | `.grok/skills/install-anchor/SKILL.md` |
| Claude Code | `.claude/commands/install-anchor.md` |

## Verify

```bash
command -v anchor
anchor --list
anchor --help
```

If you only updated PATH in one session, open a new shell (or `source` your rc)
so other terminals pick it up.
