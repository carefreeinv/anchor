# NVIDIA Build (hosted inference) — preferred over local when configured

<!-- This is NOT self-hosted NIM. See platforms/nvidia-nim/NEMOTRON.md for the
     container you run yourself on :8000/v1. NVIDIA Build is NVIDIA's *hosted*
     developer API — no container, no GPU of your own required — keyed
     per-operator from https://build.nvidia.com. Never conflate the two in
     docs or code; cross-link, don't merge. -->

## Why prefer it

Local Aider+Ollama is valuable offline and for tiny swarm edits, but on many
laptops and WSL boxes it is latency-heavy (see
[Local Models](/platforms/local-models) and its memory-safe default). NVIDIA
Build is OpenAI-compatible, commonly free-tier for catalog models, and
typically far faster than CPU/iGPU local inference. An operator who already
exports a Build key should not have to fight Anchor's local-first wiring to
use it.

## Configure

Get a key from [build.nvidia.com](https://build.nvidia.com), then either
export it or put it in a gitignored repo-root `.env` (see `.env.example`):

```bash
export NVIDIA_API_KEY=nvapi-...
# or: NVIDIA_API_KEY=nvapi-...  in ./.env
```

`anchor` plan verbs and `python scripts/nvidia_build_probe.py --probe` load
that `.env` with setdefault (an already-exported variable wins). The fleet
client (`anchor_client.Endpoint.chat`) sends `Authorization: Bearer …` from
the first set of `ANCHOR_API_KEY`, `NVIDIA_API_KEY`, `NGC_API_KEY`. Never
commit the key; never put it in `endpoints.yaml`.

Hosted catalog ids **churn**. `GET https://integrate.api.nvidia.com/v1/models`
lists what this key can call; a retired id returns HTTP 410. Recheck after
NVIDIA catalog moves — do not treat a year-old example as still live.

Verified against NVIDIA's own docs and a live `/v1/models` + chat smoke
(2026-10-28):

| | |
|---|---|
| Base URL | `https://integrate.api.nvidia.com/v1` |
| Auth header | `Authorization: Bearer $NVIDIA_API_KEY` |
| Example model id | `nvidia/nemotron-3.5-lightning-30b-a3b` |

`NGC_API_KEY` (normally a container-registry / NIM-pull credential) is
accepted as a fallback if `NVIDIA_API_KEY` is absent — an operator already
running self-hosted NIM often has it exported already — but it is **not
guaranteed to carry inference scope**. The probe below always does a live
reachability check regardless of which variable supplied the key, so a
wrong-scope key simply fails the check and falls back to local; it never
succeeds silently.

## Check whether it's live

```bash
python scripts/nvidia_build_probe.py --probe
```

Reports `configured` (a key is present), `reachable` (a live check against
the endpoint succeeded), which env var supplied the key (never the key
itself), and the resulting `backend` (`build` or `local`).

## Preference rule

| Key present? | Reachable? | Operator override (`prefer_local`)? | Backend used |
|---|---|---|---|
| no | — | — | local |
| yes | no (401 / unreachable / timeout) | — | local |
| yes | yes | yes | local |
| yes | yes | no | **build** |

An absent or unreachable key never crashes an Aider session — it falls back
to whatever local path was already documented (Ollama/llama.cpp). An explicit
operator preference for local always wins, even with a live Build key —
Anchor never silently overrides a choice the operator already made.

## Aider wiring

If you're running Aider against this project, point its `.aider.conf.yml` at
the Build endpoint when the probe reports `build`:

```yaml
openai-api-base: https://integrate.api.nvidia.com/v1
model: openai/nvidia/nemotron-3.5-lightning-30b-a3b
```

Aider reads `OPENAI_API_KEY` for any `openai-api-base` target, so also set:

```bash
export OPENAI_API_KEY=$NVIDIA_API_KEY
```

This is a manual step in this plan's scope — the probe reports which backend
to prefer, but no scaffolder writes these Aider conf keys automatically yet.

## A key on one machine is not project law

Same rule as [Local Models](/platforms/local-models)'s multi-clone guidance:
a `NVIDIA_API_KEY` exported on one laptop does not make Build the default for
every operator on this project. Keys are per-operator, machine-local secrets
— never commit one, never assume a teammate has one.

## Terms

Build access and rate limits are NVIDIA's terms and can change without
notice. Anchor does not promise unlimited free inference, and does not
require a paid NVIDIA account for this default path.
