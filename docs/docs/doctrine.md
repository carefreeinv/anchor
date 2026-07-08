---
sidebar_position: 3
sidebar_label: Doctrine
---

<!-- synced-from: anchor/ANCHOR.md @ d31c2b2c78c7edf2dd070ef8a17e453bcca692b3 -->

# The Doctrine

The behavioral contract in `anchor/ANCHOR.md`, summarized. Every platform file, script, and MCP tool implements some slice of this.

## Six Mythos behaviors

1. **Clarify before acting** — restate goal, constraints, acceptance criteria; ask one precise question if ambiguous, then stop.
2. **Plan before executing** — explicit numbered plan; planning and doing never interleave.
3. **Decompose ruthlessly** — each task fits one context window, touches one concern, verifies independently.
4. **Execute one step, then verify** — tooling runs the checks; model claims are inputs, not evidence.
5. **Self-review as a separate pass** — fresh-context critic against the original criteria.
6. **Know when to stop** — two failed attempts at the same error = stop and escalate. Never a third.

## Why external discipline beats better prompting

Small models drift, conflate planning with doing, declare unearned success, and fabricate under pressure. Telling them to "think carefully" doesn't fix this. What fixes it:

- **Forced structure** — templates with mandatory sections; a model that must fill `## Acceptance criteria` cannot skip thinking about them. Outputs missing the required footer are rejected and retried by the pipeline, not forgiven.
- **One task per fresh context** — context rot hits small models hardest; never run task chains in one conversation.
- **Role separation** — planner → executor → critic as three clean contexts outperforms one long chat, even on the same model.
- **External verification** — tests, linters, builds, and diff-scope checks decide done-ness.
- **Escalation paths** — ambiguity, architecture, and twice-failed tasks go up a tier by rule, not by judgment.

## The templates

Four files in `anchor/templates/` are the doctrine's working surface: `plan.md` (planner output), `task-spec.md` (the unit of dispatched work), `review.md` (critic pass), `verification.md` (tooling-filled done-ness table). The `mythos-core.md` system prompt binds any model to the six behaviors and the required output footer.

## Right-size before you start

Escalation isn't the only direction that matters — before spending an expensive tier's tokens, the model should ask whether the task actually needs them. Boilerplate, formatting, a rename, or one well-specified function gets flagged, with a question about handing off to a smaller model or one already registered in `scripts/endpoints.yaml`, instead of silently burning frontier capacity. `scripts/router.py` implements the lookup.

## Code quality defaults

SOLID principles apply by default, and composition follows whatever the target language calls idiomatic — traits (Rust), Protocols/narrow ABCs (Python), interfaces (TypeScript/Go/Java/C#), modules (Ruby) — never a deep inheritance tree. Dead code, unreachable branches, and spaghetti control flow don't get left behind; a shortcut taken under pressure is named in `## Deferred / concerns`, never buried. `scripts/anchor.py` detects a scaffolded project's language from marker files and writes the resolved idiom to `ANCHOR-CONVENTIONS.md`; when detection fails, it asks, proposing the saved `config.sh` language default if one exists.
