---
sidebar_position: 3
---

# RTX laptop

An AI-optimized Windows/Linux laptop with a discrete NVIDIA GPU (RTX 4080/4090 Laptop, 12–16GB VRAM). Less memory than an Apple Silicon machine, but CUDA gives it the fastest prompt-processing in this tier — the right pick when executor latency matters more than model size.

## What fits

| VRAM | Good picks | Tier |
|---|---|---|
| 12–16GB | Qwen3 14B AWQ, Qwen3 8B, Gemma 3 12B | `swarm` / `executor` |

VRAM is the hard limit here — the model plus its KV cache must fit the card, with no unified-memory fallback. `python scripts/fit_device.py --memory 16 --backend cuda` picks a model that fits and prints the launch command plus `endpoints.yaml` stanza.

## Serving

vLLM (CUDA), via `hardware/personal-devices/configs/serve-cuda.sh` — AWQ (4-bit) fits the most model per GB of VRAM:

```bash
MODEL=Qwen/Qwen3-14B-AWQ ./configs/serve-cuda.sh
```

Register under tier `executor` (or `swarm` for the smaller models) in `scripts/endpoints.yaml`.

## Role

The fastest executor of the consumer options for latency-sensitive work. Same caveat as any laptop: don't rely on it as your only executor if it also needs to survive being unplugged or closed mid-run — prefer a desktop tower for unattended serving.
