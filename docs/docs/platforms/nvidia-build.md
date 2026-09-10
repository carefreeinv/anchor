---
sidebar_position: 7
sidebar_label: NVIDIA Build
---

<!-- synced-from: platforms/nvidia-build/BUILD.md @ 96e784f6e9f40224c47972a831d1862593ce805b -->

# NVIDIA Build

This is NVIDIA's **hosted** developer inference API — no container, no GPU of
your own required, keyed per-operator from
[build.nvidia.com](https://build.nvidia.com). It's a different product from
[self-hosted NIM](/platforms/nvidia-nim): don't conflate the two.

## Why prefer it

Local Aider+Ollama is valuable offline and for tiny swarm edits, but on many
laptops and WSL boxes it is latency-heavy (see [Local Models](/platforms/local-models)
and its memory-safe default). NVIDIA Build is OpenAI-compatible, commonly
free-tier for catalog models, and typically far faster than CPU/iGPU local
inference.

## Configure

```bash
export NVIDIA_API_KEY=nvapi-...
```

| | |
|---|---|
| Base URL | `https://integrate.api.nvidia.com/v1` |
| Auth header | `Authorization: Bearer $NVIDIA_API_KEY` |
| Example model id | `nvidia/llama-3.3-nemotron-super-49b-v1` |

`NGC_API_KEY` (a container-registry / NIM-pull credential) is accepted as a
fallback if `NVIDIA_API_KEY` is absent, but it isn't guaranteed to carry
inference scope — the probe below always does a live check, so a wrong-scope
key simply falls back to local rather than succeeding silently.

## Check whether it's live

```bash
python scripts/nvidia_build_probe.py --probe
```

## Preference rule

| Key present? | Reachable? | Operator override? | Backend |
|---|---|---|---|
| no | — | — | local |
| yes | no | — | local |
| yes | yes | prefer local | local |
| yes | yes | no | **build** |

An absent or unreachable key never crashes a session — it falls back to
local. An explicit operator preference for local always wins, even with a
live Build key.

## Aider wiring

```yaml
openai-api-base: https://integrate.api.nvidia.com/v1
model: openai/nvidia/llama-3.3-nemotron-super-49b-v1
```

```bash
export OPENAI_API_KEY=$NVIDIA_API_KEY
```

## A key on one machine is not project law

Same rule as [Local Models](/platforms/local-models)'s multi-clone guidance —
keys are per-operator, machine-local secrets, never committed, never assumed
shared with a teammate.

Build access and rate limits are NVIDIA's terms and can change without
notice; Anchor does not require a paid account for this default path.
