---
title: Planner, executor, critic — now harness-enforced
authors: [carefree]
tags: [feature, tooling]
---

Role separation graduated from prompt framing to a harness guarantee: a planner phase **cannot** write product files, an executor **cannot** touch `.plans/**` or its own spec, and a critic **cannot** write anything — enforced by code, not by asking nicely.

<!-- truncate -->

Anchor's doctrine has always said the same small model performs better as three sequential roles — planner → executor → critic — than as one conversational blob. Until now that split was trust-based: mythos-core rule 2 told the model to plan before acting, and everyone hoped it listened. Small models drift, and "hoped" is not a verification strategy.

The new **`scripts/roles.py`** is the single role→capability map. Each role carries writable-path allow/deny globs (reusing `scope_gate.path_matches`, so there is exactly one glob implementation in the repo), a `can_dispatch` flag only the orchestrator holds, and the MCP toolset the role may see. Reads stay unrestricted everywhere — only writes and dispatch are gated.

**`orchestrate.py`** now snapshots the worktree around every phase and checks the writes made *during* that phase against the phase's role. Pre-existing dirt is never blamed on a role. A violation is a hard error: it is logged as an explicit event, the offending task is marked `failed-role`, and the run still emits its plan, review, and JSON report — then exits `4`. Role transitions (plan approved → executors spawned → review starts) are logged orchestrator events in the run JSON, so "who was allowed to do what, when" is auditable after the fact.

The **project-orchestrator MCP server** applies the same map at the toolset level:

```bash
# planning session: read-only .plans/ surface — lifecycle tools not registered
python mcp/project-orchestrator/server.py --project /path/to/myapp --role planner
```

A `--role planner` or `--role critic` session never even sees `plans_claim`, `plans_release`, or `plans_complete` — deny by omission, not refusal. There is nothing to jailbreak past; the tools simply are not there. `--role executor` keeps the lifecycle tools, and omitting `--role` preserves the full pre-role surface.

The pattern is borrowed from Fable-class harness plan mode, where planning is a *state* with edit tools disabled and exit is explicit. Prompt text still tells the model its role — small models behave better told *and* constrained — but the harness is the guarantee.

One honest boundary: this hardens the **orchestrated path only**. A single-model session with no orchestrator and no MCP server between it and the filesystem is still bound by doctrine alone. That is stated in the docs rather than papered over.
