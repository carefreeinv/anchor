# Plan: <title>

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
