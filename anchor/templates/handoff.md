# Handoff: <task title>

<!-- Emitted by an executor that is approaching the ceiling declared in its task
     spec's `## Budget` — instead of a partial result, a truncated answer, or a
     silent stop. The orchestrator parses this file's headings (scripts/handoff.py),
     builds a continuation spec from `## Remaining`, and respawns a fresh context
     seeded with this text. Max 2 respawns per task; a task needing a third window
     is decomposed wrong and goes back to the planner.

     All five `##` sections below are REQUIRED and parsed by heading name. Every
     `## Remaining` item must carry its own `Verify by:` line — a handoff whose
     remaining work is not dispatchable is rejected and re-requested once. -->

## Done

<!-- One bullet per step you actually finished, each with how it was checked.
     Verification status is `pass` (you ran it and it passed), `fail`, or
     `unverified` (you could not run it) — never claim a check you did not run. -->

- [x] <step you completed> — verified by `<command or check>` → pass
- [x] <step you completed> — verified by `<command or check>` → unverified

## Remaining

<!-- Ready-to-dispatch sub-specs, not a to-do list. Each one must stand alone in a
     fresh context: goal, files, and the command that proves it done. Scope may
     only SHRINK relative to the original spec — never name a file the original
     spec did not put in scope. -->

### 1. <sub-spec title>

- Goal: <one sentence — what the next window must accomplish>
- Files in scope: <paths/globs, a subset of the original spec's scope>
- Verify by: `<command that must pass>`
- Notes: <state the next window needs that is not obvious from the files>

### 2. <sub-spec title>

- Goal: <one sentence>
- Files in scope: <paths/globs>
- Verify by: `<command that must pass>`

## Decisions made

<!-- Choices the next window must not re-litigate or accidentally reverse, each
     with the reason. This is the section that stops a continuation from undoing
     the work it inherited. -->

- <decision> — <why, in one line>

## Files touched

<!-- Every path you changed in this window, with what changed. The continuation
     reads this before editing anything. -->

- `<path>` — <what changed>

## Open concerns

<!-- Anything you noticed but did not act on: suspected bugs, shaky assumptions,
     things marked (unverified). "none" is a valid entry. -->

- <concern, or `none`>
