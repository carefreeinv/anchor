# DeepSeek-R1 distills — Anchor adaptation

**Qwen/Llama backbones distilled from R1: 7B/8B/14B/32B/70B.** Local reasoning specialists — the fleet's "hard problem" and critic tier.

## Critical quirks

- **Avoid a system prompt entirely** — official guidance: put ALL instructions in the user message (mythos-core text goes at the top of the user turn).
- Sampling: temp 0.5–0.7 (0.6 recommended), top_p 0.95. **Greedy decoding breaks these models** (repetition loops).
- Force thinking: ensure output begins with `<think>`. Strip `<think>...</think>` before feeding downstream or into history.
- No few-shot examples in the prompt — they degrade R1-style models. Describe the format; don't demonstrate it.

Registry mapping for the fleet scripts (`scripts/fit_device.py` emits this for you):

```yaml
quirks:
  system_role: fold_into_user   # no system prompt: instructions fold into the user turn
  strip_think: true
  sampling_thinking: {top_p: 0.95}
  system_suffix: '<the LOW-CONFIDENCE budget rule below>'
```

`anchor_client.py` additionally refuses greedy decoding whenever thinking is on, so a stray `temperature: 0` can't trigger the repetition-loop failure.

## Role fit

- **Critic:** the best local reviewer per GB. Give it the diff + spec + `templates/review.md`; its long deliberation catches what executors miss.
- **Hard single problems:** race conditions, off-by-one hunts, algorithm choice — the "Opus role" of a local fleet.
- **Executor:** NO. Slow, token-hungry, prone to over-refactoring simple tasks. Never waste it on boilerplate (same economics as the Fable playbook: deliberation is expensive; spend it on judgment).

## Budget guardrail

Cap max_tokens (e.g., 8–16k) and add:

> If your reasoning exceeds the budget before a conclusion, stop and output your best current answer marked LOW-CONFIDENCE plus the single open question that would resolve it.
