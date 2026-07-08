#!/usr/bin/env python3
"""model-fleet MCP server — lets an orchestrating agent (Claude Code, Grok Build, or a
local planner) delegate work to the hardware fleet (swarm tier, H100 tier, Space-1)
instead of burning frontier credits on keystrokes.

Run: python server.py    (needs: pip install "mcp[cli]" requests pyyaml)
Claude Code: claude mcp add model-fleet -- python /path/to/mcp/model-fleet/server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from anchor_client import Fleet, has_required_footer, load_prompt  # noqa: E402

mcp = FastMCP("model-fleet")
_fleet: Fleet | None = None


def fleet() -> Fleet:
    global _fleet
    if _fleet is None:
        _fleet = Fleet()
    return _fleet


@mcp.tool()
def list_fleet() -> str:
    """List available fleet endpoints (name, tier, model) and role→tier routing."""
    f = fleet()
    lines = [f"- {e.name} [{e.tier}] {e.model} @ {e.base_url}" for e in f.endpoints]
    lines.append("\nroles: " + ", ".join(f"{r}→{t}" for r, t in f.roles.items()))
    return "\n".join(lines)


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
