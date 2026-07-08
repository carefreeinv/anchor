# Mistral Small 3.x — Anchor adaptation

**~24B dense.** The community's "fast executor" pick: low latency, good function calling, permissive Apache license.

## Setup

- Use the official chat template exactly; Mistral is sensitive to template drift.
- Sampling: temp 0.15 (official recommendation is LOW) for executor work; 0.5–0.7 for critic prose.
- System prompt: `mythos-core.md` as-is (real system role supported).

Registry mapping for the fleet scripts (`scripts/fit_device.py` emits this for you):

```yaml
quirks:
  temperature: 0.15                       # executor default; critics pass their own
  system_suffix: '<the BLOCKED reminder below>'
```

## Role fit

- **Executor:** primary role. Excellent for scoped code edits, tool-calling steps, and structured extraction inside pipelines.
- **Tool-use node:** best local model per VRAM for reliable JSON/function-call outputs — use it as the "hands" of the `model-fleet` MCP server on mid-size hardware.
- **Planner/critic:** not its strength; it optimizes for concision and will under-explain reasoning.

## Guardrails

- Mistral's terseness means it may skip the `## How to verify` footer under load — enforce with a format check in the pipeline (reject and retry outputs missing footers; `scripts/orchestrate.py` does this).
- Keep task specs fully self-contained; Mistral does not ask clarifying questions readily. The BLOCKED rule from `mythos-core.md` needs re-emphasis:

> Reminder: an incomplete spec means your ONLY valid output is BLOCKED: <missing thing>.
