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

``--probe`` reports two answers: **Max fit** (largest catalog entry under the
usable budget — capability ceiling) and **Default for wire** (memory-safer
pick for Aider / ``.env`` / launcher defaults, using free/available RAM when
known). Personal-device profiles under pressure default to the smallest fit
unless free RAM clearly supports the max.

Usage:
  python fit_device.py --memory 48                    # 64GB Mac Mini (~48GB usable), Metal
  python fit_device.py --memory 16 --backend mlx
  python fit_device.py --memory 24 --backend cuda     # single RTX 4090
  python fit_device.py --memory 48 --context 32768    # size for a longer context
  python fit_device.py --memory 48 --emit-endpoint    # stanza for Default for wire
  python fit_device.py --probe                         # detect OS/RAM/GPU and recommend
  python fit_device.py --list                          # show the whole model catalog
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

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

# Free/available RAM × this factor = runtime wire budget (leave headroom for OS/IDE).
WIRE_SAFETY_FACTOR = 0.60

# Profiles that bias Default for wire toward the smallest catalog fit when free
# RAM is unknown or tight (WSL/iGPU/CPU laptops — the LENOVO 16GB class).
PRESSURE_PRONE_PROFILES = frozenset({
    "wsl-host-cpu",
    "wsl-cpu",
    "linux-cpu",
    "unknown",
})


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
        # Ollama OpenAI path often burns a small max_tokens on reasoning and
        # leaves content=""; floor is portable. Do NOT emit openai_think —
        # key presence makes Endpoint.chat send body `think` on every call,
        # which 400s on llama.cpp / MLX / vLLM. Opt in only for Ollama.
        q["min_completion_tokens"] = 256
        q["sampling_thinking"] = {"top_p": 0.95, "top_k": 20}
        q["sampling"] = {"top_p": 0.8}
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


# OpenAI-compatible local servers commonly used with personal devices.
# Prefer Ollama (11434) before llama-server (8080) / vLLM (8000).
LOCAL_API_PORTS: tuple[int, ...] = (11434, 8080, 8000)


def default_gateway_ip() -> str | None:
    """Best-effort default-gateway IPv4 (WSL → Windows host, typical Linux)."""
    try:
        out = _run(["ip", "route", "show", "default"], timeout=3)
    except Exception:
        out = ""
    m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
    if m:
        return m.group(1)
    # Fallback: parse `ip route` without show default
    try:
        out = _run(["ip", "route"], timeout=3)
    except Exception:
        return None
    m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None


def resolv_nameserver_ips() -> list[str]:
    """IPv4 nameservers from /etc/resolv.conf (WSL often lists the Windows host)."""
    path = Path("/etc/resolv.conf")
    if not path.is_file():
        return []
    found: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("nameserver"):
            continue
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", parts[1]):
            if parts[1] not in found:
                found.append(parts[1])
    return found


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    return h in {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def candidate_api_hosts(*, wsl: bool | None = None) -> list[tuple[str, str]]:
    """Ordered (host, source) candidates for a guest-reachable OpenAI API.

    Order (plan contract): loopback → default-gateway → resolv nameserver.
    Mirrored-networking localhost is covered by the loopback attempt.
    """
    if wsl is None:
        wsl = detect_wsl()
    ordered: list[tuple[str, str]] = [("127.0.0.1", "loopback")]
    seen = {"127.0.0.1", "localhost"}
    if wsl:
        gw = default_gateway_ip()
        if gw and gw not in seen:
            ordered.append((gw, "default-gateway"))
            seen.add(gw)
        for ns in resolv_nameserver_ips():
            if ns not in seen:
                ordered.append((ns, "resolv-nameserver"))
                seen.add(ns)
    return ordered


def openai_base_url(host: str, port: int) -> str:
    return f"http://{host}:{int(port)}/v1"


def http_get_ok(url: str, *, timeout: float = 1.5) -> bool:
    """True when URL returns HTTP < 500 (connection/refusal → False)."""
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "anchor-fit-device/1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200) or 200) < 500
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        return False


def discover_reachable_openai_base(
    *,
    wsl: bool | None = None,
    ports: tuple[int, ...] | None = None,
    timeout: float = 1.5,
    probe_url=None,
) -> dict | None:
    """Return the first guest-reachable OpenAI-compatible ``/v1`` base URL.

    Result keys: ``base_url``, ``host``, ``port``, ``source``, ``tried``.
    ``None`` if nothing answered.

    ``probe_url`` may be a test double: ``callable(url) -> bool`` or
    ``callable(url, timeout=...) -> bool``.
    """
    check = probe_url or http_get_ok
    port_list = ports or LOCAL_API_PORTS
    tried: list[dict] = []
    for host, source in candidate_api_hosts(wsl=wsl):
        for port in port_list:
            base = openai_base_url(host, port)
            probe = base.rstrip("/") + "/models"
            try:
                ok = bool(check(probe, timeout=timeout))
            except TypeError:
                ok = bool(check(probe))
            tried.append({"url": probe, "ok": ok, "source": source, "host": host, "port": port})
            if ok:
                return {
                    "base_url": base,
                    "host": host,
                    "port": int(port),
                    "source": source,
                    "tried": tried,
                }
    return None


def default_local_port(backend: str, *, prefer_ollama: bool = False) -> int:
    if prefer_ollama:
        return 11434
    return 8000 if backend == "cuda" else 8080


def normalize_openai_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if re.search(r":\d+$", u) and not u.endswith("/v1"):
        u = u + "/v1"
    return u


def resolve_register_base_url(
    proposed: str | None,
    *,
    wsl: bool | None = None,
    backend: str = "metal",
    discover=None,
    http_ok=None,
) -> dict:
    """Pick a guest-reachable base_url for registration / stanza emission.

    Never silently keep a loopback URL when the guest cannot open it and a
    non-loopback candidate answered. Returns ``base_url``, ``ok``, ``rewrote``,
    ``reason``, and optional ``discovery``.
    """
    discover_fn = discover or discover_reachable_openai_base
    check = http_ok or http_get_ok
    wsl_flag = detect_wsl() if wsl is None else wsl
    prefer_ollama = bool(wsl_flag)
    hit = discover_fn(wsl=wsl_flag)

    if proposed:
        proposed = normalize_openai_base_url(proposed)
        m = re.match(r"^https?://([^/:]+)", proposed)
        host = m.group(1) if m else ""
        if is_loopback_host(host):
            try:
                loop_ok = bool(check(proposed.rstrip("/") + "/models", timeout=1.5))
            except TypeError:
                loop_ok = bool(check(proposed.rstrip("/") + "/models"))
            if loop_ok:
                return {
                    "base_url": proposed,
                    "ok": True,
                    "rewrote": False,
                    "reason": "loopback-reachable",
                    "discovery": hit,
                }
            if hit and not is_loopback_host(str(hit.get("host", ""))):
                return {
                    "base_url": hit["base_url"],
                    "ok": True,
                    "rewrote": True,
                    "reason": f"loopback-refused; using {hit['source']}",
                    "discovery": hit,
                }
            return {
                "base_url": proposed,
                "ok": False,
                "rewrote": False,
                "reason": "loopback-refused; no reachable alternative",
                "discovery": hit,
            }
        try:
            ok = bool(check(proposed.rstrip("/") + "/models", timeout=1.5))
        except TypeError:
            ok = bool(check(proposed.rstrip("/") + "/models"))
        return {
            "base_url": proposed,
            "ok": ok,
            "rewrote": False,
            "reason": "proposed-host" if ok else "proposed-host-unreachable",
            "discovery": hit,
        }

    if hit:
        return {
            "base_url": hit["base_url"],
            "ok": True,
            "rewrote": False,
            "reason": f"discovered:{hit['source']}",
            "discovery": hit,
        }

    port = default_local_port(backend, prefer_ollama=prefer_ollama)
    return {
        "base_url": openai_base_url("127.0.0.1", port),
        "ok": False,
        "rewrote": False,
        "reason": "no-reachable-api; loopback-fallback",
        "discovery": None,
    }


def endpoint_stanza(
    model: Model,
    backend: str,
    context: int,
    name: str | None = None,
    *,
    base_url: str | None = None,
) -> str:
    port = default_local_port(backend, prefer_ollama=False)
    served = model.hf if backend == "cuda" else model.name
    url = (base_url or openai_base_url("localhost", port)).rstrip("/")
    quirks = quirks_for(model, context)
    lines = [
        f"  - name: {name or f'{model.name}-local'}",
        f"    tier: {model.tier}",
        f"    base_url: {url}",
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
    if isinstance(v, dict):
        inner = ", ".join(f"{k}: {_yaml_val(val)}" for k, val in v.items())
        return "{" + inner + "}"
    if isinstance(v, str) and any(c in v for c in " :{}#'\""):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def fitting_models(memory_gb: float, quant: str, context: int) -> list[Model]:
    """Catalog entries that fit, largest (most capable) first."""
    fits = [m for m in CATALOG if estimate_memory_gb(m.params_b, quant, context) <= memory_gb]
    return sorted(fits, key=lambda m: m.params_b, reverse=True)


def detect_available_memory_gb() -> float | None:
    """Guest free/available RAM in GB (Linux MemAvailable; best-effort elsewhere)."""
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
        m = re.search(r"MemAvailable:\s+(\d+)\s+kB", text)
        if m:
            return int(m.group(1)) / (1024 * 1024)
        m = re.search(r"MemFree:\s+(\d+)\s+kB", text)
        if m:
            return int(m.group(1)) / (1024 * 1024)
    except OSError:
        pass
    return None


def default_wire_model(
    fits: list[Model],
    *,
    quant: str,
    context: int,
    free_gb: float | None = None,
    available_gb: float | None = None,
    profile: str | None = None,
    total_ram_gb: float | None = None,
    safety_factor: float = WIRE_SAFETY_FACTOR,
) -> tuple[Model, str]:
    """Pick the memory-safer default for config files + a pressure label.

    Returns ``(model, pressure)`` where ``pressure`` is ``\"low\"`` or ``\"high\"``.

    * **Max fit** remains ``fits[0]`` (largest under the usable/catalog budget).
    * **Default for wire** prefers a model whose estimate fits
      ``free_or_available * safety_factor`` when that figure is known.
    * If free/available is unknown, pressure-prone profiles (WSL CPU/iGPU, linux
      CPU, unified ≤24GB) get the **smallest** fit; otherwise max fit.
    """
    if not fits:
        raise ValueError("fits must be non-empty")
    max_fit = fits[0]
    smallest = min(fits, key=lambda m: m.params_b)
    profile = profile or ""
    pressure_prone = (
        profile in PRESSURE_PRONE_PROFILES
        or (total_ram_gb is not None and total_ram_gb <= 24)
        or ("igpu" in profile)
    )

    runtime_src = available_gb if available_gb is not None else free_gb
    if runtime_src is not None:
        budget = float(runtime_src) * float(safety_factor)
        runtime_fits = [
            m for m in fits
            if estimate_memory_gb(m.params_b, quant, context) <= budget
        ]
        if runtime_fits and max_fit in runtime_fits:
            return max_fit, "low"
        if runtime_fits:
            return min(runtime_fits, key=lambda m: m.params_b), "high"
        return smallest, "high"

    if pressure_prone:
        return smallest, "high"
    return max_fit, "low"


def print_catalog() -> None:
    print(f"{'model':26s} {'params':>7s}  {'tier':14s} family")
    for m in CATALOG:
        print(f"{m.name:26s} {m.params_b:6.0f}B  {m.tier:14s} {m.family}"
              + (f"   # {m.note}" if m.note else ""))


def _run(cmd: list[str], timeout: int = 8) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def detect_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
        return "microsoft" in text or "wsl" in text
    except OSError:
        return False


def detect_total_ram_gb() -> float | None:
    # Linux / WSL
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
        m = re.search(r"MemTotal:\s+(\d+)\s+kB", text)
        if m:
            return int(m.group(1)) / (1024 * 1024)
    except OSError:
        pass
    # macOS
    out = _run(["sysctl", "-n", "hw.memsize"])
    if out.strip().isdigit():
        return int(out.strip()) / (1024 ** 3)
    return None


def _parse_nvidia_smi_vram_gb(out: str) -> float | None:
    nums = []
    for line in out.splitlines():
        line = line.strip()
        if line.replace(".", "", 1).isdigit():
            nums.append(float(line))
    if not nums:
        return None
    # nvidia-smi nounits is MiB when values are large
    return max(nums) / 1024.0 if max(nums) > 256 else max(nums)


def detect_cuda_vram_gb() -> float | None:
    cmds: list[list[str]] = []
    for exe in ("nvidia-smi", "nvidia-smi.exe"):
        found = shutil.which(exe)
        if found:
            cmds.append([found, "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    for path in (
        "/mnt/c/Windows/System32/nvidia-smi.exe",
        "/mnt/c/WINDOWS/System32/nvidia-smi.exe",
    ):
        if Path(path).is_file():
            cmds.append([path, "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    for cmd in cmds:
        vram = _parse_nvidia_smi_vram_gb(_run(cmd))
        if vram is not None:
            return vram
    return None


def detect_apple_silicon() -> bool:
    if platform.system() != "Darwin":
        return False
    out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    if "apple" in out.lower():
        return True
    out = _run(["uname", "-m"])
    return "arm64" in out.lower()


def _powershell_exe() -> str | None:
    for name in ("powershell.exe", "pwsh.exe"):
        p = shutil.which(name)
        if p:
            return p
    for candidate in (
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def probe_windows_host() -> dict | None:
    """Read bare-metal Windows facts from WSL via powershell.exe (no user-run .ps1).

    Returns None if not invokable. Does not install anything.
    """
    ps = _powershell_exe()
    if not ps:
        return None
    # Single JSON blob — keep the script compact for subprocess
    # AdapterRAM is often a bogus signed value for iGPUs — names only.
    script = (
        "$ErrorActionPreference='Stop';"
        "$cs=Get-CimInstance Win32_ComputerSystem;"
        "$os=Get-CimInstance Win32_OperatingSystem;"
        "$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1;"
        "$gpus=@(Get-CimInstance Win32_VideoController|ForEach-Object{"
        "  [pscustomobject]@{Name=$_.Name}"
        "});"
        "$ollama=$null; try{$ollama=(Get-Command ollama -ErrorAction SilentlyContinue).Source}catch{};"
        "[pscustomobject]@{"
        "  TotalRAM_GB=[math]::Round($cs.TotalPhysicalMemory/1GB,1);"
        "  FreeRAM_GB=[math]::Round($os.FreePhysicalMemory/1MB,1);"
        "  Manufacturer=$cs.Manufacturer; Model=$cs.Model;"
        "  CPU=$cpu.Name; LogicalCPUs=$cs.NumberOfLogicalProcessors;"
        "  GPUs=$gpus; OllamaPath=$ollama"
        "}|ConvertTo-Json -Compress -Depth 4"
    )
    try:
        p = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = (p.stdout or "").strip().lstrip("\ufeff")
    # PowerShell may emit CRLF; take last JSON-looking line if mixed with noise
    if not raw.startswith("{"):
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                raw = line
                break
    if not raw.startswith("{"):
        return None
    try:
        import json
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    gpus = data.get("GPUs") or []
    if isinstance(gpus, dict):
        gpus = [gpus]
    gpu_names = [str(g.get("Name") or "") for g in gpus if isinstance(g, dict)]
    # Discrete NVIDIA / AMD heuristics (iGPU AdapterRAM is unreliable — ignore for fit)
    has_nvidia_name = any("nvidia" in n.lower() for n in gpu_names)
    has_amd_dgpu = any(
        re.search(r"\b(radeon|rx\s*\d)", n, re.I) and "graphics" in n.lower()
        for n in gpu_names
    )
    # Iris/UHD/Vega iGPU → shared memory class
    igpu_only = bool(gpu_names) and not has_nvidia_name and not has_amd_dgpu

    host_nvidia_vram = None
    if has_nvidia_name:
        host_nvidia_vram = detect_cuda_vram_gb()  # tries nvidia-smi.exe too

    tools_host = {
        "powershell": True,
        "ollama_windows": bool(data.get("OllamaPath")),
        "nvidia_smi_windows": bool(
            shutil.which("nvidia-smi.exe")
            or Path("/mnt/c/Windows/System32/nvidia-smi.exe").is_file()
        ),
    }

    return {
        "total_ram_gb": data.get("TotalRAM_GB"),
        "free_ram_gb": data.get("FreeRAM_GB"),
        "manufacturer": data.get("Manufacturer"),
        "model": data.get("Model"),
        "cpu": data.get("CPU"),
        "logical_cpus": data.get("LogicalCPUs"),
        "gpu_names": gpu_names,
        "has_nvidia": has_nvidia_name,
        "has_amd_dgpu": bool(has_amd_dgpu),
        "igpu_only": igpu_only,
        "cuda_vram_gb": host_nvidia_vram,
        "tools_host": tools_host,
        "source": "powershell.exe",
    }


def probe_device() -> dict:
    """Inspect guest + (when WSL) bare-metal Windows host; size fits for best executor."""
    system = platform.system()  # Linux, Darwin, Windows
    machine = platform.machine()
    wsl = detect_wsl()
    guest_ram = detect_total_ram_gb()
    guest_cuda = detect_cuda_vram_gb()
    apple = detect_apple_silicon()
    win_host = probe_windows_host() if wsl else None

    # Prefer host RAM for recommendations when WSL can see bare metal
    total_ram = None
    if win_host and win_host.get("total_ram_gb"):
        try:
            total_ram = float(win_host["total_ram_gb"])
        except (TypeError, ValueError):
            total_ram = guest_ram
    else:
        total_ram = guest_ram

    cuda_vram = None
    if win_host and win_host.get("cuda_vram_gb"):
        cuda_vram = float(win_host["cuda_vram_gb"])
    elif guest_cuda:
        cuda_vram = guest_cuda

    recommend_bare_metal = False
    executor_placement = "local"  # where to run the model server

    if apple:
        backend = "metal"
        usable = (total_ram * 0.75) if total_ram else None
        profile = "apple-silicon"
        executor_placement = "macos-host"
    elif wsl and win_host:
        recommend_bare_metal = True
        executor_placement = "windows-host"
        if cuda_vram and cuda_vram >= 4 and win_host.get("has_nvidia"):
            backend = "cuda"
            usable = cuda_vram * 0.90
            profile = "wsl-host-cuda"
        else:
            # CPU / iGPU: size against host RAM (better than WSL cgroup view)
            backend = "metal"  # llama.cpp GGUF path
            usable = (total_ram * 0.55) if total_ram else None
            profile = "wsl-host-cpu"
    elif wsl and guest_cuda and guest_cuda >= 4:
        backend = "cuda"
        usable = guest_cuda * 0.90
        profile = "wsl-cuda"
        executor_placement = "wsl-guest"
    elif wsl:
        backend = "metal"
        usable = (guest_ram * 0.50) if guest_ram else None
        profile = "wsl-cpu"
        executor_placement = "wsl-guest"
        recommend_bare_metal = True  # still prefer host if PS unavailable
    elif cuda_vram and cuda_vram >= 4:
        backend = "cuda"
        usable = cuda_vram * 0.90
        profile = "linux-cuda" if system == "Linux" else "cuda-gpu"
        executor_placement = "linux-host"
    elif system == "Linux":
        backend = "metal"
        usable = (total_ram * 0.50) if total_ram else None
        profile = "linux-cpu"
        executor_placement = "linux-host"
    else:
        backend = "metal"
        usable = (total_ram * 0.50) if total_ram else None
        profile = "unknown"
        executor_placement = "local"

    tools = {
        "python3": bool(shutil.which("python3") or shutil.which("python")),
        "llama-server": bool(shutil.which("llama-server") or shutil.which("llama-cli")),
        "ollama": bool(shutil.which("ollama")),
        "vllm": bool(shutil.which("vllm")),
        "nvidia-smi": bool(shutil.which("nvidia-smi")),
        "brew": bool(shutil.which("brew")),
        "powershell.exe": bool(_powershell_exe()) if wsl else False,
    }
    if win_host and win_host.get("tools_host"):
        tools.update({f"host_{k}": v for k, v in win_host["tools_host"].items()})

    guest_available = detect_available_memory_gb()
    host_free = None
    if win_host and win_host.get("free_ram_gb") is not None:
        try:
            host_free = float(win_host["free_ram_gb"])
        except (TypeError, ValueError):
            host_free = None
    # Prefer host free when recommending a Windows-host executor; else guest MemAvailable.
    free_memory_gb = host_free if (recommend_bare_metal and host_free is not None) else guest_available
    available_memory_gb = guest_available

    # Guest-reachable OpenAI API (critical on WSL where Windows Ollama ≠ guest localhost).
    reg = resolve_register_base_url(None, wsl=wsl, backend=backend)
    reachable = reg.get("discovery") if reg.get("ok") else None

    return {
        "system": system,
        "machine": machine,
        "wsl": wsl,
        "apple_silicon": apple,
        "guest_ram_gb": round(guest_ram, 1) if guest_ram else None,
        "total_ram_gb": round(total_ram, 1) if total_ram else None,
        "cuda_vram_gb": round(cuda_vram, 1) if cuda_vram else None,
        "usable_memory_gb": round(usable, 1) if usable else None,
        "free_memory_gb": round(free_memory_gb, 1) if free_memory_gb is not None else None,
        "available_memory_gb": round(available_memory_gb, 1) if available_memory_gb is not None else None,
        "backend": backend,
        "profile": profile,
        "tools": tools,
        "windows_host": win_host,
        "recommend_bare_metal": recommend_bare_metal,
        "executor_placement": executor_placement,
        "reachable_api": reachable,
        "register_base_url": reg.get("base_url"),
        "register_ok": bool(reg.get("ok")),
        "register_reason": reg.get("reason"),
    }


def print_probe(probe: dict) -> None:
    print("## Machine probe\n")
    print(f"  OS (guest):      {probe['system']} ({probe['machine']})"
          + (" + WSL2" if probe["wsl"] else ""))
    if probe["apple_silicon"]:
        print("  Apple Silicon:   yes (unified memory)")

    wh = probe.get("windows_host")
    if wh:
        print("  Bare metal:      Windows host (via powershell.exe)")
        if wh.get("manufacturer") or wh.get("model"):
            print(f"  Host machine:    {wh.get('manufacturer') or ''} {wh.get('model') or ''}".rstrip())
        if wh.get("cpu"):
            print(f"  Host CPU:        {wh['cpu']}")
        if wh.get("total_ram_gb") is not None:
            print(f"  Host RAM:        ~{wh['total_ram_gb']} GB"
                  + (f" ({wh['free_ram_gb']} GB free)" if wh.get("free_ram_gb") is not None else ""))
        if probe.get("guest_ram_gb") is not None:
            print(f"  WSL RAM view:    ~{probe['guest_ram_gb']} GB (cgroup; often lower than host)")
        if wh.get("gpu_names"):
            print(f"  Host GPUs:       {', '.join(wh['gpu_names'])}")
        if wh.get("igpu_only"):
            print("  GPU class:       integrated / shared-memory (not discrete CUDA VRAM)")
        if wh.get("has_nvidia"):
            print("  NVIDIA dGPU:     yes")
        if probe.get("cuda_vram_gb") is not None:
            print(f"  CUDA VRAM:       ~{probe['cuda_vram_gb']:.1f} GB")
    else:
        if probe.get("total_ram_gb") is not None:
            print(f"  System RAM:      ~{probe['total_ram_gb']:.1f} GB")
        if probe.get("cuda_vram_gb") is not None:
            print(f"  CUDA VRAM:       ~{probe['cuda_vram_gb']:.1f} GB")
        if probe["wsl"]:
            print("  Bare metal:      (powershell.exe unavailable — WSL-only view)")

    print(f"  Profile:         {probe['profile']}")
    print(f"  Backend:         {probe['backend']}")
    print(f"  Executor place:  {probe.get('executor_placement', 'local')}")
    if probe.get("recommend_bare_metal"):
        print("  Recommendation:  run model server on **Windows bare metal**; "
              "keep Anchor/agents in WSL")
    if probe.get("usable_memory_gb") is not None:
        print(f"  Usable for model:~{probe['usable_memory_gb']:.1f} GB (conservative fit budget)")
    else:
        print("  Usable for model: unknown — pass --memory manually")
    if probe.get("free_memory_gb") is not None:
        print(f"  Free / runtime:  ~{probe['free_memory_gb']:.1f} GB "
              f"(wire budget ×{WIRE_SAFETY_FACTOR:.2f})")
    elif probe.get("available_memory_gb") is not None:
        print(f"  MemAvailable:    ~{probe['available_memory_gb']:.1f} GB "
              f"(wire budget ×{WIRE_SAFETY_FACTOR:.2f})")

    # Reachable API — never imply guest localhost works when it does not.
    ra = probe.get("reachable_api")
    if ra:
        print(f"  Reachable API:   {ra['base_url']}  (via {ra['source']})")
    elif probe.get("register_base_url"):
        status = "OK" if probe.get("register_ok") else "UNVERIFIED / unreachable from guest"
        print(f"  Reachable API:   {probe['register_base_url']}  ({status})")
        if probe.get("wsl") and not probe.get("register_ok"):
            print("  Warn:            guest cannot open a local OpenAI API yet — start "
                  "Ollama/llama-server on the Windows host (0.0.0.0), then re-run --probe. "
                  "Do not register dead localhost.")
    if probe.get("wsl") and ra and ra.get("source") != "loopback":
        print("  Note:            guest localhost refused (or was skipped); using the "
              "Windows host address. Gateway IPs can change after `wsl --shutdown` — "
              "re-probe before rewriting overlays. Optional: mirrored networking so "
              "localhost works "
              "(https://learn.microsoft.com/en-us/windows/wsl/networking).")

    print("\n  Tools:")
    for name, ok in probe["tools"].items():
        print(f"    {'yes' if ok else 'no ':3}  {name}")


def official_links(model: Model) -> list[tuple[str, str]]:
    """(label, url) for lean popular model docs — markdown-friendly."""
    family_links = {
        "qwen3": ("Qwen3 quick start",
                  "https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html"),
        "gemma3": ("Gemma 3 docs", "https://ai.google.dev/gemma/docs/core"),
        "mistral": ("Mistral Small on Hugging Face",
                    "https://huggingface.co/mistralai/Mistral-Small-24B-Instruct-2501"),
        "llama": ("Llama 3.3 Instruct",
                  "https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct"),
        "deepseek-r1-distill": ("DeepSeek-R1 distills",
                                "https://huggingface.co/collections/deepseek-ai/deepseek-r1"),
    }
    links = []
    if model.family in family_links:
        links.append(family_links[model.family])
    links.append((f"Weights (GGUF): {model.gguf}", f"https://huggingface.co/{model.gguf}"))
    if model.mlx:
        links.append((f"MLX: {model.mlx}", f"https://huggingface.co/{model.mlx}"))
    if model.hf:
        links.append((f"HF / vLLM: {model.hf}", f"https://huggingface.co/{model.hf}"))
    return links


def print_install_guidance(probe: dict) -> None:
    """Clickable-friendly install pointers for the detected OS/profile."""
    print("\n## Install / run (this system)\n")
    profile = probe.get("profile") or ""
    tools = probe.get("tools") or {}

    # Shared tooling links
    print("Common runtimes:")
    print("- [llama.cpp](https://github.com/ggerganov/llama.cpp) — GGUF, CPU/Metal/CUDA")
    print("- [Ollama](https://ollama.com/download) — simple local pull/run (good WSL/desktop on-ramp)")
    print("- [vLLM](https://docs.vllm.ai/en/latest/getting_started/installation.html) — CUDA servers")
    print("- [MLX-LM](https://github.com/ml-explore/mlx-lm) — Apple Silicon")
    print("- Anchor adapters: `hardware/personal-devices/configs/` + "
          "[personal devices guide](https://carefreeinv.com/anchor/docs/hardware/personal-devices)")
    print()

    if profile == "apple-silicon":
        print("### macOS Apple Silicon\n")
        print("1. Install [Homebrew](https://brew.sh/) if needed, then:")
        print("   ```bash")
        print("   brew install llama.cpp")
        print("   # or: pip install mlx-lm")
        print("   ```")
        print("2. Fit + launch (from Anchor repo):")
        print("   ```bash")
        print("   python scripts/fit_device.py --probe")
        print("   MODEL=… CONTEXT=… ./hardware/personal-devices/configs/serve-apple-silicon.sh")
        print("   ```")
        print("3. Docs: [Mac Mini](https://carefreeinv.com/anchor/docs/hardware/personal-devices/mac-mini) · "
              "[MacBook Pro](https://carefreeinv.com/anchor/docs/hardware/personal-devices/macbook-pro)")
    elif profile in {"wsl-cpu", "wsl-cuda", "wsl-host-cpu", "wsl-host-cuda"} or probe.get(
        "recommend_bare_metal"
    ):
        print("### WSL2 detected — prefer **Windows bare-metal** model server\n")
        print("Run the **qualifying model on the Windows host** (full RAM/GPU). Keep "
              "Anchor, git, and coding agents in WSL; point `endpoints.yaml` at the host API.\n")
        print("Host facts above come from `powershell.exe` when available "
              "(no need for you to run a `.ps1` for probing).\n")
        print("1. On **Windows** (not WSL), install a host executor:")
        print("   - Easiest: [Ollama for Windows](https://ollama.com/download) "
              "(GPU if NVIDIA drivers present; otherwise CPU)")
        print("   - Or [llama.cpp Windows releases](https://github.com/ggerganov/llama.cpp/releases)")
        print("2. On Windows, pull/serve the recommended GGUF/small model, e.g. Ollama "
              "`qwen2.5:7b` / Qwen3 small tags, listening on `0.0.0.0:11434` or `:8080`.")
        reg_url = probe.get("register_base_url")
        ra = probe.get("reachable_api")
        if ra:
            print(f"3. From **WSL**, this probe already reached **`{ra['base_url']}`** "
                  f"(via {ra['source']}). Prefer that over guessing localhost.")
        else:
            print("3. From **WSL**, probe candidates in order: `127.0.0.1` → default "
                  "gateway (`ip route`) → `resolv.conf` nameserver. Mirrored networking "
                  "can make localhost work "
                  "(https://learn.microsoft.com/en-us/windows/wsl/networking); "
                  "otherwise use the gateway IP — not a blind `localhost`.")
        if reg_url and probe.get("register_ok"):
            print(f"4. Register in Anchor (machine-local overlay): `{reg_url}` — "
                  "re-run `--probe` after reboot; gateway IPs churn.")
        elif reg_url:
            print(f"4. Do **not** register dead localhost. After the host API is up, "
                  f"re-run `--probe`; suggested fallback was `{reg_url}` "
                  f"({probe.get('register_reason')}).")
        else:
            print("4. Register only a URL `curl` from the guest can hit.")
        print("5. Optional CUDA-in-WSL only if you insist on Linux-side GPU: "
              "[CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html) — "
              "still usually worse ergonomics than host Ollama/llama.cpp.\n")
        print("#### Fallback: run inside WSL (only if host install is blocked)\n")
        print("- [Ollama for Linux](https://ollama.com/download/linux) or build "
              "[llama.cpp](https://github.com/ggerganov/llama.cpp) in the distro")
        print("- Keep weights on the **Linux filesystem** (`~/models`), not `/mnt/c`")
        print("- Fit budget is lower than host RAM; re-probe after install")
        if not tools.get("ollama") and not tools.get("llama-server") and not tools.get(
            "host_ollama_windows"
        ):
            print("\n**Status:** no model runner detected in WSL or on Windows PATH — "
                  "install [Ollama for Windows](https://ollama.com/download) first "
                  "(recommended).")
    elif profile in {"linux-cuda", "cuda-gpu"}:
        print("### Linux + NVIDIA CUDA\n")
        print("1. NVIDIA driver + [CUDA toolkit](https://developer.nvidia.com/cuda-downloads)")
        print("2. [vLLM install](https://docs.vllm.ai/en/latest/getting_started/installation.html) "
              "or llama.cpp with CUDA")
        print("3. `python scripts/fit_device.py --probe --backend cuda`")
        print("4. `./hardware/personal-devices/configs/serve-cuda.sh`")
        print("5. Docs: [RTX laptop](https://carefreeinv.com/anchor/docs/hardware/personal-devices/rtx-laptop) · "
              "[Desktop tower](https://carefreeinv.com/anchor/docs/hardware/personal-devices/desktop-tower)")
    elif profile == "linux-cpu":
        print("### Linux CPU (no GPU)\n")
        print("Use small GGUF models only. Install [llama.cpp](https://github.com/ggerganov/llama.cpp) "
              "or [Ollama](https://ollama.com/download/linux). Prefer ≤8–14B Q4.")
    else:
        print("### Generic\n")
        print("Pass explicit `--memory` / `--backend` if probe is incomplete. "
              "See [personal devices](https://carefreeinv.com/anchor/docs/hardware/personal-devices).")


def print_recommendation_report(
    probe: dict,
    memory_gb: float,
    backend: str,
    quant: str,
    context: int,
    *,
    emit_endpoint: bool = False,
    name: str | None = None,
) -> None:
    fits = fitting_models(memory_gb, quant, context)
    if not fits:
        smallest = min(CATALOG, key=lambda m: m.params_b)
        need = estimate_memory_gb(smallest.params_b, quant, context)
        raise SystemExit(
            f"Nothing in the catalog fits {memory_gb:.0f}GB at {quant}/{context} context. "
            f"The smallest model ({smallest.name}) needs ~{need:.1f}GB — lower --context or free up memory.")

    max_fit = fits[0]
    wire, pressure = default_wire_model(
        fits,
        quant=quant,
        context=context,
        free_gb=probe.get("free_memory_gb"),
        available_gb=probe.get("available_memory_gb"),
        profile=probe.get("profile"),
        total_ram_gb=probe.get("total_ram_gb"),
    )

    # Prefer a guest-reachable base_url (WSL→Windows host) over blind localhost.
    base_url = None
    if probe.get("register_ok") and probe.get("register_base_url"):
        base_url = probe["register_base_url"]
    elif probe.get("reachable_api"):
        base_url = probe["reachable_api"]["base_url"]
    elif probe.get("wsl") or str(probe.get("profile") or "").startswith("wsl"):
        reg = resolve_register_base_url(None, wsl=True, backend=backend)
        if reg.get("ok"):
            base_url = reg["base_url"]
        elif not reg.get("ok") and reg.get("reason", "").startswith("loopback-refused"):
            # Refuse silent dead localhost in emitted stanza — still print warning.
            base_url = None

    if emit_endpoint:
        if probe.get("wsl") and not base_url and not probe.get("register_ok"):
            raise SystemExit(
                "WSL guest has no reachable OpenAI API yet — refusing to emit a "
                "dead localhost stanza. Start the host server, then re-run "
                "`fit_device.py --probe --emit-endpoint`.")
        # Autowire / config writers use the memory-safer default, not max fit.
        print(endpoint_stanza(wire, backend, context, name, base_url=base_url))
        return

    ctx_ceiling = max_context_for(max_fit.params_b, quant, memory_gb)
    est_max = estimate_memory_gb(max_fit.params_b, quant, context)
    est_wire = estimate_memory_gb(wire.params_b, quant, context)
    place = probe.get("executor_placement") or "local"
    print(f"\n## Fit ({memory_gb:.0f}GB usable, backend={backend}, quant={quant}, "
          f"context={context}, executor={place})\n")
    if probe.get("recommend_bare_metal"):
        print("**Placement:** serve this model on **Windows bare metal** (host executor); "
              "do not treat WSL cgroup RAM as the ceiling when host RAM is larger.\n")
    if base_url:
        print(f"**Reachable API (use this `base_url`):** `{base_url}`\n")
    elif probe.get("wsl"):
        print("**Reachable API:** none from this guest yet — do **not** register "
              "`http://localhost:…` until `--probe` shows a Reachable API line.\n")
    print(f"**Max fit** (capability ceiling): **{max_fit.name}** "
          f"({max_fit.params_b:.0f}B, tier `{max_fit.tier}`) — est. ~{est_max:.1f}GB")
    if max_fit.note:
        print(f"- note: {max_fit.note}")
    print(f"**Default for wire** (Aider / `.env` / launcher): **{wire.name}** "
          f"({wire.params_b:.0f}B, tier `{wire.tier}`) — est. ~{est_wire:.1f}GB "
          f"— memory_pressure=`{pressure}`")
    if wire.name != max_fit.name:
        print(f"- opt-up: pass an explicit model / confirm to use **{max_fit.name}** "
              f"when free RAM allows (e.g. `AIDER_MODEL` / `--8b` style flags)")
    if wire.note and wire.name != max_fit.name:
        print(f"- note: {wire.note}")
    if ctx_ceiling > context:
        print(f"- headroom: up to ~{ctx_ceiling} context on {memory_gb:.0f}GB")
    elif ctx_ceiling and ctx_ceiling < context:
        print(f"- tight: {context} context may be over budget; ~{ctx_ceiling} is safer")

    print("\n**Links (weights + official docs) — default for wire:**")
    for label, url in official_links(wire):
        print(f"- [{label}]({url})")
    if wire.name != max_fit.name:
        print("\n**Links — max fit (opt-up):**")
        for label, url in official_links(max_fit):
            print(f"- [{label}]({url})")

    print("\n**Also fits (smaller / swarm-friendly):**")
    for m in fits[1:5]:
        print(f"- **{m.name}** ({m.params_b:.0f}B, `{m.tier}`) — "
              f"[GGUF](https://huggingface.co/{m.gguf})")

    print("\n**Launch (default for wire):**")
    print(f"```bash\n{launch_command(wire, backend, quant, context)}\n```")
    print("\n**endpoints.yaml stanza (default for wire):**")
    if probe.get("wsl") and not base_url:
        print("```text")
        print("# refused: no guest-reachable API — re-run --probe after host Ollama is up")
        print("```")
    else:
        print("```yaml")
        print(endpoint_stanza(wire, backend, context, name, base_url=base_url))
        print("```")
        if base_url and not is_loopback_host(base_url.split("://", 1)[-1].split(":")[0]):
            print("\n(Machine-local overlay only — do not commit this host gateway IP as "
                  "fleet-wide truth. Re-probe after `wsl --shutdown` / reboot.)")
    print("\n(Memory is a conservative estimate — confirm with `scripts/benchmark.py`.)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--memory", type=float, help="GB of RAM/VRAM available for the model "
                                                 "(unified-memory Macs: leave ~25%% for the OS)")
    ap.add_argument("--backend", choices=["metal", "mlx", "cuda"], default=None,
                    help="metal = llama.cpp (Apple/CPU GGUF), mlx = MLX, cuda = vLLM")
    ap.add_argument("--quant", choices=list(QUANT_BYTES), help="override the quantization (default q4)")
    ap.add_argument("--context", type=int, default=8192, help="context length to size for (default 8192)")
    ap.add_argument("--name", help="endpoints.yaml name for the emitted stanza")
    ap.add_argument("--emit-endpoint", action="store_true",
                    help="print only the endpoints.yaml stanza for the best fit")
    ap.add_argument("--probe", action="store_true",
                    help="detect OS/RAM/GPU, print install guidance, and fit models")
    ap.add_argument("--list", action="store_true", help="print the model catalog and exit")
    args = ap.parse_args()

    if args.list:
        print_catalog()
        return

    probe: dict | None = None
    if args.probe:
        probe = probe_device()
        print_probe(probe)
        print_install_guidance(probe)
        memory = args.memory if args.memory is not None else probe.get("usable_memory_gb")
        backend = args.backend or probe.get("backend") or "metal"
        if memory is None:
            raise SystemExit(
                "Probe could not determine usable memory. Re-run with --memory <GB> "
                "(VRAM for CUDA; ~75% of RAM on Apple Silicon; ~50% of RAM for CPU/WSL).")
        quant = args.quant or BACKEND_DEFAULT_QUANT.get(backend, "q4")
        print_recommendation_report(
            probe, memory, backend, quant, args.context,
            emit_endpoint=args.emit_endpoint, name=args.name,
        )
        return

    if args.memory is None:
        raise SystemExit(
            "Pass --memory <GB> or --probe. See --list for the catalog.")

    backend = args.backend or "metal"
    quant = args.quant or BACKEND_DEFAULT_QUANT[backend]
    print_recommendation_report(
        {"profile": "manual"}, args.memory, backend, quant, args.context,
        emit_endpoint=args.emit_endpoint, name=args.name,
    )


if __name__ == "__main__":
    main()
