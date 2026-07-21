---
description: Draft plans under ./.plans/drafts — create, list, load/discuss, promote (infer bugs vs features)
argument-hint: "[--list|--load|--promote|--shared|--local] [slug|topic…]"
---

# /draft — planning mode → `./.plans/drafts`

Operate on **`.plans/drafts/`**: create/refine, **list**, **load/discuss**, or
**promote** to a ready lane when the user explicitly requests promote.

Do **not** implement product code. Do **not** promote except via the promote
subcommand. Do not run `/work` here.

`$ARGUMENTS` is everything after `/draft`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/draft` | Create draft (**`<slug>.local.md`** — private/uncommitted by default) |
| `/draft <topic…>` | Create; slug from topic (`.local.md` by default) |
| `/draft <slug>` | **Exists → load/discuss**; missing → create (`.local.md`) |
| `/draft --load <slug>` | Load existing draft for discussion (must exist) |
| `/draft --list` | List `.plans/drafts/` (Goal one-liners if cheap) |
| `/draft --promote <slug>` | Move draft → `bugs/` **or** `features/` (**infer** from plan); **keep basename** (incl. `.local.md`) |
| `/draft promote <slug>` | Same |
| `/draft --shared …` | Create/refine as a **tracked** `<slug>.md` (committable draft) instead of the default |
| `/draft --local …` | Explicitly private `<slug>.local.md` (this is already the default) |

No `bugs`/`features` flag required on promote. Read the plan and choose the lane.

**Fresh drafts are private by default** — created as `<slug>.local.md` (gitignored
via `.plans/.gitignore`). **`.local` is sticky:** promote and later agent lane
moves keep the same filename; agents never drop `.local`. Only a **human manual
rename** can make a local plan tracked (or use `--shared` when **creating** a new
draft that should be tracked from the start).

## Modes

### List
`ls` drafts; table path · local? · Goal snippet. Stop.

### Load / discuss
Read full draft; restate Goal / Preferred models / Depends on / Done when / Steps
outline; discuss gaps; edit only when asked; stay under `drafts/`.

### Create / refine
Template `.anchor/templates/plan.md`; inventory deps; write only under `drafts/`.
No `Lane:`/`Status:`. **Default filename is `<slug>.local.md`** (private,
gitignored — the user may not be ready to commit a fresh draft). Use `--shared`
(alias `--tracked`) to write a committable `<slug>.md` instead. When refining an
existing draft, keep its current suffix.

**Human-owned plans:** if the work must be completed by a person (release
sign-off, manual QA, anything gated on human judgment/access), set
`- **Assignee:** <name|username|email>` (or `human`) in the header. The plan
body stays normal; agents auto-skip claiming it but may still update its
status/comments. Absent or `ai` = agent-eligible (the default).

### Promote (explicit only)
Resolve draft under `drafts/`; read fully; **infer** ready lane:

| Prefer `bugs/` when… | Prefer `features/` when… |
|----------------------|---------------------------|
| Fix / regression / crash / incorrect behavior | New capability, add/support/enable |
| Repair existing behavior | Header **Value:** high\|medium\|low |
| Pure defect language in Goal | Expansion of product surface |

If ambiguous: ask once (bug vs feature), then stop. Optional user wording
(“as a bug”, “as a feature”) overrides. Then `git mv` (or `mv`) to
`.plans/bugs/` or `.plans/features/` with the **same basename** (keep
`.local.md` if present — do not drop it). Refuse if target exists; warn if
Goal/Done when thin or Depends on unmet; do not auto-`/work`. Report path +
inferred lane + one-line reason (note if still private).

## Footer

`## Result` · `## How to verify` · `## Deferred / concerns`
