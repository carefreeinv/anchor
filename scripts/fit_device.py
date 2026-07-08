#!/usr/bin/env python3
"""fit_device — pick a model, quantization, and context that fit a personal device.

The personal-devices tier (Mac Mini, AI laptop, single-GPU desktop) has one hard
question a newcomer can't answer from a spec sheet: *which* model, at *which*
quantization, with *how much* context, actually fits my RAM/VRAM — and how do I
serve it? This does that math and prints a ready launch command plus an
`endpoints.yaml` stanza (with the right quirks for the model family, per
anchor_client.py) so the device drops straight into the fleet.

Memory is a rough estimate (weights + KV cache + runtime overhead), deliberately
conservative — treat it as a starting point and confirm with `benchmark.py`, not
as a guarantee. Bigger-but-tighter fits are flagged, not hidden.

Usage:
  python fit_device.py --memory 48                    # 64GB Mac Mini (~48GB usable), Metal
  python fit_device.py --memory 16 --backend mlx
  python fit_device.py --memory 24 --backend cuda     # single RTX 4090
  python fit_device.py --memory 48 --context 32768    # size for a longer context
  python fit_device.py --memory 48 --emit-endpoint    # print only the endpoints.yaml stanza
  python fit_device.py --list                          # show the whole model catalog
"""
from __future__ import annotations

import argparse
import sys

# Bytes per weight by quantization (empirical GGUF/AWQ/FP8 footprints, incl. embeddings).
QUANT_BYTES: dict[str, float] = {
    "q4": 0.60,   # llama.cpp Q4_K_M / AWQ 4-bit / MLX 4-bit
    "q5": 0.70,   # Q5_K_M
    "q6": 0.82,   # Q6_K
    "q8": 1.06,   # Q8_0
    "fp8": 1.02,  # vLLM FP8
    "fp16": 2.00,
}

# KV-cache GB per 1k tokens per billion params — rough GQA-model average at fp16 KV.
KV_GB_PER_1K_PER_B = 0.012
# Framework/driver/activation headroom (Metal context, CUDA context, etc.).
RUNTIME_OVERHEAD_GB = 1.0

# Backend -> default quant it serves best.
BACKEND_DEFAULT_QUANT = {"metal": "q4", "mlx": "q4", "cuda": "q4"}


class Model:
    def __init__(self, name: str, params_b: float, family: str, tier: str,
                 gguf: str, mlx: str, hf: str, thinking: bool = False, note: str = ""):
        self.name = name
        self.params_b = params_b        # total params (MoE counts all experts for memory)
        self.family = family            # qwen3 | gemma3 | mistral | llama | deepseek-r1-distill
        self.tier = tier                # endpoints.yaml tier this model serves as
        self.gguf = gguf                # HF repo for llama.cpp -hf
        self.mlx = mlx                  # HF repo for MLX
        self.hf = hf                    # HF repo for vLLM (AWQ/FP8)
        self.thinking = thinking
        self.note = note


# Catalog mirrors hardware/personal-devices/README.md and platforms/local-models/.
CATALOG: list[Model] = [
    Model("qwen3-4b", 4, "qwen3", "swarm",
          "Qwen/Qwen3-4B-GGUF", "mlx-community/Qwen3-4B-4bit", "Qwen/Qwen3-4B-AWQ",
          note="desk-toy executor; great on 16GB and under"),
    Model("qwen3-8b", 8, "qwen3", "swarm",
          "Qwen/Qwen3-8B-GGUF", "mlx-community/Qwen3-8B-4bit", "Qwen/Qwen3-8B-AWQ"),
    Model("gemma3-12b", 12, "gemma3", "executor",
          "google/gemma-3-12b-it-qat-q4_0-gguf", "mlx-community/gemma-3-12b-it-4bit",
          "google/gemma-3-12b-it", note="fold system role into first user turn"),
    Model("qwen3-14b", 14, "qwen3", "executor",
          "Qwen/Qwen3-14B-GGUF", "mlx-community/Qwen3-14B-4bit", "Qwen/Qwen3-14B-AWQ"),
    Model("mistral-small-24b", 24, "mistral", "executor",
          "bartowski/Mistral-Small-24B-Instruct-2501-GGUF",
          "mlx-community/Mistral-Small-24B-Instruct-2501-4bit",
          "mistralai/Mistral-Small-24B-Instruct-2501"),
    Model("gemma3-27b", 27, "gemma3", "executor",
          "google/gemma-3-27b-it-qat-q4_0-gguf", "mlx-community/gemma-3-27b-it-4bit",
          "google/gemma-3-27b-it", note="fold system role into first user turn"),
    Model("qwen3-30b-a3b", 30, "qwen3", "executor",
          "Qwen/Qwen3-30B-A3B-GGUF", "mlx-community/Qwen3-30B-A3B-4bit", "Qwen/Qwen3-30B-A3B",
          note="MoE: 30B in memory but ~3B active — fastest big model on Apple Silicon"),
    Model("qwen3-32b", 32, "qwen3", "executor-heavy",
          "Qwen/Qwen3-32B-GGUF", "mlx-community/Qwen3-32B-4bit", "Qwen/Qwen3-32B-FP8"),
    Model("deepseek-r1-distill-32b", 32, "deepseek-r1-distill", "reasoner",
          "bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF",
          "mlx-community/DeepSeek-R1-Distill-Qwen-32B-4bit",
          "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B", thinking=True,
          note="local critic/reasoner; give it a token budget and the LOW-CONFIDENCE stop rule"),
    Model("llama33-70b", 70, "llama", "executor-heavy",
          "bartowski/Llama-3.3-70B-Instruct-GGUF", "mlx-community/Llama-3.3-70B-Instruct-4bit",
          "casperhansen/llama-3.3-70b-instruct-awq",
          note="needs a 64GB+ unified-memory Mac or 2x 24GB GPUs"),
]


def estimate_memory_gb(params_b: float, quant: str, context: int) -> float:
    weights = params_b * QUANT_BYTES[quant]
    kv = (context / 1024) * params_b * KV_GB_PER_1K_PER_B
    return weights + kv + RUNTIME_OVERHEAD_GB


def max_context_for(params_b: float, quant: str, memory_gb: float, cap: int = 32768) -> int:
    """Largest power-of-two context (up to cap) whose estimate fits memory_gb."""
    best = 0
    ctx = 2048
    while ctx <= cap:
        if estimate_memory_gb(params_b, quant, ctx) <= memory_gb:
            best = ctx
        ctx *= 2
    return best


# Per-model guardrail lines — keep in sync with platforms/local-models/<model>.md.
GEMMA_GUARDRAIL = ("If the task spec is missing files-in-scope or acceptance criteria, "
                   "your entire output must be the single line: BLOCKED: <what is missing>.")
MISTRAL_GUARDRAIL = ("Reminder: an incomplete spec means your ONLY valid output is "
                     "BLOCKED: <missing thing>.")
R1_GUARDRAIL = ("If your reasoning exceeds the budget before a conclusion, stop and output "
                "your best current answer marked LOW-CONFIDENCE plus the single open "
                "question that would resolve it.")


def quirks_for(model: Model, context: int) -> dict:
    q: dict = {}
    if model.family == "qwen3":
        q["think_toggle"] = "qwen3"
        q["strip_think"] = True
    elif model.family == "gemma3":
        q["system_role"] = "fold_into_user"
        q["system_suffix"] = GEMMA_GUARDRAIL  # Gemma is agreeable: force BLOCKED over improvising
    elif model.family == "mistral":
        q["temperature"] = 0.15  # official rec is LOW for executor work
        q["system_suffix"] = MISTRAL_GUARDRAIL  # terse; won't push back on thin specs
    elif model.family == "deepseek-r1-distill":
        q["system_role"] = "fold_into_user"  # official guidance: no system prompt at all
        q["strip_think"] = True
        q["system_suffix"] = R1_GUARDRAIL  # deliberation budget stop rule
    if context and context < 32768:
        q["max_context"] = context
    return q


def launch_command(model: Model, backend: str, quant: str, context: int) -> str:
    if backend == "metal":
        return (f"llama-server -hf {model.gguf} --host 0.0.0.0 --port 8080 "
                f"-ngl 99 -c {context}")
    if backend == "mlx":
        return (f"mlx_lm.server --model {model.mlx} --host 0.0.0.0 --port 8080")
    # cuda / vLLM
    quant_flag = " --quantization awq" if "AWQ" in model.hf or "awq" in model.hf else ""
    return (f"vllm serve {model.hf} --host 0.0.0.0 --port 8000 "
            f"--max-model-len {context}{quant_flag}")


def endpoint_stanza(model: Model, backend: str, context: int, name: str | None = None) -> str:
    port = 8000 if backend == "cuda" else 8080
    served = model.hf if backend == "cuda" else model.name
    quirks = quirks_for(model, context)
    lines = [
        f"  - name: {name or f'{model.name}-local'}",
        f"    tier: {model.tier}",
        f"    base_url: http://localhost:{port}/v1",
        f"    model: {served}",
    ]
    # Flow style for short quirks; block style once guardrail strings appear.
    if any(isinstance(v, str) and " " in v for v in quirks.values()):
        lines.append("    quirks:")
        lines.extend(f"      {k}: {_yaml_val(v)}" for k, v in quirks.items())
    else:
        quirks_str = "{" + ", ".join(f"{k}: {_yaml_val(v)}" for k, v in quirks.items()) + "}" if quirks else "{}"
        lines.append(f"    quirks: {quirks_str}")
    return "\n".join(lines)


def _yaml_val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str) and any(c in v for c in " :{}#'\""):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def fitting_models(memory_gb: float, quant: str, context: int) -> list[Model]:
    """Catalog entries that fit, largest (most capable) first."""
    fits = [m for m in CATALOG if estimate_memory_gb(m.params_b, quant, context) <= memory_gb]
    return sorted(fits, key=lambda m: m.params_b, reverse=True)


def print_catalog() -> None:
    print(f"{'model':26s} {'params':>7s}  {'tier':14s} family")
    for m in CATALOG:
        print(f"{m.name:26s} {m.params_b:6.0f}B  {m.tier:14s} {m.family}"
              + (f"   # {m.note}" if m.note else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--memory", type=float, help="GB of RAM/VRAM available for the model "
                                                 "(unified-memory Macs: leave ~25%% for the OS)")
    ap.add_argument("--backend", choices=["metal", "mlx", "cuda"], default="metal",
                    help="metal = llama.cpp on Apple Silicon (default), mlx = MLX, cuda = vLLM")
    ap.add_argument("--quant", choices=list(QUANT_BYTES), help="override the quantization (default q4)")
    ap.add_argument("--context", type=int, default=8192, help="context length to size for (default 8192)")
    ap.add_argument("--name", help="endpoints.yaml name for the emitted stanza")
    ap.add_argument("--emit-endpoint", action="store_true",
                    help="print only the endpoints.yaml stanza for the best fit")
    ap.add_argument("--list", action="store_true", help="print the model catalog and exit")
    args = ap.parse_args()

    if args.list:
        print_catalog()
        return

    if args.memory is None:
        raise SystemExit("Pass --memory <GB> (RAM/VRAM available for the model). See --list for the catalog.")

    quant = args.quant or BACKEND_DEFAULT_QUANT[args.backend]
    fits = fitting_models(args.memory, quant, args.context)
    if not fits:
        smallest = min(CATALOG, key=lambda m: m.params_b)
        need = estimate_memory_gb(smallest.params_b, quant, args.context)
        raise SystemExit(
            f"Nothing in the catalog fits {args.memory:.0f}GB at {quant}/{args.context} context. "
            f"The smallest model ({smallest.name}) needs ~{need:.1f}GB — lower --context or free up memory.")

    best = fits[0]
    ctx_ceiling = max_context_for(best.params_b, quant, args.memory)

    if args.emit_endpoint:
        print(endpoint_stanza(best, args.backend, args.context, args.name))
        return

    est = estimate_memory_gb(best.params_b, quant, args.context)
    print(f"Device: {args.memory:.0f}GB available, backend={args.backend}, quant={quant}, "
          f"context={args.context}\n")
    print(f"Best fit: {best.name} ({best.params_b:.0f}B, tier {best.tier}) "
          f"— est. ~{est:.1f}GB")
    if best.note:
        print(f"  note: {best.note}")
    if ctx_ceiling > args.context:
        print(f"  headroom: this model fits up to ~{ctx_ceiling} context on {args.memory:.0f}GB")
    elif ctx_ceiling and ctx_ceiling < args.context:
        print(f"  tight: {args.context} context is over budget; ~{ctx_ceiling} is the safe ceiling")

    print("\nAlso fits (smaller, faster, run several as a local swarm):")
    for m in fits[1:5]:
        print(f"  {m.name:26s} {m.params_b:.0f}B  tier {m.tier}")

    print("\nLaunch:")
    print(f"  {launch_command(best, args.backend, quant, args.context)}")

    print("\nRegister in scripts/endpoints.yaml:")
    print(endpoint_stanza(best, args.backend, args.context, args.name))

    print("\n(Memory is a conservative estimate — confirm real throughput with benchmark.py.)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
