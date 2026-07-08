---
sidebar_position: 1
---

# Mac Mini

The always-on on-ramp: a silent, low-power desktop you can leave serving 24/7. Apple Silicon's unified memory lets a $600–2000 box hold models that would otherwise need a discrete GPU with the same VRAM — the deciding advantage for this tier.

## What fits

| Config | Usable for models | Good picks | Tier |
|---|---|---|---|
| M4 Pro, 64GB unified | ~48GB | Qwen3 32B, Qwen3 30B-A3B (MoE — fastest big model here), Gemma 3 27B | `executor` / `executor-heavy` |
| M4, 16–32GB unified | 10–24GB | Qwen3 8B/14B, Gemma 3 12B | `swarm` / `executor` |

Budget ~25% of total RAM for macOS (a 64GB Mac → ~48GB for models). `python scripts/fit_device.py --memory 48 --backend metal` picks the exact model, context, launch command, and `endpoints.yaml` stanza.

## Serving

llama.cpp (Metal) or MLX, via `hardware/personal-devices/configs/serve-apple-silicon.sh`:

```bash
MODEL=Qwen/Qwen3-30B-A3B-GGUF ./configs/serve-apple-silicon.sh                 # Metal (default)
MODEL=mlx-community/Qwen3-30B-A3B-4bit BACKEND=mlx ./configs/serve-apple-silicon.sh
```

Register under tier `executor` in `scripts/endpoints.yaml`.

## Role

The cheapest way to stop paying frontier credits for routine execution — and the Mac Mini is built for exactly this: near-silent, sips power, happy as an always-on endpoint. Start here before investing in a larger swarm or an H100 node.
