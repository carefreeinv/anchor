---
sidebar_position: 2
---

# Utility scripts

`scripts/` — Python, OpenAI-compatible everywhere. `pip install -r scripts/requirements.txt`, then point `endpoints.yaml` at your nodes. Model quirks (Gemma system-folding, Qwen3/Nemotron toggles, `<think>` stripping) live in `anchor_client.py`, keyed by each endpoint's `quirks:` block — callers never special-case models.

## endpoints.yaml

The fleet registry: endpoints with `tier` (swarm / executor / executor-heavy / reasoner / frontier / detached) and a `roles:` map giving tier preference order per role (tuner, executor, critic, planner).

## prompt_tuner.py

Playbook move #3 as a command: `python prompt_tuner.py "fix the login bug"` → a filled task-spec from a cheap model, with honest `TODO(owner):` markers where the rough description was silent. Never invents details — an honest TODO is a success, a plausible invention is a failure.

## router.py

The "which tier deserves this task" rule as code: regex heuristics first (free), optional tiny-model classification fallback. `--send` dispatches immediately with the mythos-core system prompt.

## orchestrate.py

The whole loop: plan (planner role or `--plan-file`) → split into tasks → execute each in a fresh context → verify with your `--verify` command → two-strike escalate or `--hold-on-fail` (detached mode) → fresh-context critic review → JSON run report. Format-gates every executor output (missing footer = failed attempt).

## benchmark.py

Playbook move #5: your tasks (JSONL with pass regexes) across your endpoints → CSV + per-endpoint pass-rate/latency table. That table *is* your routing policy, derived from your own data instead of leaderboards.

## fit_device.py

The on-ramp for the [personal-devices tier](../hardware/personal-devices): `python fit_device.py --memory <GB> [--backend metal|mlx|cuda]` picks the most capable model that fits a Mac Mini, AI laptop, or single-GPU desktop, then prints a launch command and an `endpoints.yaml` stanza with the right quirks. Memory is a conservative weights+KV+overhead estimate — confirm with `benchmark.py`.
