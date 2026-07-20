---
title: A declared token budget, and a checklist executors can't skip
authors: [carefree]
tags: [feature, doctrine, tooling]
---

Two scattered disciplines — "will this even fit?" and "did I check the basics
before diving in?" — are now one mechanical gate: every task spec declares a
token budget up front, and mythos-core rule 13 makes every executor print a
fixed pass/fail checklist before doing any work.

<!-- truncate -->

## The gap it closes

Rules 1, 10, and 11 already asked a model to restate the goal, judge whether the
task fit its tier, and flag a poor fit — but as separate prose scattered across
the system prompt, easy for a small model to skim past under pressure. And
nothing declared, up front, whether a task's context plus provided material
would actually fit the window it was headed for; a model found out by running
out of room mid-task.

**Rule 13 PRE-FLIGHT** collects the entry checks into one fixed 6-item block a
model prints before any other output:

- Goal restated?
- Acceptance criteria present?
- Files-in-scope listed?
- Budget declared and fits?
- Tier fit OK (rule 11)?
- Task small enough for this tier (rule 10)?

Any FAIL routes to that item's already-defined response — rule 1's clarifying
question, rule 11's `SUGGEST-ESCALATE`, rule 10's right-size question, or a
decompose-back-to-planner request for files-in-scope/budget gaps — and stops.
Rules 1–12 are untouched; this is a pure addition.

## Where the numbers come from

The task-spec template now opens with a `## Budget` section:

```markdown
## Budget
- Context window: <n tokens>
- Output ceiling: <n tokens>
- Spec + provided context exceeding this budget means the task is decomposed
  wrong — reject back to the planner, never truncate silently.
```

Those numbers are never the model's own guess. `scripts/prompt_tuner.py` fills
them from the registry:

```bash
python scripts/prompt_tuner.py "fix the login bug" --target h100-executor
```

`--target` names a registered endpoint in `scripts/endpoints.yaml`; the tuner
reads its `max_context` and computes an output ceiling (context minus spec minus
provided context minus a safety margin). Omit `--target`, or point at an
endpoint with no `max_context` set, and both fields read `unspecified` — an
honest gap, not an invented number.

`scripts/orchestrate.py` enforces the other half at dispatch time: before each
attempt, it checks the assembled prompt against the picked endpoint's
`max_context`. A prompt that's already too big is marked `failed-budget` and
rejected outright, never truncated — an oversized prompt means the task was
decomposed wrong, and that's the planner's call to fix, not a retry.
