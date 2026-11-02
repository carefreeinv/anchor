---
sidebar_position: 7
sidebar_label: NVIDIA Build
---

<!-- synced-from: platforms/nvidia-build/BUILD.md @ 5e83bc8e5ce57c395029da047dc374ab626a0bf4 -->

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
# or NVIDIA_API_KEY= in a gitignored repo-root .env (see .env.example)
```

`anchor` plan verbs and `nvidia_build_probe.py --probe` load `.env`
(setdefault). The fleet client authorizes from the first set of
`ANCHOR_API_KEY`, `NVIDIA_API_KEY`, `NGC_API_KEY`. Hosted catalog ids churn;
`GET /v1/models` lists live ones, a retired id returns HTTP 410.

| | |
|---|---|
| Base URL | `https://integrate.api.nvidia.com/v1` |
| Auth header | `Authorization: Bearer $NVIDIA_API_KEY` |
| Example model id | `nvidia/nemotron-3.5-lightning-30b-a3b` |

`NGC_API_KEY` (a container-registry / NIM-pull credential) is accepted as a
fallback if `NVIDIA_API_KEY` is absent, but it isn't guaranteed to carry
inference scope — the probe below always does a live check, so a wrong-scope
key simply falls back to local rather than succeeding silently.

## Check whether it's live

```bash
python scripts/nvidia_build_probe.py --probe
```

## Preference rule

`Fleet.pick` (used by `orchestrate.py` and interactive `anchor work --run`)
probes each registry endpoint with `GET {base}/models` (about 3s). Unreachable
LAN rows (for example a powered-off H100) are skipped. Then:

| LAN healthy? | Key present? | Build reachable? | `prefer_local` / `ANCHOR_PREFER_LOCAL`? | Backend used |
|---|---|---|---|---|
| yes | — | — | — | **LAN** (H100 / NIM / listed) |
| no | no | — | — | fail fast (seconds, not a 600s chat hang) |
| no | yes | no | — | fail fast |
| no | yes | yes | yes | fail fast (Build not tried) |
| no | yes | yes | no | **NVIDIA Build** (hosted, free-tier catalog) |

Healthy LAN always wins. Build is fallback, not a silent steal of rack GPUs.
`orchestrate.py --prefer-local` and env `ANCHOR_PREFER_LOCAL=1` skip Build.
The hosted model id comes from live `GET /v1/models`, preferring
`nvidia/nemotron-3.5-lightning-30b-a3b`; Super 49B is retired on Build (HTTP 410).

An absent or unreachable key never hangs a chat — `Fleet.pick` raises
`LookupError` in seconds. An explicit operator preference for local always
wins, even with a live Build key.

## Aider wiring

```yaml
openai-api-base: https://integrate.api.nvidia.com/v1
model: openai/nvidia/nemotron-3.5-lightning-30b-a3b
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
