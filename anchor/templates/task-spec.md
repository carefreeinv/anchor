# Task: <title>

<!-- The unit of work handed to an executor model. One concern. Fits one context window. -->

## Goal
<one sentence>

## Files in scope
<one path or glob per line; the scope gate (scripts/scope_gate.py) rejects any
 change outside this list *before* tests run. Globs: `*` matches within a path
 segment, `**` across segments, a trailing `/` marks a whole subtree (e.g.
 `scripts/`); a plain path matches exactly or as a directory prefix. Executor may
 touch nothing else.>

Allowed generated files: <optional globs the gate also permits — lockfiles,
 snapshots, build artifacts, e.g. `*.lock`, `__snapshots__/**`; omit if none>

## Provided context
<paste the minimal relevant code/docs here — never say "see the repo">

## Constraints
- SOLID + this project's idiomatic composition mechanism (see `ANCHOR-CONVENTIONS.md` if present); no dead code, no unreachable branches.
- <style, dependencies allowed, APIs to use/avoid>

## Acceptance criteria
- [ ] <specific, checkable>
- [ ] <specific, checkable>

## Definition of done
<exact command(s) that must succeed, e.g. `pytest tests/test_x.py -q` exits 0>

## Out of scope
<explicitly list adjacent things NOT to do>
