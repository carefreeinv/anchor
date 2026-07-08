---
sidebar_position: 3
---

# MCP servers

Two stdio servers in `mcp/`, installable into Claude Code, Grok Build (if MCP-capable), or any MCP client. Together they close the loop: **anchor-prompts** makes a lesser model *behave*, **model-fleet** makes a frontier model *delegate*.

## anchor-prompts

The discipline as callable tools, so weak models fetch structure instead of having to remember it:

- `get_doctrine` / `get_system_prompt(model)` / `get_template(name)` — the doctrine, mythos-core (or per-model variant), and the four templates
- `tune_prompt(rough_task)` — cheap-model spec rewriting via the fleet
- `preflight_check(task_spec)` — **deterministic** gate: missing sections or unresolved TODOs → "do not execute." This is the check small models always skip, done in code where it can't be skipped.
- Prompt scaffolds: `plan_task(goal)`, `critique_work(spec, work)`

## model-fleet

The delegation arm of the orchestrator pattern:

- `delegate(task_spec, role, thinking)` — ship a self-contained spec to the right tier; output format-gated on return
- `delegate_parallel_review(task_spec, work)` — two independent critics must agree; disagreement → HOLD (the Space-1 verify-twice rule, available everywhere)
- `list_fleet` / `fleet_health` — registry view and reachability sweep

```bash
claude mcp add anchor-prompts -- python /abs/path/mcp/anchor-prompts/server.py
claude mcp add model-fleet   -- python /abs/path/mcp/model-fleet/server.py
```
