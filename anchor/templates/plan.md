# Plan: <title>

<!-- When writing into a repo that uses `./.plans`, agents save under drafts/
     until a human promotes to bugs/ or features/. The only agent git mv is
     ready-lane → completed/ when Done when holds. Private plans: use
     <slug>.local.md (gitignored). See `.plans/README.md`. -->

- **Lane:** bugs | features | drafts
- **Value:** high | medium | low          <!-- features only; omit for bugs -->
- **Status:** draft | ready | in_progress | done
- **Slug:** <filename without .md and without .local>
- **Preferred models:** <names and/or tiers — who should execute this plan>

## Goal
<one sentence — the user-visible outcome>

## Context read
<files/docs actually read to form this plan>

## Constraints
- <hard constraints: language, versions, style, perf, no-touch zones>

## Conventions
<language/framework from ANCHOR-CONVENTIONS.md (or detected/asked directly) + its idiomatic composition mechanism — see anchor/ANCHOR.md "Code quality defaults". SOLID applies regardless.>

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

Use **model names** and/or **tiers** (see `anchor/ANCHOR.md` routing + `anchor/model-fitness.md`):

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
