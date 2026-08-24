#!/usr/bin/env python3
"""model-fleet MCP server — lets an orchestrating agent (Claude Code, Grok Build, or a
local planner) delegate work to the hardware fleet (swarm tier, H100 tier, Space-1)
instead of burning frontier credits on keystrokes.

Run: python server.py    (needs: pip install "mcp[cli]>=1.2.0,<3" requests pyyaml)
Claude Code: claude mcp add model-fleet -- python /path/to/mcp/model-fleet/server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# MCP SDK 2.0 renamed FastMCP to MCPServer and moved it out of
# `mcp.server.fastmcp`, which no longer exists. The decorator surface this server
# uses (tool/prompt/resource) and `run()` are identical across both majors, so a
# two-name shim keeps one implementation working on either — rather than pinning
# operators to a line that is already end-of-life, or breaking everyone still on v1.
try:  # SDK 2.x
    from mcp.server import MCPServer
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer


def _project_root() -> Path:
    here = Path(__file__).resolve().parent
    if here.parent.name == "mcp" and here.parent.parent.name == ".anchor":
        return here.parent.parent.parent
    if here.parent.name == "mcp":
        return here.parent.parent
    return here.parents[2]


REPO = _project_root()
for _scripts in (REPO / ".anchor" / "scripts", REPO / "scripts"):
    if _scripts.is_dir():
        sys.path.insert(0, str(_scripts))
        break

from anchor_client import Fleet, has_required_footer, load_prompt  # noqa: E402
from router import endpoint_detail, summarize_endpoints  # noqa: E402

mcp = MCPServer("model-fleet")
_fleet: Fleet | None = None


def fleet() -> Fleet:
    global _fleet
    if _fleet is None:
        _fleet = Fleet()
    return _fleet


@mcp.tool()
def list_fleet() -> str:
    """One capped summary line per fleet endpoint (name, tier, context size, capability
    phrase) plus role→tier routing. Deliberately no base_url/model/quirk detail — call
    lookup_endpoint(name) for full non-secret detail on one endpoint you actually need."""
    f = fleet()
    lines = summarize_endpoints(f)
    lines.append("\nroles: " + ", ".join(f"{r}→{t}" for r, t in f.roles.items()))
    return "\n".join(lines)


@mcp.tool()
def lookup_endpoint(name: str) -> str:
    """Full non-secret detail (base_url, model, quirks) for one fleet endpoint by name.
    Use this after list_fleet's summary names the endpoint you need more detail on —
    full detail is resolved on demand, never pasted into context by default. Never
    returns an API key: those come from ANCHOR_API_KEY at request time, not the
    registry."""
    return endpoint_detail(fleet(), name)


@mcp.tool()
def delegate(task_spec: str, role: str = "executor", thinking: bool = False) -> str:
    """Send a self-contained Anchor task spec to the fleet; returns the worker's output.
    role: executor | critic | tuner | planner. The spec must contain everything the
    worker needs — fleet workers have NO access to this conversation.
    Output is format-checked; a missing footer is returned as an error for retry."""
    ep = fleet().pick(role)
    system = load_prompt("anchor/system-prompts/mythos-core.md")
    out = ep.chat([{"role": "system", "content": system},
                   {"role": "user", "content": task_spec}],
                  thinking=thinking or role in {"planner", "critic"})
    header = f"[fleet: {ep.name} / {ep.model} / role={role}]\n\n"
    if not has_required_footer(out):
        return (header + "FORMAT-FAIL: worker output missing required footer "
                "(## Result / ## How to verify). Treat as unverified:\n\n" + out)
    return header + out


@mcp.tool()
def delegate_parallel_review(task_spec: str, work: str) -> str:
    """Space-1-style verify-twice: run TWO independent critic passes in fresh contexts
    and report whether they agree. Use for high-stakes accept/reject decisions."""
    f = fleet()
    template = load_prompt("anchor/templates/review.md")
    system = load_prompt("anchor/system-prompts/mythos-core.md")
    prompt = (f"You are the critic. Review only; do not fix.\n\nTEMPLATE:\n{template}\n\n"
              f"SPEC:\n{task_spec}\n\nWORK:\n{work}")
    verdicts = []
    for i in range(2):
        ep = f.pick("critic")
        out = ep.chat([{"role": "system", "content": system},
                       {"role": "user", "content": prompt}], thinking=True)
        v = "ACCEPT" if "ACCEPT" in out.upper() else ("REVISE" if "REVISE" in out.upper() else "ESCALATE")
        verdicts.append((ep.name, v, out))
    agree = verdicts[0][1] == verdicts[1][1]
    head = (f"AGREEMENT: {verdicts[0][1]}" if agree
            else f"DISAGREEMENT ({verdicts[0][1]} vs {verdicts[1][1]}) — HOLD for human/frontier review")
    body = "\n\n".join(f"--- critic {n} ({v}) ---\n{o[:3000]}" for n, v, o in verdicts)
    return f"{head}\n\n{body}"


@mcp.tool()
def fleet_health() -> str:
    """Ping every endpoint with a 1-token request; report reachable/unreachable."""
    results = []
    for e in fleet().endpoints:
        try:
            e.chat([{"role": "user", "content": "ping"}], max_tokens=1, timeout=15)
            results.append(f"OK    {e.name} [{e.tier}]")
        except Exception as ex:
            results.append(f"DOWN  {e.name} [{e.tier}] — {str(ex)[:80]}")
    return "\n".join(results)


if __name__ == "__main__":
    mcp.run()
