---
title: A scope gate that makes "scope is sacred" mechanical
authors: [carefree]
tags: [feature, tooling]
---

Mythos-core rule 7 says an executor may only touch the files listed in its task
spec. Until now that was a promise the model made to itself. **`scripts/scope_gate.py`**
makes it a check: any change outside the spec's `## Files in scope` is rejected
**before** tests run.

<!-- truncate -->

## The gap it closes

Per-agent worktrees gave each worker its own checkout. Leases decided *which*
plan a worker owns. But nothing verified that the diff a worker produced actually
stayed inside the files it was told to touch — a small model that "also fixed"
an unrelated file would sail through as long as the tests passed.

The scope gate reads the worktree's changes (`git diff` vs HEAD plus untracked
files) and classifies each path against the spec:

```bash
python scripts/scope_gate.py --root . --spec task-spec.md && pytest -q
```

Exit `3` means a path fell outside scope — and because the gate runs *before*
`pytest`, tests never execute on an out-of-scope diff. In the orchestrator, the
same check runs inline:

```bash
python scripts/orchestrate.py --plan-file .plans/features/foo.md \
  --scope-spec task-spec.md --worktree . --verify "pytest -q"
```

An out-of-scope change marks the task `failed-scope` and routes it back to the
planner. It is **not** a retryable failure — widening scope is the planner's
call, not the executor's.

## How scope is written

`## Files in scope` takes one path or glob per line, gitignore-style:

- `*` matches within a path segment, `**` across segments
- a trailing `/` marks a whole subtree (`scripts/`)
- a plain path matches exactly or as a directory prefix

Legitimately generated files — lockfiles, snapshots — go on an `Allowed generated
files:` line so a `poetry.lock` churn doesn't trip the gate:

```markdown
## Files in scope
- scripts/scope_gate.py
- tests/test_scope_gate.py

Allowed generated files: *.lock
```

The classifier (`check_scope`) is a pure function with no git or I/O, so the
matching rules are unit-tested independently of any repo; `worktree_changes` and
`enforce_scope` layer the git read on top. When a spec declares no scope at all,
the gate stays inactive rather than blocking everything — it enforces intent, it
doesn't invent it.
