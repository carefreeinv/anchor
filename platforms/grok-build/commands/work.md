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
     Bare `/work`: skip over/under-qualified and unmet-deps plans. See full skill
     (Grok 4.5 is **mid-class**; high `reasoning_effort` is a cost dial, not a
     tier promotion).
   - **Cheaper capacity + effort:** before hard-skipping overqualified or burning
     high effort on `small`/`mid`, probe `scripts/endpoints.yaml` / local models
     for a lesser reachable executor; if none, emit pasteable `/effort low` (or
     `--effort low`) for this session. Full skill: “Cheaper capacity probe” +
     “Reasoning effort / same-model cost right-size”.
   - **`--no-fit-check` / dep override:** only when user insists; still one plan; state mismatch.
   - **Never execute** `drafts/` / `completed/` / `ambiguous/` / `blocked/`.
   - **Agent moves:** claim → `in-progress/`; finish → `completed/`; park →
     `ambiguous/`|`blocked/`; release → ready. Never promote drafts; never steal
     foreign in-progress (promote drafts via `/draft --promote` only).
2. **`--list`:** ready plans (+ your in-progress) with Preferred models, fit, deps;
   optional suggested effort / cheaper endpoint; stop.
3. **No args:** pick highest-priority **good-fit** plan (menu if several and
   user did not say “just pick”). On good-fit `mid` work at high effort: note
   `/effort low` then execute. If every plan is a poor fit, list them, report
   capacity probe + pasteable effort/dispatch commands, and stop — also
   `--no-fit-check` or a stronger/cheaper session. **Slug/path:** resolve under
   ready lanes only (`slug.md` or `slug.local.md`); state any fit mismatch, then
   proceed (explicit target = override).
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
