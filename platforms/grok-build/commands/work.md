# /work — execute a tracked plan from `./.plans` (Grok Build)

<!-- Drop into the project as `.grok/skills/work/SKILL.md` (preferred) or a
     commands/work.md that your environment loads as `/work`. In the Anchor
     repo the live skill is `.grok/skills/work/SKILL.md`. -->

When the user types `/work` (optional args: `--list`, `--no-fit-check`, a plan
slug, or a path under `.plans/`):

1. **Inventory** ready plans under **`.plans/`** (dotdir — use that path; do not
   rely on a non-hidden `plans/` folder):
   - Resume **your** `.plans/in-progress/` first; else execute from `.plans/bugs/`,
     then `.plans/features/` (by `Value:` high → medium → low, default medium).
     **Ignore** foreign `in-progress/`. **Path is authoritative** — no `Lane:`/`Status:`.
   - Filter by **model fit** (**Preferred models**) and **Depends on** (skip unmet).
     Bare `/work`: skip over/under-qualified and unmet-deps plans. See full skill.
   - **`--no-fit-check` / dep override:** only when user insists; still one plan; state mismatch.
   - **Never execute** `drafts/` / `completed/` / `ambiguous/` / `blocked/`.
   - **Agent moves:** claim → `in-progress/`; finish → `completed/`; park →
     `ambiguous/`|`blocked/`; release → ready. Never promote drafts; never steal
     foreign in-progress (promote drafts via `/draft --promote` only).
2. **`--list`:** ready plans (+ your in-progress) with Preferred models, fit, deps; stop.
3. **No args:** pick highest-priority **good-fit** plan (menu if several and
   user did not say “just pick”). If every plan is a poor fit, list them and
   stop — suggest `--no-fit-check` or a stronger/cheaper session. **Slug/path:**
   resolve under ready lanes only (`slug.md` or `slug.local.md`); state any
   fit mismatch, then proceed (explicit target = override).
4. **Load** the full plan file; restate Goal + Preferred models + Done when
   (≤10 lines). Do not rewrite the plan unless a step is impossible. Resume
   from `## Progress` if present.
5. If still under bugs/features, **move to `in-progress/`** first; optionally
   note `## Progress`; **execute Steps** in order with verification commands;
   two failures on the same error → stop and escalate. Honor per-step **Route to**.
6. When **Done when** holds: `git mv` from `in-progress/` → `.plans/completed/`,
   then the usual footer. Mid-session stop → leave in **`in-progress/`** with
   `## Progress` (others ignore it).
7. **Docs rule:** product docs describe **current shipped state**, not plan
   backlog. Do not write README/docs/CHANGELOG from `.plans/` contents; when work
   ships, document the code — not the plan file.

Canonical long form (same contract): `.grok/skills/work/SKILL.md` in a project
that vendors this skill, or the Anchor repo copy of that file.
