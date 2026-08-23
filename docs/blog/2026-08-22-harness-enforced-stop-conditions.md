---
title: Two failed attempts now stops the orchestrator, not just the model
authors: [carefree]
tags: [feature, doctrine, fleet]
---

Mythos-core rule 6 has always told a model to stop after two failed fix
attempts and hand the problem up. That only works if the model is still
counting straight — and a resumed or re-invoked task starts a fresh context
with no memory of the attempts a prior run already burned. The orchestrator
now keeps that count itself.

<!-- truncate -->

## What was missing

Rule 6 is prompt discipline: "if the same error survives two distinct fix
attempts, stop." It works inside one continuous conversation. It does not
survive a process boundary — a fleet worker picking the same task back up,
or `orchestrate.py --plan-file` re-run after an interruption, starts counting
from zero every time, because nothing outside the model's own context
remembered the earlier failures.

## A persistent count, not an in-memory one

`scripts/fleet_metrics.py` already writes a claimed-vs-actual row to
`var/fleet-metrics/outcomes.jsonl` for every finished task. `should_stop`
reads that ledger instead of trusting a counter that resets with the process:

```python
should_stop(task_id, model, ledger, tier="mid")
# → continue | escalate-tier | human-report
```

Counting is per **(task, model)**. A scope-gate rejection counts as a
failure — it is one, per rule 7 — even though it never runs `--verify`. A
handoff does not count, because a handoff never reaches the ledger in the
first place; the orchestrator returns before recording one. Fewer than two
recorded failures for that pair, and the answer is always `continue`.

## Refuse the third dispatch, escalate a tier

`execute_task` consults `should_stop` before every (re)dispatch. Two
recorded failures at the current tier means the model that already failed
twice does not get a third try — the orchestrator picks an endpoint at the
fleet's next configured tier (`available_fit_tiers`, `pick_escalation_endpoint`)
and dispatches there instead, with both failures' evidence attached to the
escalated spec's prompt so the stronger tier knows what already didn't work.

## Nowhere left to escalate

Two failures already at the top tier this fleet has configured is not
"reasoner still open, keep trying" — it is exhaustion. The orchestrator
generates a structured report itself, in rule 6's own shape (tried /
observed / hypothesis / what a stronger model or human should look at), and
writes it to `var/human-reports/` before the task ever needs a third
dispatch anywhere. The ledger is metadata-only by design — no prompts, no
output — so the report says so plainly rather than inventing a diagnosis it
cannot support.

## Using it

Nothing new to configure — pass `--metrics-ledger` (or take the default
`var/fleet-metrics/outcomes.jsonl`) the way you already do for claimed-vs-actual
tracking, and `orchestrate.py` handles the rest:

```bash
python scripts/orchestrate.py --plan-file .plans/bugs/flaky-import.md \
  --verify "pytest -q"
```

Because failures are only persisted on a task's *final* attempt, this
backstop stays invisible inside one continuous run — the two-attempts-then-stop
behavior you already know is unchanged. It only bites when a task comes back
around, which is exactly the case a model's own attempt-counting can't cover.
