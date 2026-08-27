# model-fleet MCP server

The delegation arm of the orchestrator pattern: the frontier agent plans, then calls `delegate` so keystrokes run on the swarm / H100 tier instead of on credits.

Tools:

- `list_fleet` — one capped summary line per endpoint (name, tier, context size, capability phrase) + role routing, generated from `scripts/endpoints.yaml`; no `base_url`, model name, or quirk detail
- `lookup_endpoint(name)` — full non-secret detail for one endpoint, on demand (never a default include; `ANCHOR_API_KEY` stays an environment read, never a registry field)
- `delegate(task_spec, role, thinking)` — send a self-contained spec to a worker; output is format-gated
- `delegate_parallel_review(task_spec, work)` — two independent critics must agree (Space-1 verify-twice rule); disagreement → HOLD
- `fleet_health` — reachability sweep

## Install

```bash
cd mcp/model-fleet && pip install "mcp[cli]>=1.2.0,<3" requests pyyaml
claude mcp add model-fleet -- python /abs/path/mcp/model-fleet/server.py
```

Point `scripts/endpoints.yaml` at your real nodes first; `fleet_health` confirms wiring.
