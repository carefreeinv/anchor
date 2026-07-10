---
sidebar_position: 6
sidebar_label: /local-models · machine fit
---

# `/local-models`

**Best used:** **inside a project** when choosing or wiring a **lean
local** model executor for this host (not a Anchor-only base skill). See
[Skills overview](/skills/overview).

Evaluate **this machine** for cutting-edge **lean** local models (Qwen3, Gemma 3, Mistral Small, R1 distills, …), recommend what fits, and show **clickable install links** plus a short procedure for the detected OS (including **WSL2**).

## Why

Spec sheets do not answer “what can *this* box run?” This skill probes hardware, runs `scripts/fit_device.py --probe`, and turns the result into an operator-facing report with HTTPS links (official docs, Hugging Face weights, WSL/CUDA/Ollama/llama.cpp).

## Usage

| Invocation | Behavior |
|------------|----------|
| `/local-models` | Probe + fit + install guidance |
| `/local-models --list` | Catalog only |
| `/local-models --memory 16 --backend cuda` | Override probe |

## What you get

1. **Machine profile** — guest OS + WSL?; on WSL, **host** RAM/CPU/GPU via `powershell.exe`  
2. **Executor placement** — prefer **Windows bare-metal** model server when under WSL  
3. **Best lean fit** (sized to host budget when known) + smaller options  
4. **Links** — model quick starts + weight repos  
5. **Install path** — host [Ollama for Windows](https://ollama.com/download) / llama.cpp first; in-WSL only as fallback  
6. **Optional draft** — after the report, the agent asks only whether to create a plan (yes/no); it always writes under **`./.plans/drafts/`** with an auto slug (`local-executor-<model>`); install work is under **`## Prerequisites`**, not main Steps  
7. **Routing** — reconfiguration respects the operator’s **model-priority** list first; lightweight locals only do lightweight work; if the host can run heavy local models, those locals are preferred for heavy inference **when** they appear appropriately in (or are inserted consistently with) that priority order

## CLI (no agent)

```bash
python scripts/fit_device.py --probe
python scripts/fit_device.py --memory 48 --backend metal
python scripts/fit_device.py --list
```

## Install paths

Scaffolded into **projects** with `--platform claude` and/or `grok` (not
part of the Anchor base skill set; source under `platforms/`):

| Platform | Scaffolded to | Source in Anchor repo |
|----------|---------------|------------------------|
| Grok Build | `.grok/skills/local-models/SKILL.md` | `platforms/grok-build/skills/local-models/SKILL.md` |
| Claude Code | `.claude/commands/local-models.md` | `platforms/claude-code/commands/local-models.md` |

## Related

- [Personal devices](/hardware/personal-devices)
- [Local models (platform notes)](/platforms/local-models)
- [Utility scripts — fit_device](/tooling/scripts#fit_devicepy)
