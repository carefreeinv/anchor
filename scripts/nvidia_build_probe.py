#!/usr/bin/env python3
"""Detect whether NVIDIA Build (hosted OpenAI-compatible inference at
https://integrate.api.nvidia.com/v1, keyed per-operator from build.nvidia.com)
is configured and reachable, and decide whether an Aider (or other
Anchor-guided) session should prefer it over local inference.

Distinct from self-hosted NIM (platforms/nvidia-nim/NEMOTRON.md,
hardware/h100/configs/nim-compose.yaml) — that's a container an operator runs
themselves on :8000/v1. This module is about NVIDIA's *hosted* developer API.
Never confuse the two in docs or code.

Verified against NVIDIA's own docs/model pages on 2026-09-09: base URL
`https://integrate.api.nvidia.com/v1`, `Authorization: Bearer $NVIDIA_API_KEY`.
No `/v1/models` listing endpoint was confirmed in the fetched docs, so the
probe below treats a non-2xx or network failure as simply "not reachable" —
the safe fallback direction — rather than asserting the endpoint's shape.

Usage:
  python scripts/nvidia_build_probe.py --probe   # human-readable one-shot report
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import requests

BUILD_BASE_URL = "https://integrate.api.nvidia.com/v1"
# Verified live on integrate.api.nvidia.com (2026-10-28). Super 49B is HTTP 410.
DEFAULT_BUILD_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
RETIRED_BUILD_MODELS = frozenset({
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "llama-3.3-nemotron-super-49b-v1",
})

# NVIDIA_API_KEY is the documented Build inference key (from build.nvidia.com).
# NGC_API_KEY is normally a container-registry / NIM-pull credential, not
# guaranteed to carry inference scope — accepted here as a fallback because an
# operator already running self-hosted NIM often has it exported, but the
# reachability probe below is what actually validates any key found: a
# wrong-scope key just fails the probe and falls back to local, never a
# silent success.
ENV_KEY_CANDIDATES: tuple[str, ...] = ("NVIDIA_API_KEY", "NGC_API_KEY")
PROBE_TIMEOUT_S = 3.0


@dataclass
class BuildProbe:
    configured: bool
    reachable: bool
    key_source: str | None  # which env var supplied the key — never the key itself
    base_url: str
    error: str | None = None


def find_api_key(env: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """(key, source_env_var) from the first present candidate, else (None, None)."""
    source_env = env if env is not None else os.environ
    for name in ENV_KEY_CANDIDATES:
        value = source_env.get(name)
        if value:
            return value, name
    return None, None


def probe_build(
    base_url: str = BUILD_BASE_URL,
    timeout: float = PROBE_TIMEOUT_S,
    env: dict[str, str] | None = None,
) -> BuildProbe:
    """Check whether NVIDIA Build is configured (key present) and reachable.

    Never logs or returns the key itself — only which env var it came from.
    A network error, timeout, or non-2xx response is "not reachable": the
    safe direction (callers fall back to local), never a raised exception.
    """
    key, source = find_api_key(env)
    if not key:
        return BuildProbe(configured=False, reachable=False, key_source=None, base_url=base_url)

    try:
        resp = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return BuildProbe(configured=True, reachable=False, key_source=source,
                           base_url=base_url, error=type(exc).__name__)

    if resp.status_code == 200:
        return BuildProbe(configured=True, reachable=True, key_source=source, base_url=base_url)
    return BuildProbe(configured=True, reachable=False, key_source=source, base_url=base_url,
                       error=f"HTTP {resp.status_code}")


def choose_build_model(ids: list[str] | None) -> str:
    """Pick a hosted catalog id. Never Super 49B (HTTP 410 on Build)."""
    live = [
        i for i in (ids or [])
        if i not in RETIRED_BUILD_MODELS
        and not str(i).endswith("llama-3.3-nemotron-super-49b-v1")
    ]
    if DEFAULT_BUILD_MODEL in live:
        return DEFAULT_BUILD_MODEL
    for i in live:
        if "nemotron" in i.lower():
            return i
    return DEFAULT_BUILD_MODEL


def list_build_model_ids(
    probe: BuildProbe,
    *,
    timeout: float = PROBE_TIMEOUT_S,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Live ``GET /v1/models`` ids, or empty. Never raises; never returns the key."""
    if not probe.reachable:
        return []
    key, _source = find_api_key(env)
    if not key:
        return []
    try:
        resp = requests.get(
            f"{probe.base_url}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            ids.append(str(row["id"]))
        elif isinstance(row, str):
            ids.append(row)
    return ids


def preferred_backend(probe: BuildProbe, *, prefer_local: bool = False) -> str:
    """"build" or "local" — the preference rule.

    Operator override wins: prefer_local (from .aider.conf.yml / conventions /
    an explicit CLI flag) always wins regardless of probe results.
    """
    if prefer_local:
        return "local"
    if probe.configured and probe.reachable:
        return "build"
    return "local"


def explain(probe: BuildProbe, backend: str, *, prefer_local: bool = False) -> str:
    """One-line, human-readable reason for the chosen backend — no secrets."""
    if backend == "build":
        return f"using NVIDIA Build ({probe.base_url}) — key from {probe.key_source}, reachable"
    if prefer_local:
        return "using local — operator preference (prefer_local)"
    if not probe.configured:
        return "using local — no NVIDIA_API_KEY/NGC_API_KEY configured"
    detail = f" ({probe.error})" if probe.error else ""
    return f"using local — NVIDIA Build configured but unreachable{detail}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true", help="run the probe and print a one-line report")
    ap.add_argument("--prefer-local", action="store_true",
                    help="simulate an operator override that always prefers local inference")
    args = ap.parse_args()

    if not args.probe:
        raise SystemExit("Pass --probe to run the check.")

    try:
        from anchor_client import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    probe = probe_build()
    backend = preferred_backend(probe, prefer_local=args.prefer_local)
    print(f"configured: {probe.configured}")
    print(f"reachable:  {probe.reachable}")
    if probe.key_source:
        print(f"key source: {probe.key_source} (value never printed)")
    if probe.error:
        print(f"error:      {probe.error}")
    print(f"backend:    {backend}")
    print(explain(probe, backend, prefer_local=args.prefer_local))


if __name__ == "__main__":
    main()
