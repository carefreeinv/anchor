---
title: "`--run` applies executor diffs in the worktree"
authors: [carefree]
tags: [fix, tooling]
---

Interactive `anchor work --run` and `work_once.py --run` now apply unified
diffs from the executor reply into `--worktree` before scope and verify.
A footer-only reply still does not count as success.

<!-- truncate -->

`Endpoint.chat` never wrote files. The harness now parses `--- a/` / `+++ b/`
hunks (`scripts/apply_executor_diff.py`), rejects `.plans/**` and path
escapes, and fails the attempt on a bad patch. `work_once.py --ensure-worktree
--run` forwards `--worktree` so apply lands in the agent checkout.
