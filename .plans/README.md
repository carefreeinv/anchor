# `.plans/` — tracked work plans

**Start here:** run **`/work`** in your coding agent (optional: `/work --list`,
`/work <slug>`, `/work --no-fit-check`). Do not re-derive priority from chat.

Plans are **git-tracked markdown** under this **dotdir**. Do **not** gitignore
the whole `.plans/` tree. Exception: `*.local.md` plans are ignored via
`.plans/.gitignore` (private/dev work you don't want committed). Many UIs hide
dotfolders — always use the explicit path `.plans/`.

## Lanes

| Path | Execute? | Complete (`git mv` → `completed/`)? |
|------|----------|-------------------------------------|
| `bugs/` | **yes** (highest priority) | **yes** |
| `features/` | **yes** (after all bugs) | **yes** |
| `drafts/` | **no** (edit only) | **no** |
| `completed/` | **no** (archive) | n/a |

## Agent move rule (hard)

The **only** allowed agent move of a plan file inside `.plans/` is:

```text
.plans/bugs/<slug>.md   ──git mv──►  .plans/completed/   (when Done when holds)
.plans/features/<slug>.md ──git mv──►  .plans/completed/   (when Done when holds)
```

Agents must **never**:

- Promote: `drafts/` → `bugs/` or `features/`
- Demote: ready lane → `drafts/`
- Move between `bugs/` and `features/`
- Move anything out of `completed/`

**Promotion is human-only.** Humans run `git mv` from `drafts/` into `bugs/` or
`features/` and set `Status: ready`. Agents may write or edit under `drafts/`,
and may set `Status:` / `## Progress` in place, but must not relocate the file
except into `completed/` after true completion.

If a draft is named for execution: refuse; offer edit-only; tell the human to
promote when ready. Agents never run the promote `git mv`.

## How to start

1. `/work` — next ready plan by priority + **model fit** (`Preferred models`)
2. `/work --list` — inventory only (shows Preferred models + fit)
3. `/work <slug>` or `/work .plans/features/foo.md` — named plan
4. `/work --no-fit-check` — same priority pick, ignore model-fit filter (still
   **one** plan, not the whole backlog)

Headless/fleet: `python scripts/orchestrate.py --plan-file .plans/features/foo.md`
(refuses paths under `drafts/` or `completed/`).

## Priority (bare `/work`)

1. All `bugs/*.md` before any feature
2. Then `features/*.md` by header `Value: high | medium | low` (default medium)
3. Keep only **model-fit** plans unless `--no-fit-check` or user names a plan
4. Never `drafts/`, `completed/`, or this README

## Write / promote / finish

```text
Write:    agents/humans → .plans/drafts/<slug>.md until ready
Promote:  **human only** → git mv drafts/ → bugs/ or features/; Status: ready
Execute:  /work → follow Steps; verify each step
Finish:   agent: Status: done → git mv → .plans/completed/ (optional YYYY-MM-DD-<slug>.md)
```

Mid-session stop: leave in ready lane with `Status: in_progress` and a short
`## Progress` note. Do **not** move to `completed/`.

## Plan header (recommended)

```markdown
# Plan: <title>

- **Lane:** bugs | features | drafts
- **Value:** high | medium | low    # features only
- **Status:** draft | ready | in_progress | done
- **Slug:** <filename-without-md>
- **Preferred models:** <names and/or tiers>

## Goal
...
```

Body sections match `anchor/templates/plan.md`. **Preferred models** uses tiers
`small | mid | reasoner | frontier` and/or concrete names so `/work` can leave
work for cheaper or stronger models.

## Cross-model handoff

| Role | Writes / reads |
|------|----------------|
| Planner (NIM, local, human) | Write under `drafts/` only; **human** promotes when ready |
| Executor (`/work`, Fable, Sonnet, Grok, …) | Only `bugs/` + `features/`; sole move is → `completed/` when done |
| Critic | Plan **Done when** + diff |

Plans must be **self-contained** (Goal, Steps with verify commands, Done when).
Executors open the file first; do not re-plan unless Done when is impossible.

## Naming

- Tracked: `kebab-case-slug.md` — **Slug** is the stem without `.md`
- Untracked (local-only): `kebab-case-slug.local.md` — same **Slug** without
  the `.local` suffix; gitignored by `.plans/.gitignore` (`**/*.local.md`)
- `/work <slug>` matches either `slug.md` or `slug.local.md` under ready lanes
- Optional on completion: `YYYY-MM-DD-<slug>.md` (or `…local.md`) under `completed/`

Use `.local.md` for experiments, machine-specific notes, or work that should
not leave the developer machine. Promote to a tracked name (drop `.local`) when
the plan should be shared: `git mv .plans/drafts/foo.local.md .plans/drafts/foo.md`
(then human-promote lane as usual).

## Checker

Optional: `python3 scripts/check_plans.py` (lane placement, required sections).
