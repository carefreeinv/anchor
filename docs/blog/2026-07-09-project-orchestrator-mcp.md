---
title: Per-project plan orchestration via MCP
authors: [carefree]
tags: [feature, tooling]
---

Coding agents can now list, claim, and complete plans for **one project** through a limited MCP surface — without full shell, silent promote, or unbounded spend.

<!-- truncate -->

Anchor already had `/work`, headless `work_once`, and two MCPs that were either doctrine (`anchor-prompts`) or global fleet endpoints (`model-fleet`). What was missing was a **project-bound** tool plane for `.plans/` itself. The new **`mcp/project-orchestrator/`** server fills that gap.

Bind one process to one app root:

```bash
python mcp/project-orchestrator/server.py \
  --project /path/to/myapp \
  --agent-id cursor-mid-1 \
  --tier mid
```

Or register it with Claude Code / any stdio MCP client using the same flags. Optional project config lives at `.anchor/mcp.yaml` (`agent_id`, `worker_tiers`, `stale_after`, capabilities).

**v1 is deliberately L0+L1.** Agents get inventory, plan read, conventions, heuristic dependency *suggestions* (propose only — no LLM, no plan-file writes), stale/tier-gap warnings, claim/release, and **move-only complete** after the client asserts Done when. Selection and leases reuse `plan_select` / `plan_lease` — the same rules as `/work`. Promote stays human-only. L2 handoff, L3 orchestrate, L4 allowlisted shell, and loopback dashboard stats are deferred follow-ups.

Use a **distinct** `--agent-id` from systemd `fleet_watch` workers so leases do not fight. Full matrix and refuse rules: `mcp/project-orchestrator/README.md`. Docs overview: [MCP servers](/tooling/mcp-servers).

Alongside this, agent process rules are stricter for any Anchor-scaffolded project: run **`/commit-prep` before every commit** (project-agnostic tests/changelog/blog), and open feature branches from **`dev`/`develop`** — creating **`dev` from `main`/`master`** when the integration branch is missing. Those are operator/agent discipline, not new product binaries, but they keep multi-agent work reviewable.
