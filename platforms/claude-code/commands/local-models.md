---
description: Probe this machine for lean local models; recommend fits with clickable install links; offer a draft to wire the project later
argument-hint: "[--probe|--list|--status] [--memory GB] [--backend metal|mlx|cuda]"
allowed-tools: Bash(*), Read, Write, Edit
---

# /local-models — machine fit + local executor install guidance

**Scaffolded skill** (scaffolded with Claude platform; not an Anchor base
skill). Full procedure: **`.grok/skills/local-models/SKILL.md`** when present,
else the Grok source under the Anchor repo
`platforms/grok-build/skills/local-models/SKILL.md`. Summary:

1. Find `scripts/fit_device.py` (Anchor repo or project `.anchor/scripts/`).
2. Run `python3 …/fit_device.py --probe` (plus any `$ARGUMENTS` overrides).
3. Present a **markdown report** with:
   - machine profile (WSL guest + bare-metal host when probe used `powershell.exe`)
   - **executor placement** (prefer Windows host when under WSL)
   - recommended lean models from the fit list (host budget when known)
   - **clickable HTTPS links** (official docs, HF weights, Ollama/llama.cpp)
   - short install procedure **for this OS** (host first on WSL)
4. Do **not** download multi‑GB models or `pip install vllm` without confirmation.
5. **Before ending:** ask **only** whether to create a draft that reconfigures
   the **current** project for the detected local model(s) (yes/no). Store under
   **`./.plans/drafts/`** always; slug auto `local-executor-<best-model>` (suffix
   if taken) — **do not** ask for path or slug. Install process in
   **`## Prerequisites`**. Write only if the user agrees. Default `.local.md`.
6. **Routing in that draft:** user **model-priority** order is primary; local
   endpoints only for work their catalog **tier** can handle (lightweight locals
   stay lightweight). If the host can run **heavy** local inference, prefer a
   fit local for heavy work **among** options allowed by that priority list —
   never promote a tiny local to frontier/orchestrator roles.

End with `## Result`, `## How to verify`, `## Deferred / concerns` (include
draft offered/created).
