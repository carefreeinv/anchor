# Llama 3.3 70B — Anchor adaptation

The generalist workhorse if you have ~40GB+ VRAM (Q4). Well-rounded: no thinking toggle, no template quirks, real system role, huge ecosystem.

## Setup

- System prompt: `mythos-core.md` verbatim.
- Sampling: temp 0.6, top_p 0.9 general; temp 0.2 for executor determinism.
- GGUF Q4_K_M ≈ 40GB (fits 2×3090 / 1×H100 comfortably alongside KV cache); FP8 on H100 via vLLM for throughput.
- Registry mapping: `quirks: {}` — the defaults in `anchor_client.py` (0.2 executor / 0.6 thinking) already match; add `sampling: {top_p: 0.9}` if you want the official rec pinned.

## Role fit

- **Executor + critic in one box:** the safe pick when you want a single local model doing both (still use fresh contexts per role — never let it review its own conversation).
- **Planner:** acceptable for small/medium plans; it plans conservatively, which is the right failure mode. Escalate architecture to a frontier model anyway.

## Guardrails

- Llama's failure mode is *confident completeness* — polished answers with a fabricated function in the middle. The `(unverified)` marking rule and tooling verification are non-negotiable.
- It is verbose; cap max_tokens for executor steps and require the standard footer so tooling can parse results.
