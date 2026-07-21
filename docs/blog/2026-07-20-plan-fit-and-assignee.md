---
title: The right model for the plan — and knowing when it's a human
authors: [carefree]
tags: [feature, fix, model-fitness, fleet, tooling]
---

Anchor's whole job is getting the right model onto the right work. This release
tightens that in three ways: lesser models stop refusing work they're good at, a new
`plan_fit.py` decides fit mechanically so no model has to eyeball it, and a plan can
now be assigned to a **person** — which agents quietly leave alone.

<!-- truncate -->

## The refusal that looks like caution

We built a lot of machinery to stop expensive models from grabbing cheap work. We
shipped almost nothing for the opposite failure — and it turns out to be just as
costly, because it fails *quietly*. A `mid` or local session would open a plan, see
`Preferred models: mid, Claude Sonnet 5, Grok 4.5`, read the stronger names as a
locked door, and skip it. An absent or names-only list read the same way: "reserved
for a higher tier." The plan sat in the backlog, you waited, and a model that could
have finished it went idle.

The picker code never agreed with that — it already classifies those plans as
eligible and claims them. The *doctrine the models read* was stricter than the
harness. So we fixed the doctrine to match the code: only the **tiers** a plan lists
set the floor. Product names are extra good-fit hits, never a raised bar. An absent
line or a names-only list you don't match is `unknown` fit, which is **eligible**
after a one-line note. Difficulty you discover *after* claiming is a per-step routing
decision, not grounds to refuse the claim.

The fit check now has a single, narrow trigger: your documented weak column and
orchestration-class work. "A better model exists" is true of nearly every task and is
not a fit verdict. And when a session *does* correctly decline, the refusal is now
three lines — a verdict and at most two `→` next-steps — not a briefing.

## Let the script decide

Judging fit by reading headers is exactly the reasoning step models get wrong in both
directions, so there's now a script that applies the rules for you:

```bash
python scripts/plan_fit.py --model "Qwen3 32B" --tier mid --effort high
```

```text
take: features/scoped.md — good (Preferred: mid, Claude Sonnet 5, Grok 4.5) → effort high→low (overpaying)
skip: features/arch.md — underqualified (Preferred: reasoner, frontier; you: mid)
skip: bugs/manual-release.md — assigned to alice@corp.com (agents don't complete this)
1 eligible · 2 skipped  [you: Qwen3 32B/mid, effort high]
```

Identify the worker with `--tier`, `--model`, or `--endpoint` (resolved from
`endpoints.yaml`); add `--effort` and it also tells you when your reasoning dial is
wrong for a plan's tier. It's **read-only** — it never claims or moves anything, so
pair it with `plan_select.py --next --claim` once you've picked. `--json` for tooling,
`--next` for a bare path in cron guards, exit `1` when nothing fits you.

The effort advice rests on one tested invariant: **effort is a cost dial, not a tier
promotion.** Cranking a `mid` worker to `high` doesn't make `reasoner`-only plans
eligible, and running a reasoner at `low` doesn't disqualify it from its own work. No
`--effort` value ever changes *which* plans you can take — only whether you're
overpaying for the ones you already fit.

## Some plans are a human's to finish

Not all work should be auto-claimed. A release sign-off, a manual QA pass, anything
gated on human judgment or access — those belong to a person, and until now the only
way to keep agents off them was to leave the plan out of the ready lanes entirely.

A plan can now carry an optional header:

```markdown
- **Assignee:** alice@corp.com — owns the DB migration
```

The value may be a name, username, email, or the literal `human`. Any of them means
a **person** completes the plan, and every claim path — `/work`, `plan_fit.py`,
`work_once.py`, and the project-orchestrator MCP — auto-skips it, regardless of model
fit. The field defaults to **ai**: leave it off, or write `ai` / `agent` /
`unassigned`, and the plan is agent-eligible exactly as before.

Crucially, "a human completes it" is not "agents can't touch it." An agent may still
read an assigned plan and **edit its body** — add a `## Progress` note, answer a
question in the spec — and commit that change. Only *completing* it (moving it to
`in-progress/` then `completed/`) is reserved. If an operator really wants an agent to
take an assigned plan, `work_once.py --allow-assigned` forces a named claim.

Draft one the usual way — `/draft` and the plan template document the field — and set
`Assignee` when a person owns the outcome.
