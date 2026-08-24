---
title: The fleet registry gets a summary line, not a full dump
authors: [carefree]
tags: [feature, fleet, tooling]
---

Anchor already keeps executor task specs lean — never the whole project,
never a raw file dump, only the context a task actually needs. The fleet
registry itself was the exception: the model-fleet MCP's `list_fleet` handed
back every endpoint's `base_url` and model name whether or not the caller
needed it, and there was no other way to get the same picture into a prompt.
It's on the same diet as everything else now.

<!-- truncate -->

## What was pasted before

`scripts/endpoints.yaml` is internal infrastructure — LAN addresses, model
identifiers, per-endpoint quirks. None of it is secret (`ANCHOR_API_KEY` was
always an environment read, never a registry field), but none of it belongs
in a context window that only needs to know *what's available*, not *where
it lives*. `list_fleet` didn't distinguish: one call, full detail, every
time.

## A generated summary, not a hand-maintained one

`scripts/router.py` now has `summarize_endpoints(fleet)`: one capped line per
endpoint — name, tier, context size, a one-phrase capability derived from the
endpoint's own quirks (`hybrid-reasoning (nemotron)`, `frontier-class`,
`local/detached`, …) — never a `base_url`, model name, or raw quirk value.
It's generated from the registry every time, so it can't drift the way a
hand-maintained summary would.

```
h100-nemotron · reasoner · ctx=65536 · hybrid-reasoning (nemotron)
```

`fleet_summary_block(fleet)` wraps that for splicing straight into a prompt.

## Full detail, only on request

`list_fleet` now returns the summary. A new `lookup_endpoint(name)` tool
returns full non-secret detail — `base_url`, model, quirks — for one endpoint,
by name, when something actually needs it:

```
lookup_endpoint("h100-nemotron")
→ h100-nemotron [reasoner] nvidia/llama-3.3-nemotron-super-49b-v1 @ http://10.0.1.11:8000/v1
  quirks: think_toggle=nemotron, temperature=0
```

Same split, same helper, on the Python side: `router.endpoint_detail(fleet,
name)`.

## Where the summary actually lands

Not every context gets it. `orchestrate.py`'s planner phase always does —
picking `Route to` targets needs fleet awareness. `prompt_tuner.py` only adds
it to a generated task spec's `## Provided context` when the rough task is
itself about routing — mentions an endpoint, a tier, escalation, dispatch.
An ordinary "fix the login bug" spec never sees it; a "which endpoint should
handle this escalation?" one does.

## Using it

Nothing to configure — `list_fleet` and `orchestrate.py`'s planner phase
already use the summary. Reach for `lookup_endpoint(name)` (or
`router.endpoint_detail(fleet, name)` from Python) when you need the detail
`list_fleet` used to hand you unasked.
