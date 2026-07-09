---
description: Configure durable plan watchers for a project (.plans/ timers that survive reboot)
argument-hint: "[project-name|path] [--status|--install] [--tiers mid,small]"
---

# /fleet-watch — durable plan watchers for a project

Make configuring always-on plan pullers **trivial**. Resolve the project, inspect
`.plans/`, recommend capability-tier workers, and emit or install **systemd user
timers** that survive reboot (with linger).

`$ARGUMENTS` is everything after `/fleet-watch`. You may use helper scripts under
the hood—**do not** turn the reply into a raw CLI tutorial.

## Project resolution

1. Absolute / `~/` path in args → that root  
2. First non-flag token as name → `./name`, `../name` (e.g. from Anchor repo), etc., if it has or will have `.plans/`  
3. Else CWD or git root if `.plans/` exists  
4. Else ask once  

Print the resolved absolute path.

## Flow

| Args | Do |
|------|-----|
| (none or project only) | Status → recommend mid (+ small) workers → `--emit systemd` → short enable/linger instructions; offer install |
| `--status` | Status only |
| `--install` | Status + install recommended timers (confirm if consent unclear) |
| `--tiers mid,small` | Constrain proposed workers |

Find `scripts/fleet_watch.py` (Anchor `scripts/` or project fleet copy). Example:

```bash
python3 "$SCRIPTS/fleet_watch.py" --project "$PROJECT" --status
python3 "$SCRIPTS/fleet_watch.py" --project "$PROJECT" --emit systemd \
  --worker tier=mid,agent=<user>-<slug>-mid,interval=5m
```

Install only with clear consent: `--install-user --yes`. Stress  
`loginctl enable-linger $USER` for reboot without login.

## Rules

- Unique agent ids per concurrent watcher  
- No draft promotion; ignore foreign `in-progress/`  
- This chat **configures** watchers; watchers run the work-style claim/execute
  loop in the background. Interactive paired execution remains `/work`.  
- Prefer user timers over system units  

## Footer

`## Result` / `## How to verify` / `## Deferred / concerns` — project path, agent ids, timer names, linger, install yes/no.
