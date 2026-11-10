---
title: "project-orchestrator MCP tools now call the same operations as `anchor`"
authors: [carefree]
tags: [feature, tooling]
---

An MCP client on `project-orchestrator` can list, claim, heartbeat, finish,
return, prepare a review, and scaffold a draft through `anchor_ops`. The
JSON envelope matches `anchor … --json`.

<!-- truncate -->

`mcp/project-orchestrator/ops_bridge.py` runs each registered operation with
an `Answers` port that never answers. Operator-only steps come back as
`pending: [{needs: "operator", …}]`. Approve, `--promote`, and `--delegate`
are not tools.

Legacy names (`plans_claim`, `plans_complete`, …) stay as aliases. Role
scoping is unchanged: planner and critic see the read surface; executor and
orchestrator see the mutating lifecycle tools. Path confinement and L1
capability gates still wrap every write.

`work_complete` / `plans_complete` remains move-only (in-progress →
review-needed). `work_finish` still runs the finish gate. Full table:
`mcp/project-orchestrator/README.md` and [MCP servers](/tooling/mcp-servers).
