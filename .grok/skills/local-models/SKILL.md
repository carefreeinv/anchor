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

**Dual-use skill:** lives in the **Anchor checkout** base skills and is
scaffolded into projects via `anchor … --platform claude|grok` (same pattern as
`/work`, `/draft`, `/install-anchor`). Source of truth:
`.grok/skills/local-models/SKILL.md` (Claude: `.claude/commands/local-models.md`).

Answer: **what lean, popular local models can this machine run**, and **how do
I install/run a model executor here** — with **markdown links** the user can
click (official docs, HF weights, WSL/CUDA/macOS install paths). From the
Anchor tree, also guide **operator defaults** and fleet registration for
**this host**.

Prefer tooling over guesswork: run Anchor’s probe/fit helper, then present a
clear recommendation report in chat.

## Hard rule — multi-machine clones

A project is often **cloned onto several machines** (laptop, desktop, WSL guest,
CUDA box) with **different** RAM/GPU/backends. Therefore:

1. **Probe is always this host.** Never treat a prior probe, a teammate’s setup,
   or a committed “we use Qwen3-32B locally” note as true on this machine.
2. **Host fit is not project law.** Do **not** commit this host’s model size,
   quant, or `localhost` URL as if every clone has that capacity.
3. **Prefer machine-local writes** for host-only endpoints:
   - Operator defaults: `~/.config/anchor/defaults` (`config.sh` / `/config`) —
     already per machine.
   - Localhost / host-only registry stanzas: prefer a **gitignored** overlay
     (e.g. `endpoints.local.yaml` next to the registry, or document “local only
     on this host”) rather than forcing a shared `endpoints.yaml` edit that
     breaks other clones.
   - Draft plans that wire **this** host: default **`.local.md`** (gitignored).
4. **Shared project config stays portable.** Conventions / tracked docs may say
   “use a local executor **when reachable**” and name tier ceilings — not
   “everyone runs 70B on `http://127.0.0.1:11434`”.
5. **Fleet/LAN endpoints are different.** Shared `endpoints.yaml` entries that
   point at a **stable LAN/API host** (e.g. lab H100 at `10.x`) may be committed;
   pure **this-laptop** endpoints must not pretend to be fleet-wide.
6. **Stale other-host config:** if the project already lists local endpoints that
   look host-bound (`127.0.0.1`, `localhost`, hostnames that don’t resolve here)
   or a prior host note that doesn’t match this probe, **warn** and re-derive
   for this machine — never silently trust or clobber without confirmation.
7. **Declared ≠ available.** A recommendation or draft is not a promise the
   endpoint answers on every clone or after reboot.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/local-models` | Full probe + fit + install guidance for this host |
| `/local-models --probe` | Same (explicit) |
| `/local-models --list` | Catalog only (no probe) |
| `/local-models --status` | Probe tools/hardware only; skip long install blurb if already clear |
| `/local-models --memory 16 --backend cuda` | Override probe memory/backend |

`$ARGUMENTS` is everything after `/local-models`.

## Where you are (Anchor vs project)

Detect early (used for closing offers and write targets):

| Context | How to detect | Primary follow-ups |
|---------|---------------|--------------------|
| **Anchor checkout** | Tree has both `bin/anchor` and `scripts/anchor.py` **and** `scripts/fit_device.py` at repo root (source tree, not only a fleet-scaffolded `.anchor/scripts/`) | Operator defaults (`/config` / `config.sh`); optional machine-local or LAN fleet stanza in **this** repo’s `scripts/endpoints.yaml` (LAN only if shared); install on this host |
| **Scaffolded project** | CWD/git root is not the Anchor source tree (may have `.anchor/`, `.anchor-manifest.json`) | Install on this host; **portable** project notes + **machine-local** endpoint wiring; `.local.md` draft |

Same probe either way. Different write surfaces; same multi-machine rules.

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
   `powershell.exe` (host RAM, CPU, GPUs) vs WSL cgroup RAM. State clearly:
   **this host only** (other clones need their own `/local-models`).
2. **Compatibility** — honest: good / limited (CPU/iGPU) / excellent (CUDA/Metal)
3. **Executor placement** — if WSL: **prefer Windows bare-metal** model server;
   Anchor stays in WSL and points the **machine-local** registry at the host API
4. **Recommended models** (lean + popular from the fit list, sized to **host**
   usable budget when known) — for each:
   - name, size, Anchor tier
   - why it fits **here**
   - links: official quick start + GGUF/HF weights (from probe output)
5. **Install on this system** — short procedure for the **detected** profile:
   - **WSL2:** lead with [Ollama for Windows](https://ollama.com/download) or
     Windows llama.cpp on the **host** (probe already used `powershell.exe` —
     user need not run a PS1 just to get recommendations); then how WSL reaches
     `localhost` / host IP; WSL-in-guest install only as fallback
   - **Apple Silicon:** brew llama.cpp / MLX → serve script
   - **Linux CUDA:** driver + vLLM or llama.cpp CUDA → serve-cuda.sh
   - **Linux CPU:** small GGUF only
6. **Config scope** — what is safe **on this machine** vs what must stay
   **portable** for multi-clone projects (see hard rule)
7. **Next Anchor steps** — register endpoint (machine-local vs LAN); optional
   `/install-anchor` if CLI missing; optional `/config` when in Anchor checkout;
   point at personal-devices hardware docs
8. **Offer follow-up** (required close) — see step 6 below

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
- Name the **target machine** when install is not on the agent’s guest
  (e.g. WSL → Windows host via documented host installers).

### 5. Catalog philosophy (what “lean popular” means)

Prefer models in `fit_device.py`’s catalog (Qwen3, Gemma 3, Mistral Small, R1
distills, Llama 3.3) at **Q4**, short context (8k default), official chat
templates — not giant FP16 frontier weights on a laptop.

### 5b. Routing policy (recommendations + any wiring)

Wire local models **without** promoting small locals into heavy work — and
**without** ignoring the operator’s model-priority list — and **without**
assuming every clone can run the same local.

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
   - Prefer a **local** endpoint that is **fit** for that weight **on this host**
   - **Among** options that are fit, walk the user’s **model-priority** order and
     pick the first that can do the job (local or remote)
   - If the user’s priority already puts a capable local early, keep that order
   - If priority has no local token yet, **propose** inserting the local endpoint
     name at a position consistent with their preferences — do not silently
     reorder their whole list

4. **Lightweight stays lightweight.** Small locals stay on `swarm`/`executor`
   tiers. Do not map them to `frontier` / orchestrator roles.

5. **Reachability over assumption.** Prefer remote/fleet endpoints that answer
   when this host has no fit local; never hard-fail a multi-clone project because
   one laptop cannot run the largest catalog entry.

6. State this policy in the report and in any draft (`## Routing policy` /
   multi-machine note).

### 6. Offer follow-up (required close)

After the report (and **before** ending the turn), offer the right follow-up for
**where you are**. Skip for `--list` / pure catalog mode.

#### A. In the Anchor checkout — operator defaults + this host’s fleet

Ask (yes/no; may combine):

1. **Operator defaults** — update `~/.config/anchor/defaults` via `./config.sh`
   (or `/config`) so model-priority includes a fit **local** token for **this
   machine** (still subject to tier ceilings). This is the right place for
   “default install / default local preference” that follows the operator across
   scaffolds **on this host**.
2. **Optional draft** under `./.plans/drafts/` (`.local.md`) to register a
   **verified** endpoint for **this host** in `scripts/endpoints.yaml` only when
   it is a **LAN/shared** URL, or to document a **machine-local** overlay path
   for localhost. Install stays in **Prerequisites**.

Do **not** write shared doctrine that claims every developer machine has this
host’s VRAM.

#### B. In a scaffolded project — portable intent + machine-local wire-up

Ask whether to create a **draft** under **`./.plans/drafts/`** that:

- Installs/serves the model on **this** host (Prerequisites)
- Registers a **machine-local** endpoint (gitignored overlay preferred for
  `localhost`; shared registry only for multi-host-reachable URLs)
- Updates conventions with **portable** language (“local when reachable”; tier
  ceilings) rather than hard-coding this host’s best model as universal

Slug auto: `local-executor-<best-model>` (+ `-2`, …). Default **`.local.md`**.
Do not ask for path or slug. Create the draft only if the user agrees.

#### Shared draft rules (both contexts)

- **Do not** install runners or download weights as part of creating the draft.
- **Do not** treat Prerequisites install as silent `/work` steps.
- Use plan template shape (`.anchor/templates/plan.md` or Anchor
  `anchor/templates/plan.md`). **No** `Lane:` / `Status:`.
- Preferred models for executing the **wiring** plan: `small`, `mid`.

#### Draft skeleton (fill from this probe)

```markdown
# Plan: Wire local fleet endpoint (<best-model>) on this host

- **Value:** medium
- **Priority:** P2
- **Slug:** local-executor-<best-model>
- **Preferred models:** small, mid
- **Depends on:** none

## Goal
On **this machine only**, install/serve probe-selected local model(s) and register
them for Anchor use without claiming every clone of this repo has the same
capacity. Portable project notes may say “local when reachable”; host-only URLs
stay machine-local.

## Prerequisites
<!-- INSTALL — do not execute Steps until these hold -->
- [ ] Probe profile (this host): …
- [ ] Executor placement: windows-host | macos | linux-cuda | …
- [ ] Host can/cannot run heavy local (VRAM/RAM class from probe)
- [ ] Install runner on bare metal / host (commands + links from /local-models)
- [ ] Model weights pulled / GGUF available for: <best> (+ optional smaller)
- [ ] Server listening (URL + verify command)
- [ ] From this environment, `curl`/client can reach that URL

## Multi-machine
- This draft is for host profile: … (re-run `/local-models` on other clones)
- Shared registry vs machine-local overlay: …
- Do not commit localhost-only stanzas as fleet-wide truth

## Routing policy (from /local-models)
- User model-priority (from config/conventions): `…`  <!-- or “unset — propose” -->
- Lightweight locals (tier swarm/mid only): …
- Heavy-capable local on this host? yes/no

## Context read
- Output of `fit_device.py --probe` from session date …
- Existing MODEL_PRIORITY / conventions / endpoints (note other-host staleness) …

## Steps
| # | Task | Touches | Verify by | Route to |
|---|------|---------|-----------|----------|
| 1 | Register endpoint: machine-local overlay for localhost, or shared registry only if LAN-reachable | endpoints path | YAML + tier correct; other clones not broken | small |
| 2 | Align quirks with catalog | same | stanza matches probe | small |
| 3 | Portable conventions/priority notes (user order primary; no over-tier; “when reachable”) | conventions / ~/.config/anchor | priority reviewed | mid |
| 4 | Smoke local OpenAI-compatible call (lightweight prompt only) | — | short completion OK | small |

## Done when
- [ ] This host has a correct-tier local endpoint (or explicit “no local fit”)
- [ ] Shared project config does not require other clones to have this host’s VRAM
- [ ] Prerequisites install checklist was satisfied before smoke
- [ ] Documented how to re-run the server after reboot **and** re-probe on a new machine
```

## Output footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: profile, best model, top install path (with links), whether a runner is
already on PATH, context (Anchor vs project), multi-machine notes, and whether a
**follow-up was offered / created** (path if draft created; whether `/config` was
suggested).

**Closing prompt (mandatory unless `--list`):** ask the yes/no follow-up for the
detected context (Anchor: defaults and/or draft; project: draft). Do **not** ask
for project path or slug when offering a draft.

## Out of scope

- Fine-tuning / training
- Cloud GPU provisioning (unless user asks)
- Replacing `/install-anchor` (CLI registration only) or `/config` (operator
  survey — **offer** it from Anchor; do not replace it)
- Guaranteeing VRAM fit without `benchmark.py` confirmation
- Creating drafts or writing defaults without user consent
- Treating Prerequisites install as silent `/work` steps
- Committing one machine’s localhost fit as project-wide required capacity
- Implementing full desired-state declaration / ensure pipelines (future
  `/local-models-config` + `/local-models-ensure` if present in backlog)
