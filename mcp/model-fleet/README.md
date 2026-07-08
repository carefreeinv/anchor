# model-fleet MCP server

The delegation arm of the orchestrator pattern: the frontier agent plans, then calls `delegate` so keystrokes run on the swarm / H100 tier instead of on credits.

Tools:

- `list_fleet` — endpoints + role routing from `scripts/endpoints.yaml`
- `delegate(task_spec, role, thinking)` — send a self-contained spec to a worker; output is format-gated
- `delegate_parallel_review(task_spec, work)` — two independent critics must agree (Space-1 verify-twice rule); disagreement → HOLD
- `fleet_health` — reachability sweep

## Install

```bash
cd mcp/model-fleet && pip install "mcp[cli]" requests pyyaml
claude mcp add model-fleet -- python /abs/path/mcp/model-fleet/server.py
```

Point `scripts/endpoints.yaml` at your real nodes first; `fleet_health` confirms wiring.
