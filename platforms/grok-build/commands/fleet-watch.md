# /fleet-watch — durable plan watchers (Grok Build)

<!-- Canonical: .grok/skills/fleet-watch/SKILL.md -->

When the user types `/fleet-watch` (optional project name/path, `--status`, `--install`):

1. **Resolve project** — CWD/git root if `.plans/` exists; or `foo-project` as
   `./foo-project` / `../foo-project`; or absolute path. Print absolute root.
2. **Status** then **recommend** mid (and optional small) workers with unique agent ids.
3. **Emit** durable user timers (via `fleet_watch.py` under the hood); give linger +
   enable instructions. **Install only** with clear consent (`--install`).
4. Do not dump script-flag docs unless something fails. Skill configures
   watchers; watchers run the work-style loop in the background (interactive
   paired work stays `/work`).

Full skill: `.grok/skills/fleet-watch/SKILL.md`.
