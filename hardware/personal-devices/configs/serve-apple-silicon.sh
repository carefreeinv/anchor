#!/usr/bin/env bash
# Serve a local model on Apple Silicon (Mac Mini / MacBook Pro) as an Anchor
# fleet endpoint. Two backends: llama.cpp (Metal) or MLX. Pick by MODEL/BACKEND.
#
# Run `python scripts/fit_device.py --memory <GB>` first to choose a model that
# fits your machine — it prints the exact repo id and context to use here.
set -euo pipefail

BACKEND="${BACKEND:-metal}"          # metal (llama.cpp) | mlx
MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-GGUF}"   # for mlx, use an mlx-community repo
PORT="${PORT:-8080}"
CONTEXT="${CONTEXT:-8192}"

case "$BACKEND" in
  metal)
    # brew install llama.cpp
    exec llama-server -hf "$MODEL" --host 0.0.0.0 --port "$PORT" -ngl 99 -c "$CONTEXT"
    ;;
  mlx)
    # pip install mlx-lm
    exec mlx_lm.server --model "$MODEL" --host 0.0.0.0 --port "$PORT"
    ;;
  *)
    echo "Unknown BACKEND '$BACKEND' (expected metal or mlx)" >&2
    exit 1
    ;;
esac
