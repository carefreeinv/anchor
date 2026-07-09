# H100 node — the local frontier tier

Fleet tier: **reasoner + heavy executor**. One or more H100s (80GB) serving the models that plan, review, and take escalations from the swarm.

## Recommended layout (single H100)

| Slot | Model | Serving | Why |
|---|---|---|---|
| Reasoner/critic | Llama-3.3-Nemotron-Super-49B (NIM) or [DeepSeek-R1](https://huggingface.co/collections/deepseek-ai/deepseek-r1) Distill-70B | NIM container / vLLM FP8 | planner + critic + escalation target |
| Heavy executor | [Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) 32B FP8 or [Llama 3.3](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) 70B AWQ | vLLM | bulk high-quality execution |

Two models won't fit at full context simultaneously on one 80GB card — either time-share via llama-swap-style switching, dedicate the card to one slot and put the other on a second card, or run one mid-size model (Qwen3 32B FP8) that covers both slots acceptably.

## Setup

```bash
# vLLM route
pip install vllm
vllm serve Qwen/Qwen3-32B-FP8 --host 0.0.0.0 --port 8000 \
  --max-model-len 32768 --gpu-memory-utilization 0.92
# NIM route (Nemotron; see platforms/nvidia-nim/NEMOTRON.md)
docker compose -f configs/nim-compose.yaml up -d
```

Register endpoints in `scripts/endpoints.yaml` under tiers `reasoner` and `executor-heavy`.

## Anchor notes for this tier

- This tier replaces credit-metered frontier calls for *most* judgment work: plans, reviews, twice-failed escalations. Keep a true frontier model (Fable/Opus via Claude Code) only for the hardest architecture calls and final review of large merges.
- Batch is the superpower: vLLM continuous batching means the whole swarm's escalations and the orchestrator's reviews run concurrently — size `max_num_seqs` accordingly.
- Reasoning models on this card get token budgets (8–16k) and the LOW-CONFIDENCE stop rule from `platforms/local-models/deepseek-r1-distill.md`.
