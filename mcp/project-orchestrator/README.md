# project-orchestrator MCP

Per-project **limited** orchestrator for Anchor `.plans/`. Coding agents get list/claim/complete and dependency/stale tools **without** full shell, promote, or unbounded spend.

**v1 = L0+L1 only.** Progress registry / loopback `/stats` (dashboard) is a follow-up.

## Capability matrix

| Cap | Tools | Default |
|-----|--------|---------|
| **L0 read** | `project_info`, `plans_list`, `plan_read`, `conventions_get`, `plans_inventory_for_deps`, `plans_stale_report` | on |
| **L0.5 deps** | `plans_suggest_dependencies` — **heuristic only**, **propose only** (no file writes, no LLM) | on |
| **L1 claim** | `plans_claim`, `plans_release`, `plans_complete` (**move only** — client asserts Done when) | on |
| **L2–L4** | handoff / orchestrate / allowlisted shell | **off** (not shipped in v1) |
| **Forbidden** | promote drafts, MCP git push/merge, plan markdown writes, path escape, foreign in-progress | always |

### Refuse matrix

| Action | Result |
|--------|--------|
| Claim `drafts/` / `completed/` / `ambiguous/` / `blocked/` | refuse |
| Claim with unmet **Depends on** | refuse (unless `allow_unmet_deps=true`) |
| Claim / complete foreign `in-progress/` | refuse |
| `plan_read` outside project root | refuse |
| `plans_complete` without prior claim (not in-progress) | refuse |
| Complete runs tests/verify | **no** — move only |

### Stale / tier-gap (warn-only)

Default ready-plan age threshold: **48h** (`stale_after` in config). Codes:

- `STALE-TIER-GAP` — Preferred models tiers not in known `worker_tiers` / `--tier`
- `STALE-UNCLAIMED` — age past threshold with capacity present or unknown
- `STALE-LEASE` — expired / missing lease on in-progress
- `STALE-DEPS` — aged ready plan blocked by unmet Depends on
- `STALE-PARKED` — long stay in ambiguous/blocked

Never auto-promotes, force-claims, or rewrites Preferred models.

## Install / run

```bash
pip install "mcp[cli]" PyYAML
# From Anchor repo (scripts/ must be importable):
python mcp/project-orchestrator/server.py \
  --project /path/to/myapp \
  --agent-id cursor-mid-1 \
  --tier mid
```

### Claude Code

```bash
claude mcp add myapp-orch -- \
  python /abs/path/to/anchor/mcp/project-orchestrator/server.py \
  --project /abs/path/to/myapp \
  --agent-id cursor-mid-1 \
  --tier mid
```

### Cursor / other stdio MCP

Register the same command as a stdio server. Use a **distinct** `agent_id` from systemd `fleet_watch` workers (e.g. `cursor-mid` vs `timer-mid`) to avoid lease fights.

### Config file (optional)

`myapp/.anchor/mcp.yaml`:

```yaml
project_root: .
agent_id: cursor-mid-1
default_tier: mid
worker_tiers: [mid]
stale_after: 48h
capabilities: [L0, L1]
```

If `--project` is omitted, the server walks upward from cwd for `.anchor/mcp.yaml`, or uses cwd when it contains `.plans/`.

## Packaging note

Imports `plan_select` and `plan_lease` from Anchor `scripts/` via `sys.path` (same pattern as `anchor-prompts` / `model-fleet`). **Do not copy** those modules into this package.

## When to use which MCP

| Server | Owns |
|--------|------|
| **project-orchestrator** | One project's `.plans/` lifecycle (this package) |
| **model-fleet** | Global endpoint registry / `delegate` |
| **anchor-prompts** | Doctrine, templates, preflight (repo-agnostic) |

## Agent git (implementers of *this* repo)

If the project uses Git: use **`dev`**, else **`develop`**. If neither exists,
**create `dev` from `main` (else `master`)** and push `origin dev` when allowed.
Then `feature/<slug>` from that line; **`/commit-prep` before any `git commit`**;
**push the feature branch to origin only**; never auto-merge to dev/main.

## Non-goals (v1)

- Dashboard stats HTTP surface (Phase 4 follow-up)
- L2 fleet handoff / L3 orchestrate / L4 shell
- Human promotion of drafts
- Auto-drain of the entire backlog
