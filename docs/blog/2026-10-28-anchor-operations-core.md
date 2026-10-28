---
title: "The Anchor Harness core: operations, not a second copy of the workflow"
authors: [carefree]
tags: [feature, tooling]
---

`anchor plans`, `anchor work`, `anchor review`, and `anchor draft` still do
what they did last week. The logic behind them now lives in one module a
second transport can call.

<!-- truncate -->

## One registry, two adapters

`scripts/anchor_ops.py` registers each verb/action as a handler with typed
parameters, a `mutates` flag, and a `requires` class (`operator`, `model`,
`harness`, or nothing). `scripts/anchor_cli.py` is the terminal adapter:
argparse, prompts, JSON or text, exit codes.

An adapter that cannot answer — headless CLI, and later the project
orchestrator MCP — passes an `Answers` port that raises instead of reading.
Those runs still list, claim, and finish. They never merge, and they never
grow a flag that stands in for Approve.

Handlers keep calling `plan_store`, `plan_select`, `plan_lease`, `work_once`,
and `merge_feature`. The registry does not grow a third copy of lane, fit, or
`Depends on` rules.

Golden `--json` snapshots in `tests/golden/anchor_cli/` pin the envelope so
the move cannot silently change what a caller parses.
