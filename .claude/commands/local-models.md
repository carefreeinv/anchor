---
description: Probe this machine for lean local models; recommend fits with clickable install links; multi-machine-safe defaults/drafts
argument-hint: "[--probe|--list|--status] [--memory GB] [--backend metal|mlx|cuda]"
allowed-tools: Bash(*), Read, Write, Edit
---

# /local-models — machine fit + local executor install guidance

**Dual-use** (Anchor base + scaffolded projects). Full procedure:
**`.grok/skills/local-models/SKILL.md`**. Summary:

1. Find `scripts/fit_device.py` (Anchor repo or project `.anchor/scripts/`).
2. Run `python3 …/fit_device.py --probe` (plus any `$ARGUMENTS` overrides).
3. Present a **markdown report** with:
   - machine profile (WSL guest + bare-metal host when probe used `powershell.exe`)
   - **this host only** — other clones of the same repo need their own probe
   - **executor placement** (prefer Windows host when under WSL)
   - **Default for wire** (memory-safer) + **Max fit** (ceiling) from
     `fit_device.py --probe` — on WSL/Aider projects, offer
     `write_aider_env.py --root <project>` to wire the reachable base into a
     gitignored `.env` (bare `aider` else Connection-refuses against guest
     `localhost`); name opt-up
   - **Reachable API** `base_url` from the probe (loopback → gateway →
     `resolv.conf`); never register dead WSL `localhost` when only the host
     gateway answers
   - recommended lean models from the fit list (host budget when known)
   - **clickable HTTPS links** (official docs, HF weights, Ollama/llama.cpp)
   - short install procedure **for this OS** (host first on WSL; re-probe after
     reboot — gateway IPs churn)
   - **config scope**: machine-local vs portable multi-clone project config
4. Do **not** download multi‑GB models or `pip install vllm` without confirmation.
5. **Multi-machine hard rule:** never commit this host’s localhost / gateway-IP
   fit as project law; prefer `~/.config/anchor` + gitignored overlays for
   host-only endpoints; shared registry only for LAN/API hosts other clones can
   reach; re-probe on every machine after clone.
6. **Confirmed-stack autowire (project context only):** after the report, run
   `python3 scripts/local_models_autowire.py --detect` (or `.anchor/scripts/…`
   in a project). If **CONFIRMED** (guest-reachable API **and** that API
   actually lists the Default-for-wire model — not just "responds"), ask
   **"Wire this project?" (Y/N)**. On yes:
   `local_models_autowire.py --project <project> --write` — writes a
   machine-local endpoints overlay, the gitignored `.env` (via
   `write_aider_env.py`), an idempotent conventions note (only if a
   conventions file already exists), and — only when `aider` is on
   `$PATH` — `.aider.conf.yml` (**Default-for-wire** model, never Max fit)
   plus a copied launcher script. On no, or gates not confirmed: fall through
   to the draft offer below — **never writes**. Never installs Ollama or pulls
   weights here — detected-existing only.
7. **Before ending:**
   - **In Anchor checkout:** ask whether to update operator defaults
     (`./config.sh` / `/config`) and/or create a `.local.md` draft for this
     host’s fleet wiring.
   - **In a project:** ask **only** whether to create a reconfigure draft under
     **`./.plans/drafts/`** (slug auto `local-executor-<best-model>`;
     **`.local.md`**). Install in **Prerequisites**. Portable conventions language
     only (“local when reachable”).
8. **Routing:** user **model-priority** order is primary; local endpoints only for
   work their catalog **tier** can handle; never promote a tiny local to
   frontier/orchestrator roles.

End with `## Result`, `## How to verify`, `## Deferred / concerns` (include
multi-machine note + draft/defaults offered/created).
