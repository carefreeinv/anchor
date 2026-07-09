---
description: Draft plans under ./.plans/drafts — create, list, load/discuss, promote (infer bugs vs features)
argument-hint: "[--list|--load|--promote|--local] [slug|topic…]"
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
| `/draft` | Create draft from conversation goal |
| `/draft <topic…>` | Create; slug from topic |
| `/draft <slug>` | **Exists → load/discuss**; missing → create |
| `/draft --load <slug>` | Load existing draft for discussion (must exist) |
| `/draft --list` | List `.plans/drafts/` (Goal one-liners if cheap) |
| `/draft --promote <slug>` | Move draft → `bugs/` **or** `features/` (**infer** from plan) |
| `/draft promote <slug>` | Same |
| `/draft --local …` | Create/refine as `<slug>.local.md` |

No `bugs`/`features` flag required on promote. Read the plan and choose the lane.

## Modes

### List
`ls` drafts; table path · local? · Goal snippet. Stop.

### Load / discuss
Read full draft; restate Goal / Preferred models / Depends on / Done when / Steps
outline; discuss gaps; edit only when asked; stay under `drafts/`.

### Create / refine
Template `anchor/templates/plan.md`; inventory deps; write only under `drafts/`.
No `Lane:`/`Status:`.

### Promote (explicit only)
Resolve draft under `drafts/`; read fully; **infer** ready lane:

| Prefer `bugs/` when… | Prefer `features/` when… |
|----------------------|---------------------------|
| Fix / regression / crash / incorrect behavior | New capability, add/support/enable |
| Repair existing behavior | Header **Value:** high\|medium\|low |
| Pure defect language in Goal | Expansion of product surface |

If ambiguous: ask once (bug vs feature), then stop. Optional user wording
(“as a bug”, “as a feature”) overrides. Then `git mv` (or `mv`) to
`.plans/bugs/` or `.plans/features/` same basename; refuse if target exists;
warn if Goal/Done when thin or Depends on unmet; do not auto-`/work`. Report
path + inferred lane + one-line reason.

## Footer

`## Result` · `## How to verify` · `## Deferred / concerns`
