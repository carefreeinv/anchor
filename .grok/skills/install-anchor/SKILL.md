---
name: install-anchor
description: >
  Ensure the `anchor` CLI is safely available on PATH via /install-anchor.
  Identify OS/shell, locate the Anchor checkout, check existing registration,
  and symlink bin/anchor into a user-writable PATH dir when needed. Use when
  the user runs /install-anchor, asks to install or register the anchor
  command, or reports that `anchor` is not found.
argument-hint: "[--status|--fix] [--bin-dir PATH]"
disable-model-invocation: false
metadata:
  short-description: "Register the anchor command on PATH safely"
---

# /install-anchor — register the `anchor` CLI on PATH

Make `anchor` available as a shell command **without sudo**, without
overwriting an unrelated binary, and without requiring a full pip install.

Preferred method: **user-local symlink** from a directory already on `PATH`
(usually `~/.local/bin`) to this checkout’s `bin/anchor` wrapper.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/install-anchor` | Inspect system + status; if missing/broken, **propose** install and confirm before changing anything |
| `/install-anchor --status` | Inspect only; never write |
| `/install-anchor --fix` | After status, apply the safe fix (still confirm if intent is unclear) |
| `/install-anchor --bin-dir ~/bin` | Prefer that directory for the symlink (must be user-writable) |

`$ARGUMENTS` is everything after `/install-anchor`.

## Safety rules (hard)

1. **No sudo / no `/usr/local/bin`** unless the user **explicitly** asks for a system-wide install.
2. **Never overwrite** an existing `anchor` that does not clearly belong to this Anchor checkout without explaining the conflict and getting confirmation.
3. **Confirm before writes** (symlink create/replace, PATH line append). `--status` never writes. `--fix` may write after a short recap if the user already asked to fix/install.
4. Prefer **symlink → `bin/anchor`** over `pip install` (tracks the git checkout; fleet scripts stay out of the package).
5. Unix-first (Linux / macOS / WSL). Native Windows without WSL: report unsupported and stop (or document WSL path only).

## Steps

### 1. Identify the system

Run and summarize briefly:

```bash
uname -s
uname -m
echo "SHELL=$SHELL"
echo "HOME=$HOME"
echo "PATH=$PATH"
command -v python3 || true
python3 --version || true
```

Note: Linux, Darwin (macOS), or other. WSL often still reports `Linux`.

### 2. Locate the Anchor checkout

Find a directory that contains **both** `bin/anchor` and `scripts/anchor.py`:

1. Git root of CWD if it has those files.
2. Absolute path in `$ARGUMENTS` if given.
3. Walk parents of CWD for `bin/anchor` + `scripts/anchor.py`.
4. Common sibling: `../anchor` when CWD is another project under the same parent.
5. If still missing: ask once for the Anchor repo path.

Set `ANCHOR_ROOT` to that absolute path. Verify:

```bash
test -x "$ANCHOR_ROOT/bin/anchor"
head -5 "$ANCHOR_ROOT/bin/anchor"
"$ANCHOR_ROOT/bin/anchor" --list >/dev/null
```

### 3. Status of the `anchor` command

```bash
command -v anchor || true
type -a anchor 2>/dev/null || true
ls -la "$(command -v anchor)" 2>/dev/null || true
# If present, does it work and point at this checkout?
anchor --list 2>&1 | head -20 || true
readlink -f "$(command -v anchor)" 2>/dev/null || true
```

Classify:

| State | Meaning |
|-------|---------|
| **ok** | `anchor` on PATH, runs, resolves to this `$ANCHOR_ROOT` (or a pip install of this tree that still works) |
| **missing** | not on PATH |
| **broken** | on PATH but fails (`--list` errors) or points at a deleted path |
| **foreign** | on PATH but clearly another project/tool — do not replace without explicit user OK |

Print classification + evidence.

If **ok** and no `--fix`: stop with success (nothing to do).

### 4. Choose a safe bindir

Default candidates (first that is **writable** and ideally **already on PATH**):

1. `--bin-dir` if provided
2. `$HOME/.local/bin`
3. `$HOME/bin`

```bash
mkdir -p "$BINDIR"   # only after confirm, when installing
```

If the chosen dir is **not** on `PATH`, plan a PATH append for the user’s shell rc
(`~/.bashrc`, `~/.zshrc`, or `~/.config/fish/config.fish` from `$SHELL`) — **do not
edit rc without confirmation**. Suggest:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 5. Recommend (and optionally apply)

**Recommended action** (default):

```bash
ln -sfn "$ANCHOR_ROOT/bin/anchor" "$BINDIR/anchor"
# ensure BINDIR is on PATH (session + optional rc line)
hash -r 2>/dev/null || true
command -v anchor
anchor --list | head -5
```

Use `ln -sfn` so re-running updates the symlink to this checkout.

**Present draft findings** before any write:

- OS / shell
- `ANCHOR_ROOT`
- Current `anchor` state (ok / missing / broken / foreign)
- Proposed `BINDIR` and whether it is on PATH
- Exact commands you will run

Then ask to proceed (unless `--status`, or user already said `--fix` / “install it”).

**Do not** run `pip install` / `pipx install` unless the user asks for a packaged
install. If they do, prefer:

```bash
cd "$ANCHOR_ROOT"
python3 -m pip install --user -e .
# or: pipx install "$ANCHOR_ROOT"
```

and warn about old setuptools / use a venv (see README).

### 6. Verify

After install:

```bash
command -v anchor
anchor --help | head -15
anchor --list | head -10
```

Expect: `command -v anchor` under the chosen bindir; `--list` prints platform keys.

If PATH was only updated in this session, tell the user to open a new shell **or**
`source` their rc so other terminals see `anchor`.

## Output footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: OS, `ANCHOR_ROOT`, prior state, actions taken (or “status only”), final
`command -v anchor`, and whether a new shell is needed for PATH.

## Out of scope

- Scaffolding a project (`anchor <dir>` / `/config`)
- Installing fleet timers (`/fleet-watch`)
- System-wide install requiring root (only if user insists — spell the risk)
- Overwriting a foreign `anchor` binary without explicit confirmation
