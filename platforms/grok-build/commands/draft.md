# /draft — drafts create / list / load / promote (Grok Build)

<!-- Canonical: .grok/skills/draft/SKILL.md -->

When the user types `/draft` (args optional):

1. **`--list`:** list `.plans/drafts/` (path, local?, Goal line); stop.
2. **`--promote <slug>`** or **`promote <slug>`:** read the draft; **infer**
   `bugs/` vs `features/` from Goal/Value/wording (no lane flag required);
   optional user “as bug/feature” overrides; `git mv` to that lane with the
   **same basename** (keep `.local.md` if present — never drop it); refuse if
   target exists; do not implement; do not auto-`/work`. State lane + reason.
3. **`--load <slug>`** or **`<slug>` that already exists:** read full draft;
   restate Goal/Steps/Done when; discuss; edit only if asked; stay in `drafts/`.
4. **Else create/refine** under `.plans/drafts/` (`--local` / `local` →
   `<slug>.local.md`). Template: plan.md. Plan only — no product code.
5. Promote **only** when promote args (or clear “promote this draft”) are
   present — not as a side effect of draft/load.

Canonical long form: `.grok/skills/draft/SKILL.md`.
