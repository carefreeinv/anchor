---
sidebar_position: 2
---

# MacBook Pro

The portable AI workstation: an M3 Max / M4 Max with 64–128GB of unified memory is the highest-memory option in this tier, and doubles as your dev machine. Same Apple Silicon serving story as the Mac Mini, with a bigger ceiling.

## What fits

| Config | Usable for models | Good picks | Tier |
|---|---|---|---|
| M3 Max / M4 Max, 64GB | ~48GB | Qwen3 32B, Qwen3 30B-A3B, Gemma 3 27B | `executor` / `executor-heavy` |
| M3 Max / M4 Max, 128GB | ~110GB | Llama 3.3 70B — the biggest model this tier can hold | `executor-heavy` |

`python scripts/fit_device.py --memory 110 --backend metal` (or your usable GB) sizes a model and prints the launch command plus `endpoints.yaml` stanza.

## Serving

llama.cpp (Metal) or MLX, via `hardware/personal-devices/configs/serve-apple-silicon.sh`:

```bash
MODEL=bartowski/Llama-3.3-70B-Instruct-GGUF ./configs/serve-apple-silicon.sh       # Metal
MODEL=mlx-community/Llama-3.3-70B-Instruct-4bit BACKEND=mlx ./configs/serve-apple-silicon.sh
```

## Role

The most capable single-machine executor in this tier — a 128GB Max can even hold a 70B reasoner. But it's still a laptop: don't make it your only executor if it also gets closed in a bag mid-run. For anything unattended, prefer a Mac Mini or a desktop tower.
