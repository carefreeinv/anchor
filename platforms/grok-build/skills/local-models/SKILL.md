---
name: local-models
description: >
  Evaluate this machine for cutting-edge lean local models via /local-models.
  Probe OS/RAM/GPU/WSL, recommend fits from Anchor's catalog, and show
  clickable install links and a short procedure for this system (e.g. WSL
  llama.cpp / Ollama). Use when the user runs /local-models, asks what local
  model fits, how to install a local executor, or whether this box can run
  Qwen/Gemma/Mistral locally.
argument-hint: "[--probe|--list|--status] [--memory GB] [--backend metal|mlx|cuda]"
disable-model-invocation: false
metadata:
  short-description: "Probe machine; recommend lean local models + install links"
---

# /local-models — machine fit + local executor install guidance

**Scaffolded skill:** scaffolded into projects via `anchor … --platform claude|grok`.
It is **not** part of the Anchor’s base skill set (unlike `/work`,
`/draft`, `/anchor`). Source of truth lives under `platforms/` in the Anchor
repo and is copied to `.grok/skills/local-models/` (or Claude commands) on scaffold.

Answer: **what lean, popular local models can this machine run**, and **how do
I install/run a model executor here** — with **markdown links** the user can
click (official docs, HF weights, WSL/CUDA/macOS install paths).

Prefer tooling over guesswork: run Anchor’s probe/fit helper, then present a
clear recommendation report in chat.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/local-models` | Full probe + fit + install guidance for this host |
| `/local-models --probe` | Same (explicit) |
| `/local-models --list` | Catalog only (no probe) |
| `/local-models --status` | Probe tools/hardware only; skip long install blurb if already clear |
| `/local-models --memory 16 --backend cuda` | Override probe memory/backend |

`$ARGUMENTS` is everything after `/local-models`.

## Steps

### 1. Locate Anchor scripts

Find `scripts/fit_device.py` (and preferably `hardware/personal-devices/`):

1. Git root of CWD if it contains them
2. Parent `../anchor` when CWD is a sibling project
3. Project `.anchor/scripts/fit_device.py` if fleet-scaffolded there
4. Ask once if still missing

```bash
SCRIPTS=…   # directory containing fit_device.py
```

### 2. Probe + fit (required)

```bash
python3 "$SCRIPTS/fit_device.py" --probe
# or with overrides from $ARGUMENTS:
python3 "$SCRIPTS/fit_device.py" --probe --memory 16 --backend cuda
python3 "$SCRIPTS/fit_device.py" --list
```

If `--probe` fails on memory, re-run with an explicit `--memory` from `free -h` /
Activity Monitor / `nvidia-smi`.

### 3. Present the report in chat (markdown)

Rewrite the tool output into a **readable, link-rich** report. Use real HTTPS
URLs (GitHub, Hugging Face, Microsoft Learn, NVIDIA, Ollama, carefreeinv.com
docs) so the client can render clickable links.

#### Required sections

1. **Machine** — guest OS + WSL?; when WSL, **bare-metal Windows** facts from
   `powershell.exe` (host RAM, CPU, GPUs) vs WSL cgroup RAM
2. **Compatibility** — honest: good / limited (CPU/iGPU) / excellent (CUDA/Metal)
3. **Executor placement** — if WSL: **prefer Windows bare-metal** model server;
   Anchor stays in WSL and points `endpoints.yaml` at the host API
4. **Recommended models** (lean + popular from the fit list, sized to **host**
   usable budget when known) — for each:
   - name, size, Anchor tier
   - why it fits
   - links: official quick start + GGUF/HF weights (from probe output)
5. **Install on this system** — short procedure for the **detected** profile:
   - **WSL2:** lead with [Ollama for Windows](https://ollama.com/download) or
     Windows llama.cpp on the **host** (probe already used `powershell.exe` —
     user need not run a PS1 just to get recommendations); then how WSL reaches
     `localhost` / host IP; WSL-in-guest install only as fallback
   - **Apple Silicon:** brew llama.cpp / MLX → serve script
   - **Linux CUDA:** driver + vLLM or llama.cpp CUDA → serve-cuda.sh
   - **Linux CPU:** small GGUF only
6. **Next Anchor steps** — register endpoint; optional `/install-anchor` if CLI missing;
   point at personal-devices hardware docs
7. **Offer a follow-up draft plan** (required close) — see step 6 below

#### Link bank (always prefer these when relevant)

| Topic | URL |
|-------|-----|
| WSL install | https://learn.microsoft.com/en-us/windows/wsl/install |
| CUDA on WSL | https://docs.nvidia.com/cuda/wsl-user-guide/index.html |
| llama.cpp | https://github.com/ggerganov/llama.cpp |
| Ollama download | https://ollama.com/download |
| Ollama Linux install | https://ollama.com/download/linux |
| vLLM install | https://docs.vllm.ai/en/latest/getting_started/installation.html |
| MLX-LM | https://github.com/ml-explore/mlx-lm |
| Homebrew | https://brew.sh/ |
| Qwen3 quick start | https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html |
| Gemma 3 | https://ai.google.dev/gemma/docs/core |
| DeepSeek-R1 distills | https://huggingface.co/collections/deepseek-ai/deepseek-r1 |
| Anchor personal devices | https://carefreeinv.com/anchor/docs/hardware/personal-devices |

Also link concrete HF repos printed by `fit_device.py` for the recommended model.

### 4. Do not silently install heavy stacks

- **Never** `pip install vllm` / download multi‑GB weights without user confirmation.
- **May** run read-only probes (`nvidia-smi`, `free`, `fit_device.py --probe`).
- If the user asks to install, show the exact commands and confirm first (sudo risk).

### 5. Catalog philosophy (what “lean popular” means)

Prefer models in `fit_device.py`’s catalog (Qwen3, Gemma 3, Mistral Small, R1
distills, Llama 3.3) at **Q4**, short context (8k default), official chat
templates — not giant FP16 frontier weights on a laptop.

### 5b. Routing policy (reconfigure drafts + recommendations)

Wire local models into the project **without** promoting small locals into
heavy work — and **without** ignoring the operator’s model-priority list.

1. **User model order is primary.** Read (when present):
   - `~/.config/anchor/defaults` → `MODEL_PRIORITY=…` (via `config.sh` / saved defaults)
   - project `.anchor/conventions.md` (or legacy `ANCHOR-CONVENTIONS.md`) model-priority section
   Treat that ordered list as the **first** rule for which model/endpoint to try
   (including any `local` / endpoint names the user already listed).

2. **Right-size by capability (hard).** Catalog `tier` from the probe is a
   ceiling, not a promotion:
   | Local fit tier | May be preferred for |
   |----------------|----------------------|
   | `swarm` / small | Boilerplate, thin executor, cheap swarm work only |
   | `executor` / mid | Scoped multi-file / routine mid work |
   | `executor-heavy` / `reasoner` | Heavier local inference **only if** the probe
     budget truly fits that model class on this host |

   Never configure a 4B–8B CPU/iGPU local as the default for architecture,
   multi-hour autonomy, or other frontier-class tasks.

3. **Heavy inference when the host can.** If the probe shows real heavy-local
   capacity (e.g. large unified memory, discrete NVIDIA VRAM, fits
   `executor-heavy` / large catalog entries), then for **heavy inference** work:
   - Prefer a **local** endpoint that is **fit** for that weight
   - **Among** options that are fit, walk the user’s **model-priority** order and
     pick the first that can do the job (local or remote)
   - If the user’s priority already puts a capable local early, keep that order
   - If priority has no local token yet, **propose** inserting the local endpoint
     name at a position consistent with their preferences (e.g. after cheaper
     remotes they listed first, or at the front if they asked for local-first) —
     do not silently reorder their whole list

4. **Lightweight stays lightweight.** Small locals stay on `swarm`/`executor`
   tiers in `endpoints.yaml`. Do not map them to `frontier` / orchestrator roles.
   Escalation to Preferred orchestrator / cloud frontier remains for work beyond
   local tier.

5. State this policy in the report and in any reconfigure draft
   (`## Routing policy` or under conventions step).

### 6. Offer draft plan: reconfigure project for detected local models (required)

After the report (and **before** ending the turn), **ask the user** whether to
create a **draft plan** they can execute later (once install deps are done):

> Create a draft under `.plans/drafts/` that reconfigures **this project** to use
> the detected local model(s) as an Anchor fleet endpoint? (Install stays in
> **Prerequisites** — the plan assumes you may run `/work` after install.)

- **Skip** this offer for `--list` / pure catalog mode.
- **Do not** create the draft until the user says yes (or equivalent) to *creating*
  a reconfigure draft — that is the only confirmation required.
- **Do not** install runners or download weights as part of creating the draft.
- **Do not** ask where to store the draft or what the slug should be:
  - **Path (fixed):** current project **`./.plans/drafts/`** (git root of CWD if
    that is the project; otherwise CWD’s `.plans/drafts/`). Create the tree if needed.
  - **Slug (auto):** `local-executor-<best-model>` from the probe (e.g.
    `local-executor-qwen3-8b`). If that file already exists, append `-2`, `-3`, …
    Do not prompt to confirm the slug.
  - Default privacy: **`<slug>.local.md`**.

#### If the user accepts — write the draft

1. Ensure **`./.plans/drafts/`** exists on the **current project** (create dirs if
   missing). Do not ask for another project path.
2. Choose slug automatically: `local-executor-<best-model>` (+ numeric suffix if
   taken). No customer-specific names; no slug confirmation prompt.
3. Use `.anchor/templates/plan.md` shape (or `anchor/templates/plan.md` in the
   Anchor source tree). **No** `Lane:` / `Status:`.
4. **Required section — `## Prerequisites` (install-first, special attention):**
   - Host/guest facts from this probe (profile, host RAM, GPU class, placement)
   - Ordered install checklist for the **chosen** runner (host Ollama/llama.cpp
     when WSL bare-metal recommended; else platform-specific)
   - Links (HTTPS) for each install step
   - How to verify the server is up (`curl` health / `ollama list` / open port)
   - Explicit: **Do not start Steps until Prerequisites are checked off**
5. **Goal / Steps** of the plan itself should be **project reconfiguration**, e.g.:
   - Add/update `endpoints.yaml` (project fleet path or
     `.anchor/scripts/endpoints.yaml` if fleet-scaffolded)
   - Set quirks + **tier** from `fit_device` (never over-tier a small local)
   - Update `.anchor/conventions.md` **model priority** using step **5b**:
     user order primary; insert fit local token(s); heavy-local only if probe allows
   - Document routing: lightweight work → small locals only; heavy work → first
     **fit** model in user priority (prefer capable local when it appears / when
     host can run heavy and user accepts local in that band)
   - Smoke: `work_once --list` or a tiny chat against the local endpoint
   - **Not** “install Ollama” as a Step row — that belongs in Prerequisites
6. Preferred models for the **plan execution** (wiring the project): `small` /
   `mid` (mechanical). Separately, the **fleet** Preferred models / priority
   updated by the plan must encode 5b for day-to-day routing.
7. Report the draft path only (no “is this slug OK?”); mention `/draft --load` /
   `/draft --promote` when ready (basename sticky if `.local.md`).

#### Draft skeleton (fill from this probe)

```markdown
# Plan: Wire local fleet endpoint (<best-model>)

- **Value:** medium
- **Priority:** P2
- **Slug:** local-executor-<best-model>
- **Preferred models:** small, mid
- **Depends on:** none

## Goal
Configure this Anchor project to use probe-selected local model(s) as fleet
endpoint(s), with routing limited by fit tier and ordered primarily by the
operator’s model-priority list (heavy work prefers capable local when the host
and priority allow).

## Prerequisites
<!-- INSTALL — do not execute Steps until these hold -->
- [ ] Probe profile: …
- [ ] Executor placement: windows-host | macos | linux-cuda | …
- [ ] Host can/cannot run heavy local (VRAM/RAM class from probe)
- [ ] Install runner on bare metal / host (commands + links from /local-models)
- [ ] Model weights pulled / GGUF available for: <best> (+ optional smaller)
- [ ] Server listening (URL + verify command)
- [ ] From this environment, `curl`/client can reach that URL

## Routing policy (from /local-models)
- User model-priority (from config/conventions): `…`  <!-- or “unset — propose” -->
- Lightweight locals (tier swarm/mid only): …
- Heavy-capable local on this host? yes/no — if yes, prefer fit local for heavy
  inference in priority order; if no, never assign heavy roles to these locals

## Context read
- Output of `fit_device.py --probe` from session date …
- Existing MODEL_PRIORITY / `.anchor/conventions.md` …
- Project endpoints path …

## Steps
| # | Task | Touches | Verify by | Route to |
|---|------|---------|-----------|----------|
| 1 | Add endpoint stanza(s); tier matches catalog fit only | endpoints.yaml | YAML + tier correct | small |
| 2 | Align quirks with catalog | endpoints.yaml | stanza matches probe | small |
| 3 | Merge model-priority / routing notes (user order primary; no over-tier) | .anchor/conventions.md | priority list reviewed | mid |
| 4 | Smoke local OpenAI-compatible call (lightweight prompt only) | — | short completion OK | small |

## Done when
- [ ] Local endpoint(s) registered with correct tier (no small-as-frontier)
- [ ] Conventions/priority reflect user order + fit-based heavy/light rules
- [ ] Prerequisites install checklist was satisfied before smoke
- [ ] Documented how to re-run the server after reboot
```

## Output footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: profile, best model, top install path (with links), whether a runner is
already on PATH, and whether a **draft was offered / created** (path if created).

**Closing prompt (mandatory unless `--list`):** ask only whether to **create** the
reconfigure draft (yes/no). Do **not** ask for project path or slug — those are
fixed/auto (step 6).

## Out of scope

- Fine-tuning / training
- Cloud GPU provisioning (unless user asks)
- Replacing `/install-anchor` (CLI registration only)
- Guaranteeing VRAM fit without `benchmark.py` confirmation
- Creating the reconfigure draft without user consent
- Treating Prerequisites install as silent `/work` steps
