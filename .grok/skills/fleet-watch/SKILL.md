---
name: fleet-watch
description: >
  Configure durable multi-tier plan watchers for a project via /fleet-watch.
  Resolve the project from CWD or a name/path argument, inspect .plans/, and
  emit or install reboot-persistent systemd user timers. Use when the user runs
  /fleet-watch, wants background plan pollers, or asks to watch a project for
  new ready plans.
argument-hint: "[project-name|path] [--status|--install] [--tiers mid,small]"
disable-model-invocation: false
metadata:
  short-description: "Watch a project .plans/ with durable timers"
---

# /fleet-watch — durable plan watchers for a project

Make it **trivial** to configure always-on pullers for a project’s **`.plans/`**
tree. You resolve the project, inspect status, propose capability-tier workers,
and print or install **systemd user timers** that survive reboot (with linger).

This skill is the product UX. Helper scripts (`fleet_watch.py`, `work_once.py`)
are implementation detail—use them; do not force the user to learn their flags.

The **skill session** only configures watchers. The **watchers** apply a
work-style loop (claim → execute → complete) in the background—one plan per
tick (pull model). Interactive “work this plan with me now” remains `/work`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/fleet-watch` | Project = CWD / git root if it has `.plans/`; then status + recommend setup |
| `/fleet-watch foo-project` | Resolve project by name (see below), then same |
| `/fleet-watch /abs/path` | Explicit root |
| `/fleet-watch --status` | Inspect only |
| `/fleet-watch --install` | Status + install recommended user timers (**confirm** if intent unclear) |
| `/fleet-watch --tiers mid,small` | Prefer those tiers when proposing workers |

`$ARGUMENTS` is everything after `/fleet-watch`.

## 1. Resolve project root

Apply in order; stop at first hit that contains `.plans/` (or will be scaffolded):

1. **Absolute path** token (`/…` or `~/…` expanded).
2. **Explicit** `--project PATH` if present.
3. **Named project** first non-flag token:
   - `./name` or `name` under CWD
   - `../name` (sibling of CWD)—common when CWD is the Anchor repo
   - `name` under git root’s parent
4. **CWD** if `./.plans` exists.
5. **Git root** of CWD if `<git-root>/.plans` exists.
6. Otherwise **ask once** for the project path (do not guess silently).

Print the resolved absolute path before acting.

If `.plans/` is missing: explain scaffold (`anchor <project> …`) and stop unless
the user wants only an install plan for after scaffold.

## 2. Resolve Anchor scripts (quietly)

Find a directory that contains `fleet_watch.py` and `work_once.py`:

- `$(git rev-parse --show-toplevel)/scripts` when inside Anchor
- or `scripts/` under the target project if fleet-scaffolded
- or absolute Anchor install the user already uses

Do not dump a script tutorial in the reply unless something fails.

```bash
python3 "$SCRIPTS/fleet_watch.py" --project "$PROJECT" …
```

## 3. Default flow (no special flags)

1. **Status** — run `fleet_watch.py --project "$PROJECT" --status`. Summarize:
   plan counts per lane, preferred orchestrator if set, existing `anchor-watch-*`
   timers, linger on/off.
2. **Recommend workers** if none installed (sensible defaults when user is vague):

   | Tier | agent-id pattern | interval |
   |------|------------------|----------|
   | mid | `<user>-<projectslug>-mid` | 5m |
   | small | `<user>-<projectslug>-small` | 10m |

   Add reasoner only if the user asked or plans prefer reasoner/frontier often.
   Unique agent ids are mandatory (in-progress ownership).

3. **Emit** durable config (do not install yet):

   ```bash
   python3 "$SCRIPTS/fleet_watch.py" --project "$PROJECT" --emit systemd \
     --worker tier=mid,agent=<id>,interval=5m \
     --worker tier=small,agent=<id2>,interval=10m
   ```

4. **Present a short “do this” block** to the user:
   - enable linger: `loginctl enable-linger $USER`
   - enable timers (names from emit output), **or** offer  
     `/fleet-watch --install` / re-run with consent to use `--install-user --yes`
5. Optional smoke only if useful: `--once` for one tier (exit 1 = idle is OK).

## 4. Flags

- **`--status`** — stop after status (no emit/install).
- **`--install`** — after status, install user timers with recommended (or
  `--tiers`) workers. If the user did not clearly ask to install, confirm first.
  Use `fleet_watch.py --install-user --yes …`.
- **`--tiers a,b`** — limit proposed/installed workers to those fit tiers.
- **`--emit cron`** — only if user prefers cron over systemd.

## 5. Rules to restate briefly

1. Pull one plan per tick; no central assigner; no auto-promote.
2. Claim → `in-progress/`; only that agent-id continues; others ignore.
3. Watchers ≠ preferred orchestrator for architecture.
4. Prefer user timers + linger over system units unless user demands root.

## Output footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: resolved project path, worker agent-ids, timer unit names, linger state,
whether install ran or only recommendations.

## Out of scope

- Stepping through a plan’s tasks **in this chat** (use `/work` for interactive;
  background work-style execution is what installed watchers do)
- Promoting drafts
- Teaching the full `fleet_watch.py` CLI (point at tooling docs if asked)
- `--install-user` without consent when intent is status-only
