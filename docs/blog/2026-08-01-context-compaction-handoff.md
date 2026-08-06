---
title: When a task outgrows its window, hand off instead of truncating
authors: [carefree]
tags: [feature, doctrine, tooling]
---

A task that runs out of context used to fail the worst way available: a
truncated answer, a confident "the rest is straightforward", or a silent stop
that looks like success. Executors now emit a **structured handoff** as they
approach their declared budget, and the orchestrator respawns a **fresh**
context seeded with it.

<!-- truncate -->

## The failure this replaces

Anchor's doctrine has always said *one task per fresh context* — context rot is
real and hits small models hardest. But "decompose so every task fits" is a
prediction, and predictions are wrong sometimes. When a task turned out bigger
than its window, nothing in the pipeline had a defined path: the model produced
whatever it could and the verification step scored a partial answer against
criteria it never finished.

The fix is not a longer conversation. Continuing in the same context is exactly
the thing that rots.

## The handoff

`anchor/templates/handoff.md` is the new artifact. Five required sections, all
machine-parsed:

- `## Done` — what is finished, each with how it was checked (`pass`, `fail`, or
  `unverified` — never a check you did not run)
- `## Remaining` — ready-to-dispatch sub-specs, each with a `Verify by:` line
- `## Decisions made` — with the reason, so the next window does not reverse them
- `## Files touched`
- `## Open concerns`

**Mythos-core rule 15** makes emitting one mandatory near budget, and states the
part models get wrong on their own: a handoff is a *successful* outcome. A
truncated answer is not.

## The orchestrator decides, not the model

`scripts/orchestrate.py` does its own token accounting. At 80% of the picked
endpoint's `max_context` it attaches a budget notice to the dispatch, telling the
executor to hand off rather than begin work it cannot finish. A model's sense of
how much room it has left is an input; the number is the authority.

A handoff reply is recognized *before* the output-footer gate — a handoff has no
`## Result` footer by design, so without that ordering the pipeline would have
retried a correct handoff as a malformed answer.

Then the continuation: original task restated, done items and decisions carried
forward as do-not-redo/do-not-reverse, and **only** the remaining sub-specs
dispatched — into a new context, not an extended one.

## Three guardrails worth knowing

**Vague remaining work is rejected.** A sub-spec with no `Verify by:` line gets
one corrective retry, then escalates. "Finish the rest" is not dispatchable, and
a continuation seeded with it fails in a way that is hard to attribute.

**Scope may only shrink.** Compaction is a convenient place for scope creep to
hide — a fresh continuation has no memory of the original boundary, so an
executor that "discovers" it also needs `deploy/` could smuggle it in. Remaining
work naming paths outside the original spec's `## Files in scope` is refused and
routed back to the planner, who owns that call.

**Two respawns, then stop.** A task that still cannot finish after two
continuations is reported as a decomposition error rather than respawned again —
it needs splitting, not another window. Override with `--max-respawns`; `0`
disables continuations entirely and escalates on the first handoff.

## Using it

Nothing to configure: any endpoint with `max_context` in `endpoints.yaml` gets
the budget notice automatically, and `orchestrate.py` handles the rest.

```bash
python scripts/orchestrate.py --plan-file .plans/features/big-migration.md \
  --verify "pytest -q" --max-respawns 2
```

The run JSON records each handoff as an event, with the window number and how
much work remained — so a task that needed three windows is visible afterward as
a planning problem, which is what it is.
