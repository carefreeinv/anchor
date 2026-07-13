---
sidebar_position: 2
---

# Utility scripts

`scripts/` — Python, OpenAI-compatible everywhere. `pip install -r scripts/requirements.txt`, then point `endpoints.yaml` at your nodes. Model quirks ([Gemma](https://ai.google.dev/gemma/docs/core) system-folding, [Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html)/Nemotron toggles, `<think>` stripping) live in `anchor_client.py`, keyed by each endpoint's `quirks:` block — callers never special-case models.

```mermaid
flowchart LR
  ep["endpoints.yaml"]
  fit["fit_device / router"]
  wo["work_once"]
  fw["fleet_watch"]
  orch["orchestrate"]
  bench["benchmark"]

  ep --> fit
  ep --> wo
  ep --> orch
  fit --> ep
  fw --> wo
  wo --> orch
  bench --> ep
```

## endpoints.yaml

The fleet registry: endpoints with `tier` (swarm / executor / executor-heavy / reasoner / frontier / detached) and a `roles:` map giving tier preference order per role (tuner, executor, critic, planner).

## prompt_tuner.py

Playbook move #3 as a command: `python prompt_tuner.py "fix the login bug"` → a filled task-spec from a cheap model, with honest `TODO(owner):` markers where the rough description was silent. Never invents details — an honest TODO is a success, a plausible invention is a failure.

## router.py

The "which tier deserves this task" rule as code: regex heuristics first (free), optional tiny-model classification fallback. `--send` dispatches immediately with the mythos-core system prompt.

## work_once.py

Headless puller for multi-tier fleets: same priority + Preferred-models fit + **Depends on** checks as interactive `/work` — **ready lanes only** (never bare-picks in-progress), one claim per invocation (optional `--max-plans N`). Each worker passes `--tier` or `--endpoint` and a unique `--agent-id`; a claim **moves** the plan to `.plans/in-progress/` and writes its lease under `.plans/.leases/` atomically. Other agents ignore foreign in-progress work; there is no silent reclaim. Keep a long job alive with `--heartbeat`, take over a crashed worker's expired lease with `--recover`. Unmet dependencies are skipped (`--no-dep-check` to override). Park half-baked/stuck work: `--park ambiguous|blocked`. Return to ready: `--return-ready`. Parallel code edits: **`worktree_for_agent.py`** or `work_once.py --ensure-worktree` (one worktree per agent-id under `var/worktrees/`). Exit `1` means idle backlog (normal for cron). Full setup: [Fleet workers](/tooling/fleet-workers).

```bash
python work_once.py --list --tier mid --agent-id mid-1
python work_once.py --once --endpoint h100-executor --agent-id mid-1 --run
python work_once.py --path .plans/in-progress/x.md --park blocked --agent-id mid-1
```

Shared selection: `plan_select.py` (fit + deps). Claims + moves: `plan_lease.claim_and_move` / `park` / `return_to_ready`.

## fleet_watch.py

Implementation behind the [**`/fleet-watch`**](/skills/fleet-watch) skill (prefer the skill in an agent). Direct CLI for automation/CI: `--project`, `--status`, `--list` / `--once`, `--emit systemd|cron`, `--install-user` (systemd **user** timers; reboot-safe with `loginctl enable-linger $USER`). See [Fleet workers](/tooling/fleet-workers) for the pull model.

```bash
python fleet_watch.py --project /path/to/app --status
python fleet_watch.py --project /path/to/app --emit systemd \
  --worker tier=mid,agent=mid-1,interval=5m
```

## pending_merges.py

Advises which finished work is committed but **not yet merged** into integration. For each local branch it counts commits the merge target doesn't have — `feature/*` → `dev`/`develop` (else `main`/`master`), and `dev`/`develop` → mainline — and flags any `feature/<slug>` that matches a plan under `.plans/completed/` as **completed work awaiting merge**. Advisory by default; pass `--exit-code` to return `1` when anything is pending (for a coordinator, monitor, or CI to surface), `--json` for machines.

```bash
python pending_merges.py                 # human table
python pending_merges.py --json --exit-code
```

## orchestrate.py

The whole loop: plan (planner role or `--plan-file`) → split into tasks → execute each in a fresh context → verify with your `--verify` command → two-strike escalate or `--hold-on-fail` (detached mode) → fresh-context critic review → JSON run report. Format-gates every executor output (missing footer = failed attempt). Pass `--scope-spec <task-spec.md>` (with `--worktree <root>`) to run the **scope gate** before `--verify`: a change outside the spec's `## Files in scope` marks the task `failed-scope` and tests never run. Roles are also harness-enforced per phase via the `roles.py` capability map: writes made during the planner phase outside `.plans/**`, executor writes into `.plans/**` (or its own spec), or any critic write are **role violations** — logged as events, marked `failed-role` on the task, and the run exits `4` after still emitting its outputs. Role transitions (plan approved → executors spawned → review) are explicit logged events. Often invoked by `work_once.py --run` after a claim.

## roles.py

The role→capability map behind ANCHOR.md's role-separation bullet — planner / executor / critic as **harness-enforced capability sets**, not prompt framing, in one module so nothing re-declares role powers elsewhere. Each `RoleCapabilities` carries writable-path allow/deny globs (reusing `scope_gate.path_matches` — one glob implementation), a `can_dispatch` flag (orchestrator only), and the MCP toolset the role may see. `check_role_writes(caps, paths)` classifies a phase's writes; unlike the scope gate it is always active (an empty allowlist means read-only). Consumed by `orchestrate.py` (per-phase enforcement) and the project-orchestrator MCP server (`--role` toolsets). Reads stay unrestricted for every role — only writes and dispatch are gated.

## scope_gate.py

Machine-enforces mythos-core rule 7 ("scope is sacred"). `check_scope(diff_paths, in_scope, allowed_generated)` is a pure classifier; `worktree_changes(root)` reads the git diff (tracked vs HEAD + untracked); `enforce_scope(...)` combines them. Any changed path outside the task spec's `## Files in scope` (or an `Allowed generated files:` allowlist) is a violation. Globs are gitignore-style: `*` within a segment, `**` across segments, trailing `/` for a subtree, plain paths match exactly or as a directory prefix. Use as a **verify pre-step** so tests never run on an out-of-scope diff — `python scope_gate.py --root . --spec spec.md && pytest -q` (exit `3` = violation) — or via `orchestrate.py --scope-spec`.

## benchmark.py

Playbook move #5: your tasks (JSONL with pass regexes) across your endpoints → CSV + per-endpoint pass-rate/latency table. That table *is* your routing policy, derived from your own data instead of leaderboards.

## fit_device.py

The on-ramp for the [personal-devices tier](/hardware/personal-devices):

```bash
python fit_device.py --probe                 # detect OS/RAM/GPU/WSL + install tips + fit
python fit_device.py --memory 48 --backend metal
python fit_device.py --list
```

`--probe` prints machine facts, **markdown-friendly install links** (WSL, CUDA, llama.cpp, Ollama, vLLM, MLX), then the best lean catalog fit with HF weight links and an `endpoints.yaml` stanza. On **WSL**, it also queries the **Windows host** via `powershell.exe` (RAM/CPU/GPUs) so recommendations use bare-metal capacity and prefer a **host** model executor. Manual `--memory` / `--backend` still work. Memory is a conservative weights+KV+overhead estimate — confirm with `benchmark.py`. Agent UX: [**`/local-models`**](/skills/local-models).
