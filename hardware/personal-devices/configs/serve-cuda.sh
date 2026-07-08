#!/usr/bin/env bash
# Serve a local model on an RTX-equipped laptop or single-GPU desktop tower as an
# Anchor fleet endpoint, via vLLM (CUDA). AWQ (4-bit) fits the most model per GB
# of VRAM; FP8 is faster where VRAM allows.
#
# Run `python scripts/fit_device.py --memory <VRAM_GB> --backend cuda` first to
# choose a model that fits your card — it prints the exact repo id and context.
set -euo pipefail

# pip install vllm
MODEL="${MODEL:-Qwen/Qwen3-14B-AWQ}"
PORT="${PORT:-8000}"
CONTEXT="${CONTEXT:-16384}"
GPU_UTIL="${GPU_UTIL:-0.90}"

EXTRA=()
case "$MODEL" in
  *AWQ*|*awq*) EXTRA+=(--quantization awq) ;;
esac

exec vllm serve "$MODEL" --host 0.0.0.0 --port "$PORT" \
  --max-model-len "$CONTEXT" --gpu-memory-utilization "$GPU_UTIL" "${EXTRA[@]}"
