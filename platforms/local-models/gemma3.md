# Gemma 3 — Anchor adaptation

**Sizes:** 1B/4B/12B/27B (12B+ recommended for code work; 4B is fine for summaries/classification in pipelines).

## The system-role quirk

Gemma 3's chat template has **no true system role** — "system" text is folded into the first user turn. Consequences:

- Put `mythos-core.md` at the top of the FIRST user message, followed by `---`, then the task spec.
- Instructions decay over turns faster than on models with a real system slot → hard rule: **one task per conversation**, never multi-turn task chains.

Registry mapping for the fleet scripts (`scripts/fit_device.py` emits this for you):

```yaml
quirks:
  system_role: fold_into_user
  system_suffix: '<the BLOCKED guardrail below>'
  sampling: {top_k: 64, top_p: 0.95}
```

## Sampling

temp 1.0, top_k 64, top_p 0.95 (official recommendation); drop to temp 0.3–0.5 for executor steps where determinism matters more than flair.

## Role fit

- **Executor:** 27B is a strong, obedient executor — best-in-class instruction following for its size.
- **Critic:** decent with a checklist; weaker than Qwen3-32B at catching logic errors.
- **Planner:** no.

## Extra guardrail

Gemma is agreeable — it will attempt underspecified tasks rather than push back. Append:

> If the task spec is missing files-in-scope or acceptance criteria, your entire output must be the single line: BLOCKED: <what is missing>.

## Serving

GGUF via llama.cpp/Ollama (`gemma3:27b`), QAT quants are high quality; vision-capable at 4B+ if you need screenshot-reading in pipelines.
