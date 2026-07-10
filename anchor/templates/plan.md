# Plan: <title>

<!-- When writing into a repo that uses `./.plans`, use /draft (planning mode)
     so agents save under drafts/ until a human moves the file into bugs/ or
     features/. The only agent git mv is ready-lane → completed/ when Done when
     holds. Private plans: /draft --local → <slug>.local.md (gitignored). See
     `.plans/README.md`.

     Path is authoritative — do NOT put Lane: or Status: in the file.
     drafts/ = not ready · bugs|features/ = ready · completed/ = done. -->

- **Value:** high | medium | low          <!-- features only; omit for bugs -->
- **Priority:** P1 | P2 | P3               <!-- P1 > P2 > P3; default P2 if omitted; orders within a lane -->
- **Slug:** <filename without .md and without .local>
- **Preferred models:** <names and/or tiers — who should execute this plan>
- **Depends on:** <comma-separated plan slugs, or `none`>  <!-- other .plans work that must be done first -->

## Goal
<one sentence — the user-visible outcome>

## Context read
<files/docs actually read to form this plan>

## Dependencies (how to fill)

Before finalizing this plan, **inventory existing plans** under `.plans/` (all lanes:
drafts, bugs, features, in-progress, ambiguous, blocked, completed). For each other
plan, read at least its Goal (and Done when if present) and decide whether *this*
work should wait on it:

- Shared modules, APIs, or scaffolds that plan must land first → list its **Slug**
- Same problem already tracked elsewhere → depend on it or merge; do not duplicate
- Only soft thematic overlap → do **not** depend; mention under Context if useful

Write slugs in **Depends on** (header). Executors **must not** start this plan while
any dependency is unmet (still open outside `completed/`, and not evidenced complete
in git history of `completed/`). Use `none` if you truly checked and found none.

Optional detail list:

```markdown
## Depends on (detail)
- `other-slug` — why this blocks us
```

## Constraints
- <hard constraints: language, versions, style, perf, no-touch zones>

## Conventions
<language/framework from ANCHOR-CONVENTIONS.md (or detected/asked directly) + its idiomatic composition mechanism — see .anchor/ANCHOR.md "Code quality defaults". SOLID applies regardless.>

## Steps
| # | Task | Touches | Verify by | Route to |
|---|------|---------|-----------|----------|
| 1 | <atomic task> | <files> | <command/check> | <model tier> |

## Risks
- <risk → mitigation>

## Escalation triggers
- Ambiguous requirement discovered → back to planner
- Task fails verification twice → bigger model
- Architectural decision needed → bigger model / human
- Step looks overqualified for its assigned tier (boilerplate/rename/formatting on a frontier route) → downgrade to smaller/local model instead

## Done when
- <machine-checkable conditions, all must hold>

---

### Preferred models (for plan drafters)

Fill **Preferred models** from plan complexity so cheap/capable executors find the right work and expensive tiers leave it alone. `/work` skips poor-fit plans unless the user names the plan or passes `--no-fit-check` (still one plan — not the whole backlog).

Use **model names** and/or **tiers** (see `.anchor/ANCHOR.md` routing + `.anchor/model-fitness.md`):

| Tier | Typical models | Good for |
|------|----------------|----------|
| `small` | Haiku, Qwen3 4–8B, Gemma 3 12B | Boilerplate, renames, formatting, thin docs |
| `mid` | Sonnet-class, Grok 4.5, Qwen3 32B, GPT Terra | Scoped multi-file features, refactors, routine reviews |
| `reasoner` | Opus-class, Nemotron thinking-on, R1 distill | Architecture, deep single-bug, security-adjacent |
| `frontier` | Fable-class | Multi-hour autonomy, large migrations, multi-service debug |

Examples:

- `mid` — any solid executor; not worth frontier credits
- `Claude Sonnet 5, Grok 4.5, Qwen3 32B` — named fleet picks
- `reasoner, frontier` — needs a strong reasoner; small/mid should skip
- `small, mid` — keep frontier/Opus off this work

Omit only when unsure; default assumption for executors is **mid**. Per-step **Route to** still applies inside the plan for mixed-difficulty steps.
