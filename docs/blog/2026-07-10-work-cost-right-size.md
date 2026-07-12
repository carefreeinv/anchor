---
title: "/work now probes for cheaper capacity before it burns an expensive session"
authors: [carefree]
tags: [feature, tooling]
---

An expensive session hitting `/work` used to have two options on `small`/`mid`
Preferred work: skip it and leave the backlog stuck, or quietly do it anyway at
full cost. There's now a third: check whether something cheaper can actually
take it, and say so explicitly.

<!-- truncate -->

## The probe

Before `/work` hard-skips overqualified work — or spends a high-reasoning-effort
session on `small`/`mid` Preferred plans — it now checks `scripts/endpoints.yaml`
for a lesser, **reachable** executor. The registry tiers map onto Preferred-models
fit the same way `work_once.py` already reads them: `swarm`→`small`,
`executor`/`executor-heavy`/`detached`→`mid`, `reasoner`→`reasoner`,
`frontier`→`frontier`. Listed isn't the same as live — an unreachable worker
doesn't count as a delegation target.

If a cheaper endpoint is up, `/work` leaves the plan unclaimed and prints the
dispatch line instead of grabbing it itself:

```bash
python scripts/work_once.py --once --endpoint h100-executor --registry scripts/endpoints.yaml
```

## When nothing cheaper is reachable

If the fleet is dark or nothing registered fits, the session doing the checking
is the available executor — `/work` no longer permanently refuses `mid` work
just because it's overqualified. Instead it right-sizes its own cost and emits a
pasteable command for the current product:

| Product | Lower cost for `small`/`mid` | Raise for `reasoner`+ |
|---|---|---|
| Grok Build TUI | `/effort low` (or `/model <id> low`) | `/effort high` |
| Grok CLI / headless | `--effort low` | `--effort high` |
| Nemotron / Qwen3 hybrid | thinking off | thinking on |

High reasoning effort on a mid-class model is a **cost dial**, not a tier
promotion — a Grok 4.5 session at high effort is still `mid` for Preferred
matching, not overqualified for `mid` plans. `anchor/model-fitness.md` now says
so explicitly for Grok 4.5's row.

## Where it landed

The full contract lives in `.claude/commands/work.md` and its Grok mirror
`.grok/skills/work/SKILL.md`, ported into `platforms/grok-build/GROK.md` +
`platforms/grok-build/commands/work.md`, and documented on the
[`/work`](/skills/work) and [Grok Build](/platforms/grok-build) docs pages. True
overqualified work with no cheaper worker reachable still gets a one-line
suggestion — `/work --no-fit-check` plus the effort command — rather than a
silent claim; underqualified plans still skip outright.
