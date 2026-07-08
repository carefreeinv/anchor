# /work — execute a tracked plan from `./.plans` (Grok Build)

<!-- Drop into the project as `.grok/skills/work/SKILL.md` (preferred) or a
     commands/work.md that your environment loads as `/work`. In the Anchor
     repo the live skill is `.grok/skills/work/SKILL.md`. -->

When the user types `/work` (optional args: `--list`, `--no-fit-check`, a plan
slug, or a path under `.plans/`):

1. **Inventory** ready plans under **`.plans/`** (dotdir — use that path; do not
   rely on a non-hidden `plans/` folder):
   - Execute only: `.plans/bugs/`, then `.plans/features/` (by `Value:`
     high → medium → low, default medium).
   - Filter by **model fit** using each plan’s **Preferred models** header
     (tiers: `small` | `mid` | `reasoner` | `frontier`, or concrete names).
     Bare `/work`: **skip** plans you are overqualified for (leave for cheaper
     models) or underqualified for (leave for stronger models). See full skill.
   - **`--no-fit-check`:** turn off that filter for this run only; still pick
     **one** plan (not the whole backlog); still state fit in one line.
   - **Never execute** `.plans/drafts/` or `.plans/completed/`.
   - **Agent move rule:** the only allowed relocate under `.plans/` is
     `bugs|features` → `completed/` when Done when holds. Never promote drafts
     or move between ready lanes (**promotion is human-only**).
2. **`--list`:** print ready plans with Preferred models + your fit; stop.
3. **No args:** pick highest-priority **good-fit** plan (menu if several and
   user did not say “just pick”). If every plan is a poor fit, list them and
   stop — suggest `--no-fit-check` or a stronger/cheaper session. **Slug/path:**
   resolve under ready lanes only (`slug.md` or `slug.local.md`); state any
   fit mismatch, then proceed (explicit target = override).
4. **Load** the full plan file; restate Goal + Preferred models + Done when
   (≤10 lines). Do not rewrite the plan unless a step is impossible.
5. Set `Status: in_progress` if the header supports it; **execute Steps** in
   order with verification commands; two failures on the same error → stop and
   escalate. Honor per-step **Route to**.
6. When **Done when** holds: `Status: done`, `git mv` → `.plans/completed/`,
   then the usual `## Result` / `## How to verify` / `## Deferred / concerns`
   footer. Mid-session stop → leave in ready lane with `## Progress`, do not
   complete.

Canonical long form (same contract): `.grok/skills/work/SKILL.md` in a project
that vendors this skill, or the Anchor repo copy of that file.
