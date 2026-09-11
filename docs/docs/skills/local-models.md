---
sidebar_position: 6
sidebar_label: /local-models · machine fit
---

# `/local-models`

**Best used:** on **any host** (Anchor checkout or a scaffolded project) when
choosing or wiring a **lean local** model executor for **this** machine.
Re-run per clone — multi-machine safe. See [Skills overview](/skills/overview).

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
3. **Reachable API** — guest-proven `base_url` (loopback → default gateway → `resolv.conf` nameserver); never register dead WSL `localhost` when the host API only answers on the gateway IP  
4. **Best lean fit** (sized to host budget when known) + smaller options  
5. **Links** — model quick starts + weight repos  
6. **Install path** — host [Ollama for Windows](https://ollama.com/download) / llama.cpp first; in-WSL only as fallback; re-probe after reboot (gateway IPs churn); optional [mirrored networking](https://learn.microsoft.com/en-us/windows/wsl/networking)  
7. **Optional draft** — after the report, the agent asks only whether to create a plan (yes/no); it always writes under **`./.plans/drafts/`** with an auto slug (`local-executor-<model>`); install work is under **`## Prerequisites`**, not main Steps  
8. **Routing** — reconfiguration respects the operator’s **model-priority** list first; lightweight locals only do lightweight work; if the host can run heavy local models, those locals are preferred for heavy inference **when** they appear appropriately in (or are inserted consistently with) that priority order

## CLI (no agent)

```bash
python scripts/fit_device.py --probe
python scripts/fit_device.py --memory 48 --backend metal
python scripts/fit_device.py --list
```

## Install paths

**Dual-use:** Anchor checkout **and** scaffolded into projects with
`--platform claude` and/or `grok` (same base paths as `/work`):

| Platform | Path |
|----------|------|
| Grok Build | `.grok/skills/local-models/SKILL.md` |
| Claude Code | `.claude/commands/local-models.md` |

## Queen-bee plans, drone executes

A local model this skill just wired up is a **drone**, not a planner:

- **Queen-bee** (a cloud/frontier session, or a human) writes plans into
  `.plans/drafts/` and promotes them to `.plans/bugs/` or `.plans/features/`.
- **Drone** (the local model, via `/work` in an agentic harness like Aider, or
  headless via `work_once.py`/`fleet_watch.py`) only claims and executes an
  already-ready plan — it never drafts, promotes, reviews, or merges.

If the local model's backlog is empty, that's the correct idle state — a
drone does not invent work. See [`/work`](/skills/work) and
[Fleet workers](/tooling/fleet-workers) for the full contract; the
[Aider platform](/platforms/aider) page shows the same split for an
interactive local-model harness.

## Drone recipe: this machine, unattended

Once `/local-models` has confirmed a reachable local endpoint (Ollama,
llama.cpp, …), point `work_once.py` — the same headless picker
[Fleet workers](/tooling/fleet-workers) documents generically — at a
**machine-local** registry rather than the shared `scripts/endpoints.yaml`.
This follows `/local-models`' own multi-machine hard rule: a laptop's
`base_url` (an Ollama gateway IP, a `localhost` port) is host-specific and
must never be committed as project-wide fleet truth — prefer a gitignored
overlay; a shared registry entry is only for LAN/API hosts every clone can
actually reach.

```bash
# var/endpoints.local.yaml (gitignored) — one entry, this host's reachable URL
cat > var/endpoints.local.yaml <<'YAML'
endpoints:
  - name: laptop-swarm
    tier: swarm
    base_url: http://<reachable-ollama-url>/v1   # from /local-models' probe
    model: qwen3:4b
    quirks: {think_toggle: qwen3, strip_think: true, min_completion_tokens: 256}
YAML

# Inspect, then claim one fit-appropriate ready plan (never merges):
python scripts/work_once.py --list --endpoint laptop-swarm --registry var/endpoints.local.yaml
python scripts/work_once.py --once --endpoint laptop-swarm --registry var/endpoints.local.yaml --agent-id laptop-swarm-1
```

For a reboot-persistent poller instead of a one-shot claim, hand the same
registry/endpoint name to [`/fleet-watch`](/skills/fleet-watch) — the
`--worker` spec takes a `registry=` key so the generated systemd unit points
at your machine-local file, not the shared `scripts/endpoints.yaml` default:

```bash
python scripts/fleet_watch.py --project . --emit systemd \
  --worker tier=small,agent=laptop-swarm-1,interval=10m,endpoint=laptop-swarm,registry=var/endpoints.local.yaml
```

See [Fleet workers](/tooling/fleet-workers) for the full systemd/cron
recipes; this page only adds the machine-local-registry step specific to a
drone running on the box `/local-models` just probed.

## Related

- [Personal devices](/hardware/personal-devices)
- [Local models (platform notes)](/platforms/local-models)
- [Utility scripts — fit_device](/tooling/scripts#fit_devicepy)
