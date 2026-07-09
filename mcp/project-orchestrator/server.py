#!/usr/bin/env python3
"""project-orchestrator MCP server — limited per-project plan coordination (L0+L1).

Binds to a single project root. Tools operate only under that project's ``.plans/``.
No promote, no plan-file writes, no arbitrary shell. ``plans_complete`` is move-only.

Run:
  python server.py --project /path/to/app --agent-id cursor-mid-1 --tier mid

Claude Code:
  claude mcp add myapp-orch -- python /path/to/mcp/project-orchestrator/server.py \\
    --project /path/to/myapp --agent-id cursor-mid-1 --tier mid

Requires: pip install "mcp[cli]" PyYAML
Scripts import via Anchor monorepo ``scripts/`` on sys.path (do not copy plan_select).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

import coordinator as coord  # noqa: E402

mcp = FastMCP("project-orchestrator")
_CFG: coord.CoordinatorConfig | None = None


def _cfg() -> coord.CoordinatorConfig:
    if _CFG is None:
        raise RuntimeError("server config not initialized — pass --project")
    return _CFG


def _out(data: object) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, default=str)


def _err(exc: BaseException) -> str:
    return _out({"ok": False, "error": str(exc)})


@mcp.tool()
def project_info() -> str:
    """Project root, agent_id, tiers, Preferred orchestrator, compact stale warnings."""
    try:
        return _out(coord.project_info(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def plans_list() -> str:
    """List ready + in-progress plans (priority order) with fit/deps + stale warnings."""
    try:
        return _out(coord.plans_list(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def plan_read(plan_ref: str) -> str:
    """Read one plan under .plans/ by slug or path. Refuses paths outside the project."""
    try:
        return _out(coord.plan_read(_cfg(), plan_ref))
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def plans_inventory_for_deps() -> str:
    """Summaries of all plan lanes for dependency analysis."""
    try:
        return _out(coord.plans_inventory_for_deps(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def plans_suggest_dependencies(goal_or_plan_text: str, exclude_slug: str = "") -> str:
    """Heuristic Depends-on suggestions (propose only; no file writes; no LLM)."""
    try:
        return _out(
            coord.plans_suggest_dependencies(
                _cfg(),
                goal_or_plan_text,
                exclude_slug=exclude_slug or None,
            )
        )
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def plans_stale_report() -> str:
    """Stale / languishing plan warnings (age, tier-gap, expired lease, unmet deps). Warn-only."""
    try:
        return _out(coord.plans_stale_report(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def plans_claim(plan_ref: str, allow_unmet_deps: bool = False) -> str:
    """Claim a ready plan → in-progress + lease. Refuses unmet Depends on unless override."""
    try:
        return _out(
            coord.plans_claim(_cfg(), plan_ref, allow_unmet_deps=allow_unmet_deps)
        )
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def plans_release(plan_ref: str, target_lane: str = "") -> str:
    """Return in-progress plan to bugs|features or drop a ready-path lease."""
    try:
        return _out(
            coord.plans_release(
                _cfg(), plan_ref, target_lane=target_lane or None
            )
        )
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def plans_complete(plan_ref: str) -> str:
    """Move in-progress plan to completed/ only. Client asserts Done when — no verify in MCP."""
    try:
        return _out(coord.plans_complete(_cfg(), plan_ref))
    except coord.CoordinatorError as e:
        return _err(e)


@mcp.tool()
def conventions_get() -> str:
    """Project conventions excerpt + Preferred orchestrator if present."""
    try:
        return _out(coord.conventions_get(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


def main(argv: list[str] | None = None) -> None:
    global _CFG
    parser = argparse.ArgumentParser(description="Project orchestrator MCP (L0+L1)")
    parser.add_argument(
        "--project",
        default=None,
        help="Project root (directory with .plans/). Or set project_root in .anchor/mcp.yaml",
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help="Stable agent id for leases (distinct from fleet_watch timers)",
    )
    parser.add_argument(
        "--tier",
        default=None,
        help="Default fit tier: small|mid|reasoner|frontier",
    )
    args, _unknown = parser.parse_known_args(argv)

    try:
        _CFG = coord.build_config(
            args.project,
            agent_id=args.agent_id,
            tier=args.tier,
        )
    except coord.CoordinatorError as e:
        print(f"project-orchestrator: {e}", file=sys.stderr)
        sys.exit(2)

    mcp.run()


if __name__ == "__main__":
    main()
