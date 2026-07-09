# `.plans/` — tracked work plans

**Start here:** run **`/work`** in your coding agent (optional: `/work --list`,
`/work <slug>`, `/work --no-fit-check`). Do not re-derive priority from chat.

Plans are **git-tracked markdown** under this **dotdir**. Do **not** gitignore
the whole `.plans/` tree. Exception: `*.local.md` plans are ignored via
`.plans/.gitignore` (private/dev work you don't want committed). Many UIs hide
dotfolders — always use the explicit path `.plans/`.

## Documentation vs plans (hard rule)

**Docs describe the project’s current shipped state — not plans.** README, `docs/`,
CHANGELOG, blog, and public prose must not restate the **contents** of this tree
(drafts, ready backlog, in-progress bodies, unfinished acceptance items) as product
docs or roadmap. When work from a plan ships, document the code and public contract
— not the plan file. Documenting how **this workflow** works (lanes, `/work`, path
rules) is fine; documenting “what we plan to build next” from plan files is not.

## Path is authoritative

**Lane and lifecycle status live only in the filesystem path.** Humans move
files freely; do **not** put `Lane:` or `Status:` inside plan markdown.

| Path | Meaning | Who may execute? |
|------|---------|------------------|
| `bugs/` | ready bug work (highest priority) | any fit agent (then move → `in-progress/`) |
| `features/` | ready feature work | any fit agent (then move → `in-progress/`) |
| `in-progress/` | claimed / being worked | **only the agent that moved it there** |
| `ambiguous/` | half-baked / needs clarification | **no** (parked; not auto-picked) |
| `blocked/` | cannot proceed with current means | **no** (parked; not auto-picked) |
| `drafts/` | not ready (edit / design) | no one (edit only) |
| `completed/` | finished archive | no one |

## Agent move rule (hard)

Agents may relocate plan files **only** as follows:

```text
bugs|features/<slug>.md     ──mv──►  in-progress/     (starting work + lease)
in-progress/<slug>.md       ──mv──►  completed/       (Done when holds)
bugs|features|in-progress/  ──mv──►  ambiguous/       (half-baked / underspecified)
bugs|features|in-progress/  ──mv──►  blocked/         (cannot fix now)
in-progress/<slug>.md       ──mv──►  bugs|features/   (release claim for others)
ambiguous|blocked/<slug>.md ──mv──►  bugs|features/   (return when unblocked/clarified)
```

Also record ownership under `.plans/.leases/` (agent id + expiry) while in
`in-progress/`. Headless: `work_once.py` claim/park/return helpers.

Agents must **never**:

- Promote `drafts/` → ready **except** via explicit **`/draft --promote <slug>`**
  (agent infers `bugs/` vs `features/` from the plan; or clear user language
  handled by the `/draft` skill). `/work` and fleet pullers must **never** promote.
- Move ready/in-progress → `drafts/`
- Swap `bugs/` ↔ `features/` except via explicit return targeting a lane
- Move anything out of `completed/`
- **Touch another agent’s `in-progress/` plan** (ignore it)

If a draft is named for **execution** (`/work`): refuse; offer `/draft --load`
or `/draft --promote …` then `/work` on the ready path.

## How to start

0. **`/draft`** — planning mode on **`.plans/drafts/`**: create, `--list`,
   `--load` / open existing slug for discussion, optional `--local` →
   `*.local.md`. **Promote** with `/draft --promote <slug>` (infer bugs vs
   features from the plan). Does not implement product work.
1. `/work` — resume **your** `in-progress/` work if any, else next ready plan by
   priority + **model fit**
2. `/work --list` — inventory ready plans (+ your in-progress); **ignore others’**
3. `/work <slug>` or `/work .plans/features/foo.md` — named plan
4. `/work --no-fit-check` — same priority pick, ignore model-fit filter (still
   **one** plan, not the whole backlog)

Headless pull (companion to `/work`, not a replacement):

```bash
python scripts/work_once.py --list --tier mid --agent-id worker-1
python scripts/work_once.py --once --tier mid --agent-id worker-1   # → in-progress/
python scripts/work_once.py --max-plans 3 --tier small --agent-id swarm-a
```

Uses the same priority + Preferred-models rules; moves claimed plans into
`in-progress/` and writes leases under `.plans/.leases/` (gitignored). Prefer
one writer per clone/worktree.

**Multi-agent fleet:** unique `--agent-id` per worker; each ignores
`in-progress/` plans it did not claim. Full guide:
[Multi-agent fleet workers](https://carefreeinv.com/anchor/docs/tooling/fleet-workers)
(source: `docs/docs/tooling/fleet-workers.md`). Durable timers: run **`/fleet-watch`** in your coding agent (from the project, or
`/fleet-watch <name>` from Anchor)—see
[docs](https://carefreeinv.com/anchor/docs/skills/fleet-watch).

## Priority (bare `/work`)

1. **Your** plans already under `in-progress/` (resume first)
2. All `bugs/*.md` before any feature
3. Then `features/*.md` by header `Value: high | medium | low` (default medium)
4. Keep only **model-fit** plans unless `--no-fit-check` or user names a plan
5. Never `drafts/`, `completed/`, `ambiguous/`, `blocked/`, foreign `in-progress/`,
   or this README

## Write / promote / finish

```text
Write:    /draft → .plans/drafts/<slug>.md  (or <slug>.local.md with --local)
List:     /draft --list
Load:     /draft --load <slug>  (or /draft <slug> if file exists)
Promote:  /draft --promote <slug>  (infer bugs|features from plan; path = ready)
Claim:    agent → move into in-progress/ + lease (path = working)
Execute:  /work → follow Steps; verify each step
Park:     agent → ambiguous/ (half-baked) or blocked/ (cannot fix)
Release:  agent → bugs|features/ (give up claim; still ready for others)
Finish:   agent: git mv in-progress/ → completed/ (optional YYYY-MM-DD-<slug>.md)
Worktree: parallel agents use scripts/worktree_for_agent.py ensure
          --agent-id … [--slug …] (var/worktrees/<id>/); or work_once --ensure-worktree
Branch:   from **dev** (else **develop**); if neither exists, **create dev**
          from **main** (else **master**) and push origin when possible
Commit:   **/commit-prep** first (prep only: tests + CHANGELOG + blog); if green
          and plan complete, commit on feature branch (see /work); optional push
          of that branch only; never auto-merge to dev/main.
```

Mid-session stop: leave the file in **`in-progress/`** with a short `## Progress`
note. Do **not** move to `completed/`. Other agents must ignore that file.

Half-baked or stuck: move to **`ambiguous/`** or **`blocked/`** and note why in
`## Progress` / session footer. Unparking back to ready is allowed when the
blocker is cleared.

## Plan header (recommended)

```markdown
# Plan: <title>

- **Value:** high | medium | low    # features only; omit for bugs
- **Slug:** <filename-without-md>
- **Preferred models:** <names and/or tiers>
- **Depends on:** <slug-a, slug-b | none>

## Goal
...
```

**Do not** include `Lane:` or `Status:` — the directory is the marker.

### Dependencies

Plans may list other plan **slugs** they require first. When drafting or coordinating:

1. Inventory existing `.plans/**` (all lanes).
2. Compare goals — add **Depends on** when this work should wait on another plan.
3. Use `none` only after checking.

**Executors must not start** a plan while any dependency is unmet: still open outside
`completed/`, and not evidenced complete in git history of `.plans/completed/`.
Logical checks: open-lane presence wins over stale memory; completed file or git
history of completed/ satisfies. Coordinators (project MCP / planners) should
propose Depends on when discussing a plan.

Body sections match `anchor/templates/plan.md`. **Preferred models** uses tiers
`small | mid | reasoner | frontier` and/or concrete names so `/work` can leave
work for cheaper or stronger models.

## Cross-model handoff

| Role | Writes / reads |
|------|----------------|
| Planner (NIM, local, human) | Write under `drafts/` only; **human** moves when ready |
| Executor (`/work`, Fable, Sonnet, Grok, …) | Ready → own `in-progress/` → `completed/`; ignore others’ in-progress |
| Critic | Plan **Done when** + diff |

Plans must be **self-contained** (Goal, Steps with verify commands, Done when).
Executors open the file first; do not re-plan unless Done when is impossible.

## Naming

- Tracked: `kebab-case-slug.md` — **Slug** is the stem without `.md`
- Untracked (local-only): `kebab-case-slug.local.md` — same **Slug** without
  the `.local` suffix; gitignored by `.plans/.gitignore` (`**/*.local.md`)
- `/work <slug>` matches either `slug.md` or `slug.local.md` under ready lanes
  (or your own `in-progress/`)
- Optional on completion: `YYYY-MM-DD-<slug>.md` (or `…local.md`) under `completed/`

## Checker

Optional: `python3 scripts/check_plans.py` (path under a known lane, required
sections for executable lanes; flags obsolete `Lane:` / `Status:` headers).
