# Personal devices — Mac Mini, AI laptops, and similar

Fleet tier: **executor** (a well-specced one can reach **executor-heavy**). The on-ramp tier: no rack, no cluster — a single machine you already own or can buy off the shelf, serving mid-size models for day-to-day execution while you decide whether to build out `swarm` or `h100` capacity.

## Recommended options

| Device | Memory for models | Serving | Good for |
|---|---|---|---|
| Mac Mini (M4 Pro, 64GB unified) | ~48GB usable | llama.cpp (Metal) or MLX | [Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) 30B-A3B, [Gemma 3](https://ai.google.dev/gemma/docs/core) 27B — always-on, silent, cheap to run 24/7 |
| Mac Mini (M4, 16–32GB unified) | 10–24GB usable | llama.cpp (Metal) or MLX | [Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) 8B/14B, [Gemma 3](https://ai.google.dev/gemma/docs/core) 12B — swarm-tier executor at desk-toy price |
| MacBook Pro (M3 Max / M4 Max, 64–128GB unified) | up to ~110GB usable | llama.cpp (Metal) or MLX | Same ceiling as a Mac Mini Pro but portable; doubles as a dev machine |
| RTX-equipped laptop (RTX 4080/4090 Laptop, 12–16GB VRAM) | 12–16GB VRAM | llama.cpp or vLLM (CUDA) | [Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) 14B/32B AWQ, fastest prompt-processing of this group |
| Desktop tower, single RTX 4090/5090 (24–32GB VRAM) | 24–32GB VRAM | vLLM (CUDA) | [Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) 32B FP8, [Llama 3.3](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) 70B AWQ — brushes up against `executor-heavy` |

Apple Silicon's unified memory is the deciding factor for this tier: it lets a $600–2000 consumer machine hold models that would otherwise need a discrete GPU with equivalent VRAM. Trade-off is prompt-processing speed — Metal is slower than CUDA at long-context prefill, so CUDA laptops/desktops still win on latency-sensitive executor work.

## Which model fits? (`fit_device.py`)

The one question a spec sheet can't answer is *which* model, at *which* quantization, with *how much* context, fits your machine. `scripts/fit_device.py` does that math and prints a ready launch command plus an `endpoints.yaml` stanza (with the right quirks baked in for the model family):

```bash
python scripts/fit_device.py --probe                      # detect this machine + install links + fit
python scripts/fit_device.py --memory 48                 # 64GB Mac Mini (~48GB usable), Metal
python scripts/fit_device.py --memory 16 --backend mlx   # 24GB MacBook Air
python scripts/fit_device.py --memory 24 --backend cuda  # single RTX 4090
python scripts/fit_device.py --list                       # the whole catalog
```

In a coding agent, prefer **`/local-models`** (same probe + clickable install procedures for WSL/macOS/CUDA).

Memory is a conservative estimate (weights + KV cache + overhead) — a starting point to confirm with `benchmark.py`, not a guarantee. On unified-memory Macs, budget ~25% of total RAM for the OS (a 64GB Mac → `--memory 48`).

## Setup

The `configs/` scripts wrap the two serving paths — set `MODEL`/`CONTEXT` from what `fit_device.py` recommended:

```bash
# Apple Silicon (Mac Mini / MacBook Pro) — llama.cpp (Metal) or MLX
MODEL=Qwen/Qwen3-30B-A3B-GGUF ./configs/serve-apple-silicon.sh          # BACKEND=metal (default)
MODEL=mlx-community/Qwen3-30B-A3B-4bit BACKEND=mlx ./configs/serve-apple-silicon.sh

# CUDA laptop/desktop tower — vLLM
MODEL=Qwen/Qwen3-14B-AWQ ./configs/serve-cuda.sh
```

Register endpoints in `scripts/endpoints.yaml` under tier `executor` (or `executor-heavy` for the RTX 4090/5090 desktop config) — `fit_device.py` prints the stanza for you.

## Anchor notes for this tier

- This is the cheapest way to stop paying frontier credits for routine execution — start here before investing in a larger swarm or H100 node.
- Apple Silicon machines are close to silent and sip power, so leaving one on as an always-on `executor` endpoint costs little; the Mac Mini in particular is built for exactly this.
- A laptop in this tier is still a laptop: don't rely on it as your only executor if it also needs to survive being closed in a bag mid-run — prefer the desktop/Mini options for anything unattended.
