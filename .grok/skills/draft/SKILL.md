---
name: draft
description: >
  Planning mode for ./.plans/drafts: create, list, load/discuss existing drafts,
  and promote a draft to bugs/ or features/ when the user asks. Use when the user
  runs /draft, asks to draft a plan, list drafts, open a draft, or promote a draft.
argument-hint: "[--list|--load|--promote|--local] [slug|topic…]"
disable-model-invocation: false
metadata:
  short-description: "Drafts: create, list, load, promote"
---

# /draft — planning mode → `./.plans/drafts`

Operate on plans under **`.plans/drafts/`**. Modes: **create/refine**, **list**,
**load/discuss**, and **promote** (to the ready lane the plan implies: `bugs/`
or `features/`) when the user explicitly requests promote.

Do **not** implement product code in this skill. Do **not** run `/work` here.
Promotion is allowed **only** via the promote subcommand below — never as a
side effect of create/load, and never from `/work` or fleet pullers.

Many UIs hide dotfolders — use paths under `.plans/` explicitly.

`$ARGUMENTS` is everything after `/draft`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/draft` | Create a new draft from the conversation goal |
| `/draft <topic…>` | Create; slug from topic (kebab-case) |
| `/draft <slug>` | **If file exists:** load it for discussion (see Load). **If not:** create |
| `/draft --load <slug>` | Load existing draft for discussion (error if missing) |
| `/draft --list` | List all drafts (tracked + `.local.md`); do not implement |
| `/draft --promote <slug>` | Move draft → `bugs/` or `features/` (agent **infers** lane from plan) |
| `/draft promote <slug>` | Same as `--promote` |
| `/draft --local …` | New/refine path uses `<slug>.local.md` |
| `/draft local …` | Alias for `--local` |

Flags may appear anywhere. Remaining non-flag tokens are topic/slug.

## Local flag (create/refine only)

| Mode | Filename under `drafts/` | Git |
|------|--------------------------|-----|
| default | `<slug>.md` | Tracked |
| `--local` / `local` | `<slug>.local.md` | Ignored via `.plans/.gitignore` |

Promote keeps the same basename (`foo.md` or `foo.local.md`) in the ready lane.

## Resolve draft path

Search `.plans/drafts/` for (in order):

1. Exact path if user passed `.plans/drafts/...`
2. `<slug>.md` then `<slug>.local.md` (and reverse if `--local` was set)
3. Unique prefix match on filenames; if ambiguous, list matches and stop

## Mode: list

```bash
ls -la .plans/drafts
```

For each `*.md` / `*.local.md` (skip `.gitkeep`): print path, local vs tracked,
and one-line Goal (or first heading) if cheap to read. Do not implement. Stop.

## Mode: load / discuss

When the draft **exists** and the user did not ask to promote-only:

1. Read the **full** file.
2. Restate **Goal**, **Preferred models**, **Depends on**, **Done when**, and
   Steps outline in ≤15 lines.
3. Open discussion: questions, gaps, dep risks, Preferred models fit — do **not**
   silently rewrite the whole plan.
4. Apply edits only when the user asks to change something (or clearly wants a
   full refine pass). Write back to the **same** path under `drafts/`.
5. Offer next actions: keep discussing, refine sections, or
   `/draft --promote <slug>` then `/work`.

`--load <slug>` fails if missing (do not create). Bare `/draft <slug>` creates
only when no matching draft file exists.

## Mode: create / refine (new or explicit rewrite)

1. Ensure `.plans/drafts/` exists.
2. Inventory `.plans/**` for **Depends on** / duplicates; read conventions + enough code.
3. Write `anchor/templates/plan.md` shape: Value, Slug, Preferred models, Depends on,
   Goal, Context, Constraints, Steps, Risks, Done when. No `Lane:` / `Status:`.
4. Path only under `drafts/`. Report path; do not promote unless asked.

## Mode: promote (user-authorized)

**Only** when args include `--promote` or bare `promote` plus a resolvable
slug/path. Do **not** require a `bugs`/`features` flag — **infer the ready lane
from the plan body** (and optional user wording).

1. Resolve the draft file under `.plans/drafts/` (must exist); read it fully.
2. **Choose lane** (`bugs/` vs `features/`) using the plan, in order:
   - Explicit user override in this turn only (“promote as a bug”, “to features”)
     if they said so without needing a flag in the skill syntax.
   - **Bug signals:** Goal/title about fix, regression, crash, incorrect behavior,
     “bug”, broken test, security hole; no product **Value:** field or Value omitted
     for a pure fix; Steps are restore/repair rather than new capability.
   - **Feature signals:** new capability, add/support/enable, refactor-as-product,
     header **Value:** high|medium|low present; expansion of surface area.
   - If still ambiguous: ask **one** clarifying question (bug fix vs feature) and
     stop — do not guess silently.
3. Target dir: only `.plans/bugs/` or `.plans/features/` — never `in-progress/`,
   `completed/`, `ambiguous/`, `blocked/`.
4. Refuse if target basename already exists (report both paths; stop).
5. Prefer `git mv` when tracked; else `mv`. Create the target dir if needed.
6. Do **not** start `/work` unless the user immediately asks.
7. Report old path → new path **and** the inferred lane + one-line reason
   (e.g. `features/ — Value: high + “add fleet-watch skill” Goal`).

Pre-promote sanity (warn, don’t block unless catastrophic):

- Missing Goal or Done when → warn and ask once to confirm promote anyway.
- Unmet **Depends on** → warn; promote still allowed if user insisted with promote.
- If the plan looks half-baked for a ready lane → warn; offer stay in drafts.

## Planning rules (all modes)

1. **No product implementation** outside the plan file.
2. **No promote** except Mode: promote.
3. **No execute** of Steps (that is `/work` on a ready plan).
4. Path is authoritative — no `Lane:` / `Status:` fields.
5. Fit check / Preferred orchestrator: escalate architecture if this session is a
   poor fit; temporary coordinator only for frontier/near-frontier when unset.

## Argument parse order

1. `--list` / `-l` → list; stop.
2. `--promote` or bare `promote` → promote (infer bugs vs features from plan).
3. `--load` → require slug; load/discuss.
4. `--local` / bare `local` → local filename for create/refine.
5. Else slug/topic → load if exists, else create.

Ignore obsolete tokens `bugs`/`features` immediately after `--promote` if a user
still types them; treat as optional override of inferred lane.

## Output footer

```text
## Result
(mode; paths; promote from→to if any)
## How to verify
(ls / open file / git status)
## Deferred / concerns
(open questions; promote readiness; deps)
```

## Out of scope

- Implementing plan Steps
- Promoting without explicit promote args (or clear “promote this to features”
  language that you treat as promote mode)
- Promoting from `/work`, `work_once`, or fleet-watch
- Documenting draft backlog as product docs

## Quick discovery

```bash
ls -la .plans/drafts
ls .plans/bugs .plans/features .plans/in-progress \
   .plans/ambiguous .plans/blocked .plans/completed 2>/dev/null
```
