---
title: A daemon can now accept, skip, or reject a plan without a model
authors: [carefree]
tags: [feature, fleet, tooling]
---

Picking which plan to work on has always been mechanical — priority, value,
fit, dependencies, none of it needs judgment. But two real gaps sat under
that mechanism: a plan quoting an example header inside a code fence could
be misread as its own field, and one corrupt file could take down a whole
polling loop. Both are fixed, and daemons get an explicit triage mode that
makes the "no model needed" property visible instead of implicit.

<!-- truncate -->

## The false-positive fences could cause

Plan headers are parsed with regex over the whole file. That's fine for a
normal plan — until one quotes an example header inside a fenced code block,
which `anchor/templates/plan.md` itself does. Nothing previously stopped that
quoted example from being read as the plan's *own* `Priority` or `Assignee`.

`scripts/plan_parse.py`'s `strip_code_fences()` blanks fenced content (line
count preserved, so every other regex's positions stay meaningful) before any
header field is extracted. `plan_select.py`'s hot path — `inventory_ready`,
the thing every `/work` bare-pick and every fleet worker's poll goes through
— now runs on fence-stripped text.

## Corrupt files no longer crash-loop a daemon

`_record_from_path` used to call `path.read_text()` with no guard. One file
with bad encoding, or a permission error, and the whole inventory scan
raised — which meant a daemon polling a shared `.plans/` tree could die on
someone else's half-written `.local.md`.

`safe_read_text()` never raises. A read failure becomes `(None, reason)`,
which `PlanRecord` now carries as `parse_error` — a new, additive field that
defaults to `None`, so nothing that already builds a `PlanRecord` breaks.

## Three-way, not two-way

`plan_fit.py` already had a mechanical take/skip split, and it's unchanged.
`triage_plan()` adds the distinction daemons actually want: **reject** means
never eligible for this worker, full stop (unreadable, no `## Goal`, a human
Assignee, unmet deps, underqualified) — a routing question doesn't even
apply. **Skip** means eligible for someone else (overqualified, or leased by
another agent). **Take** means eligible now.

```python
verdict = triage_plan(record, worker)
# TriageVerdict(action=TriageAction.REJECT, reason="missing ## Goal section")
```

## Why not just add a CommonMark library

`scripts/` is designed to be copied standalone into every project that
scaffolds Anchor — every dependency added there is one every consumer has to
install. A fence-aware line scan gets the real-world benefit (quoted
examples can't leak into a plan's own fields) without asking every project
for one more `pip install`.

## Using it

```bash
python scripts/work_once.py --triage --tier mid --agent-id worker-1
# take: features/add-export.md — good (Preferred: mid)
# reject: features/vendor-contract.md — assigned to alice (agents don't complete this)
# skip: features/typo-fix.md — overqualified (Preferred: small; you: mid)
```

No LLM, no network, no claim — just the verdict and why. `fleet_watch.py
--triage` runs the same thing through the systemd/cron wrapper.
