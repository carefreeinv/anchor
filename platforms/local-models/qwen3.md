# Qwen3 — Anchor adaptation

**Sizes:** 0.6B–32B dense; 30B-A3B MoE (best quality/VRAM ratio for executors; runs well even on CPU-heavy rigs).

**Official quick start:** [Qwen3 Quickstart](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) · [HF collection](https://huggingface.co/collections/Qwen/qwen3)

## Thinking toggle

Qwen3 supports hybrid reasoning. Control per message:

- Append `/think` for planner/critic roles — sampling: temp 0.6, top_p 0.95, top_k 20. **Never greedy in thinking mode** (causes repetition loops).
- Append `/no_think` for executor steps — temp 0.7, top_p 0.8.
- Do not include reasoning content from previous turns back into context (strip `<think>` blocks in multi-turn use; `scripts/` helpers do this).

Registry mapping for the fleet scripts (`scripts/fit_device.py` emits this for you):

```yaml
quirks:
  think_toggle: qwen3          # appends /think or /no_think per call
  strip_think: true
  sampling_thinking: {top_p: 0.95, top_k: 20}
  sampling: {top_p: 0.8}       # /no_think executor rec (Anchor keeps temp low for determinism)
```

`anchor_client.py` refuses greedy decoding whenever thinking is on, so the repetition-loop failure can't be triggered from the pipeline.

## System prompt

Use `anchor/system-prompts/mythos-core.md` as-is (Qwen3 respects system role well). Add for sizes ≤8B:

> Your context is small and your memory unreliable. Trust only the task spec text above. If the spec doesn't contain something you need, say BLOCKED and name it — do not improvise.

## Role fit

- **Executor:** 30B-A3B or 14B/32B dense. Excellent at scoped, spec-driven edits.
- **Critic:** 32B `/think` with `templates/review.md` — checklist review is where mid models punch above weight.
- **Planner:** only 32B `/think`, and only for small plans; prefer a frontier model or Nemotron Super.
- **Not the project orchestrator:** recommend the Preferred orchestrator when set; if unset, escalate to a frontier/near-frontier session as temporary coordinator—do not self-appoint.

## Serving

llama.cpp GGUF (Q4_K_M sweet spot) or vLLM (AWQ/FP8 on H100). Long-context variants exist; still prefer short, fresh contexts per Anchor law #1.
