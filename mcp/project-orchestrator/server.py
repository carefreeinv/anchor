#!/usr/bin/env python3
"""project-orchestrator MCP server — limited per-project plan coordination (L0+L1).

Binds to a single project root. Tools operate only under that project's ``.plans/``.
No promote, no plan-file writes, no arbitrary shell. ``plans_complete`` is move-only.

Exposure of ``anchor_ops`` operations (MCP is always non-interactive; Answers never
answers; ``--delegate`` is not exposed):

| Operation | MCP | Why |
|-----------|-----|-----|
| plans.list | exposed as ``plans_list`` / ``work_list`` | read |
| plans.board | not exposed | TTY/passthrough |
| models.list | not exposed | fleet, not this server |
| models.nick | not exposed | mutates overlay |
| work.list | exposed ``work_list`` | read |
| work.claim | exposed ``work_claim`` (alias ``plans_claim``) | cap L1 |
| work.heartbeat | exposed ``work_heartbeat`` (alias ``plans_heartbeat``) | cap L1 |
| work.return | exposed ``work_return`` (alias ``plans_release``) | cap L1 |
| work.finish | exposed ``work_finish`` | cap L1; finish-gate |
| work.complete | exposed ``work_complete`` / ``plans_complete`` | move-only alias |
| review.list | exposed ``review_list`` | read |
| review.review | prepare-only ``review_prepare`` | never merge/approve |
| review.promote | not exposed | lands mainline |
| draft.list | exposed ``draft_list`` | read |
| draft.create | exposed ``draft_create`` | scaffold only; no auto-promote |
| draft.promote | not exposed | operator |
| fleet-watch.* | not exposed | host/systemd |


Toolsets are role-scoped (``scripts/roles.py``): a session opened as ``--role
planner`` or ``--role critic`` never even sees the plan-lifecycle tools
(``plans_claim`` / ``plans_release`` / ``plans_complete``) — deny by omission,
not by refusal. No ``--role`` keeps the full orchestrator surface.

Run:
  python server.py --project /path/to/app --agent-id cursor-mid-1 --tier mid
  python server.py --project /path/to/app --role planner   # read-only toolset

Claude Code:
  claude mcp add myapp-orch -- python /path/to/mcp/project-orchestrator/server.py \\
    --project /path/to/myapp --agent-id cursor-mid-1 --tier mid

Requires: pip install "mcp[cli]>=1.2.0,<3" PyYAML
Scripts import via Anchor ``scripts/`` on sys.path (do not copy plan_select).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_root() -> Path:
    """Minimal root guess used only to locate ``scripts/`` before anchor_client
    is importable. Mirrors anchor_client.project_root_from's mcp/ case; REPO is
    reassigned to the real resolver's output right after the import below."""
    here = Path(__file__).resolve().parent
    if here.parent.name == "mcp" and here.parent.parent.name == ".anchor":
        return here.parent.parent.parent
    if here.parent.name == "mcp":
        return here.parent.parent
    return here.parents[2]


REPO = _bootstrap_root()
for _scripts in (REPO / ".anchor" / "scripts", REPO / "scripts"):
    if _scripts.is_dir():
        sys.path.insert(0, str(_scripts))
        break
sys.path.insert(0, str(Path(__file__).resolve().parent))

from anchor_client import project_root_from  # noqa: E402

REPO = project_root_from(Path(__file__))

import coordinator as coord  # noqa: E402
import roles  # noqa: E402

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


def project_info() -> str:
    """Project root, agent_id, tiers, Preferred orchestrator, compact stale warnings."""
    try:
        return _out(coord.project_info(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


def plans_list() -> str:
    """List ready + in-progress plans (priority order) with fit/deps + stale warnings."""
    try:
        return _out(coord.plans_list(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


def plan_read(plan_ref: str) -> str:
    """Read one plan under .plans/ by slug or path. Refuses paths outside the project."""
    try:
        return _out(coord.plan_read(_cfg(), plan_ref))
    except coord.CoordinatorError as e:
        return _err(e)


def plans_inventory_for_deps() -> str:
    """Summaries of all plan lanes for dependency analysis."""
    try:
        return _out(coord.plans_inventory_for_deps(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


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


def plans_stale_report() -> str:
    """Stale / languishing plan warnings (age, tier-gap, expired lease, unmet deps). Warn-only."""
    try:
        return _out(coord.plans_stale_report(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


def plans_claim(
    plan_ref: str, allow_unmet_deps: bool = False, recover: bool = False
) -> str:
    """Claim a ready plan → in-progress + lease (the move IS the claim).

    Refuses unmet Depends on unless allow_unmet_deps. Refuses an in-progress plan
    with no active lease unless recover=True (take over a crashed agent's work
    whose lease expired past the long TTL); never reclaims an active foreign lease.
    """
    try:
        return _out(
            coord.plans_claim(
                _cfg(),
                plan_ref,
                allow_unmet_deps=allow_unmet_deps,
                recover=recover,
            )
        )
    except coord.CoordinatorError as e:
        return _err(e)


def plans_heartbeat(plan_ref: str) -> str:
    """Extend your lease on an in-progress plan (keep-alive under the long TTL)."""
    try:
        return _out(coord.plans_heartbeat(_cfg(), plan_ref))
    except coord.CoordinatorError as e:
        return _err(e)


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


def plans_complete(plan_ref: str) -> str:
    """Move in-progress plan → review-needed/ for human sign-off. Client asserts Done when — no verify in MCP."""
    try:
        return _out(coord.plans_complete(_cfg(), plan_ref))
    except coord.CoordinatorError as e:
        return _err(e)


def conventions_get() -> str:
    """Project conventions excerpt + Preferred orchestrator if present."""
    try:
        return _out(coord.conventions_get(_cfg()))
    except coord.CoordinatorError as e:
        return _err(e)


def _op_json(name: str, params: object) -> str:
    import ops_bridge

    cfg = _cfg()
    try:
        return _out(ops_bridge.call_op(cfg.agent_id, name, params))
    except ops_bridge.BridgeError as e:
        return _err(e)
    except coord.CoordinatorError as e:
        return _err(e)


def work_list() -> str:
    """Ready plans with fit/deps (CLI ``work.list`` envelope)."""
    import anchor_ops as _ops

    cfg = _cfg()
    return _op_json(
        "work.list",
        _ops.WorkListParams(root=str(cfg.project_root), tier=cfg.default_tier),
    )


def work_claim(slug: str, allow_unmet_deps: bool = False) -> str:
    """Claim by slug (CLI envelope). Alias of plans_claim."""
    import anchor_ops as _ops

    cfg = _cfg()
    coord.require_cap(cfg, coord.CAP_L1)
    return _op_json(
        "work.claim",
        _ops.WorkClaimParams(
            root=str(cfg.project_root),
            slug=slug,
            no_fit_check=True,
            no_dep_check=allow_unmet_deps,
            tier=cfg.default_tier,
        ),
    )


def work_heartbeat(slug: str) -> str:
    """Extend lease (CLI envelope)."""
    import anchor_ops as _ops

    cfg = _cfg()
    coord.require_cap(cfg, coord.CAP_L1)
    return _op_json(
        "work.heartbeat",
        _ops.WorkSlugParams(root=str(cfg.project_root), slug=slug),
    )


def work_return(slug: str) -> str:
    """Return in-progress to ready (CLI envelope)."""
    import anchor_ops as _ops

    cfg = _cfg()
    coord.require_cap(cfg, coord.CAP_L1)
    return _op_json(
        "work.return",
        _ops.WorkSlugParams(root=str(cfg.project_root), slug=slug),
    )


def work_finish(slug: str) -> str:
    """Finish with evidence gate → review-needed (CLI envelope)."""
    import anchor_ops as _ops

    cfg = _cfg()
    coord.require_cap(cfg, coord.CAP_L1)
    return _op_json(
        "work.finish",
        _ops.WorkSlugParams(root=str(cfg.project_root), slug=slug),
    )


def work_complete(slug: str) -> str:
    """Move-only complete (legacy plans_complete; no finish-gate)."""
    import anchor_ops as _ops

    cfg = _cfg()
    coord.require_cap(cfg, coord.CAP_L1)
    return _op_json(
        "work.complete",
        _ops.WorkSlugParams(root=str(cfg.project_root), slug=slug),
    )


def review_list() -> str:
    """review-needed inventory (CLI envelope)."""
    import anchor_ops as _ops

    cfg = _cfg()
    return _op_json(
        "review.list",
        _ops.ReviewListParams(root=str(cfg.project_root)),
    )


def review_prepare(slug: str) -> str:
    """Package a review; never merge or approve (needs_operator)."""
    import anchor_ops as _ops

    cfg = _cfg()
    return _op_json(
        "review.review",
        _ops.ReviewParams(
            root=str(cfg.project_root), slug=slug, no_delegate=True,
        ),
    )


def draft_list() -> str:
    """List drafts (CLI envelope)."""
    import anchor_ops as _ops

    cfg = _cfg()
    return _op_json("draft.list", _ops.DraftListParams(root=str(cfg.project_root)))


def draft_create(slug: str, title: str = "", goal: str = "") -> str:
    """Scaffold a draft; does not promote."""
    import anchor_ops as _ops

    cfg = _cfg()
    coord.require_cap(cfg, coord.CAP_L1)
    return _op_json(
        "draft.create",
        _ops.DraftCreateParams(
            root=str(cfg.project_root),
            slug=slug,
            title=title or None,
            goal=goal or None,
            local=True,
        ),
    )


_TOOL_FUNCS = {
    fn.__name__: fn
    for fn in (
        project_info,
        plans_list,
        plan_read,
        plans_inventory_for_deps,
        plans_suggest_dependencies,
        plans_stale_report,
        plans_claim,
        plans_heartbeat,
        plans_release,
        plans_complete,
        conventions_get,
        work_list,
        work_claim,
        work_heartbeat,
        work_return,
        work_finish,
        work_complete,
        review_list,
        review_prepare,
        draft_list,
        draft_create,
    )
}


def register_tools(server, role: str | None = None) -> list[str]:
    """Register only the tools the role may see (roles.mcp_toolset_for).

    ``server`` needs an MCP-server-style ``tool()`` decorator factory. Returns the
    registered tool names, in registration order.
    """
    names = [n for n in roles.mcp_toolset_for(role) if n in _TOOL_FUNCS]
    for name in names:
        server.tool()(_TOOL_FUNCS[name])
    return names


def build_server(role: str | None = None):
    """MCP server exposing the role's toolset (import deferred so the
    registration logic stays testable without the mcp package installed)."""
    try:  # SDK 2.x — see the note in mcp/model-fleet/server.py
        from mcp.server import MCPServer
    except ImportError:  # SDK 1.x
        from mcp.server.fastmcp import FastMCP as MCPServer

    server = MCPServer("project-orchestrator")
    register_tools(server, role)
    return server


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
    parser.add_argument(
        "--role",
        default=None,
        choices=sorted(roles.ROLES),
        help="Scope the exposed toolset to this role (default: full orchestrator surface)",
    )
    args, _unknown = parser.parse_known_args(argv)

    try:
        from anchor_client import load_dotenv

        load_dotenv()
        _CFG = coord.build_config(
            args.project,
            agent_id=args.agent_id,
            tier=args.tier,
        )
    except coord.CoordinatorError as e:
        print(f"project-orchestrator: {e}", file=sys.stderr)
        sys.exit(2)

    build_server(args.role).run()


if __name__ == "__main__":
    main()
