---
sidebar_position: 4
---

# Desktop tower

A single-GPU desktop (one RTX 4090 or 5090, 24–32GB VRAM) is the top of this tier — enough VRAM and CUDA throughput to brush up against `executor-heavy`, while staying always-on and mains-powered like a Mac Mini but faster.

## What fits

| VRAM | Good picks | Tier |
|---|---|---|
| 24GB (RTX 4090) | Qwen3 32B FP8, Qwen3 30B-A3B, DeepSeek-R1-Distill 32B (local reasoner/critic) | `executor-heavy` / `reasoner` |
| 32GB (RTX 5090) | Qwen3 32B FP8 at longer context, Llama 3.3 70B AWQ (tight) | `executor-heavy` |

`python scripts/fit_device.py --memory 24 --backend cuda` sizes a model to the card and prints the launch command plus `endpoints.yaml` stanza.

## Serving

vLLM (CUDA), via `hardware/personal-devices/configs/serve-cuda.sh` — FP8 where VRAM allows, AWQ (4-bit) to fit more model:

```bash
MODEL=Qwen/Qwen3-32B-FP8 ./configs/serve-cuda.sh
```

Register under tier `executor-heavy` in `scripts/endpoints.yaml` (or `reasoner` for a DeepSeek-R1 distill).

## Role

The best always-on single machine in this tier: mains-powered, no bag-in-a-backpack risk, and fast enough to double as a lightweight reasoner. A natural stepping stone before committing to an H100 node.
