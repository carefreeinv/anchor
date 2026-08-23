---
title: Only the footer comes back — executor reasoning stops at the boundary
authors: [carefree]
tags: [feature, doctrine, fleet]
---

An executor's reasoning, false starts, and quoted templates used to ride
along with everything else in its reply — all the way back into the
coordinator's own context, and from there into the next task's prompt. Only
the structured footer does that now; the rest is archived to disk and
discarded from context.

<!-- truncate -->

## What was crossing the boundary

Mythos-core rule 8 has always required a fixed footer — `## Result`,
`## How to verify`, `## Deferred / concerns` — at the end of every executor
reply. But the orchestrator's own footer check only ever asked "is the
footer present," then passed the **entire raw reply** back as the task's
result. A verbose executor's scratch work, three abandoned attempts at
phrasing an answer, or a quoted copy of the template from its own reasoning
all rode along with it — straight into the coordinator's context and the
critic's review prompt.

## Extract, don't trust

`fleet_metrics.extract_footer` pulls just the three required sections out,
tolerantly:

```python
extract_footer(text, max_lines=60)
# -> FooterExtraction(ok, footer_text, missing, truncated)
```

Case and spacing drift are tolerated (`##Result`, `##  HOW TO VERIFY`,
`Deferred/Concerns` all match). When a heading appears more than once — an
executor quoting the template mid-reasoning before its real answer — the
**last** occurrence wins, so an early false start never gets mistaken for
the finished result. All three sections are still required; missing any is
a named rejection, not a partial accept. And the reconstructed footer is
capped at 60 lines with an explicit `[truncated by harness]` marker, so
smuggling a full transcript inside `## Result` doesn't work either.

## The transcript goes to disk, not to context

`scripts/orchestrate.py` archives every dispatch's full raw reply to
`var/task-transcripts/<task-hash>.log` — a metadata header per attempt,
appended across retries and respawns — before anything crosses back to the
coordinator. What actually crosses is `relay_text(out)`: the extracted
footer when the reply has one, or the raw reply capped at the same line
budget when it doesn't. Either way, the coordinator's context, the next
task's prompt, and the claimed-vs-actual ledger's claim-parsing input all
see the same bounded text — never the unbounded original.

A reply with no recognizable footer at all still gets exactly the treatment
rule 6/8 already specified: one corrective retry with the expected shape
quoted, then escalation. Nothing about that path changed — only what
happens to a reply that *does* have one.

## Using it

Nothing to configure for the footer relay itself. Transcript archival
follows the same default/disable pattern as claimed-vs-actual tracking:

```bash
python scripts/orchestrate.py --plan-file .plans/features/big-refactor.md \
  --verify "pytest -q"
# transcripts land under <worktree>/var/task-transcripts/ by default;
# --transcripts <dir> to redirect, --transcripts "" to disable
```
