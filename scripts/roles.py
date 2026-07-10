#!/usr/bin/env python3
"""Role→capability map: planner / executor / critic as harness-enforced
capability sets, not prompt framing (ANCHOR.md role separation; mythos-core
rule 2 cross-ref).

One module owns the map — ``orchestrate.py`` and the project-orchestrator MCP
server both read it; nothing re-declares role powers elsewhere.

- **planner** — read anything; write only under ``.plans/**`` (plans and spec
  drafts); never dispatches executors.
- **executor** — write per task-spec scope (the scope gate enforces the spec;
  this map adds the role boundary): never ``.plans/**`` and never its own spec.
- **critic** — read-only; its output is the review artifact, not file edits.
- **orchestrator** — the coordinating process itself; unrestricted writes and
  the only role that dispatches.

Path rules reuse ``scope_gate.path_matches`` (one glob implementation, one
semantics — see that module's docstring). Deny patterns win over allow.
"""
from __future__ import annotations

from dataclasses import dataclass

from scope_gate import path_matches


class RoleError(ValueError):
    """Unknown role name."""


# project-orchestrator MCP tool names, grouped by what they can do.
MCP_READ_TOOLS = (
    "project_info",
    "plans_list",
    "plan_read",
    "plans_inventory_for_deps",
    "plans_suggest_dependencies",
    "plans_stale_report",
    "conventions_get",
)
MCP_LIFECYCLE_TOOLS = ("plans_claim", "plans_release", "plans_complete")


@dataclass(frozen=True)
class RoleCapabilities:
    """What one role may do. ``write_deny`` beats ``write_allow``; an empty
    ``write_allow`` means read-only."""

    role: str
    write_allow: tuple[str, ...]
    write_deny: tuple[str, ...]
    can_dispatch: bool
    mcp_tools: tuple[str, ...]


PLANNER = RoleCapabilities(
    role="planner",
    write_allow=(".plans/**",),
    write_deny=(),
    can_dispatch=False,
    mcp_tools=MCP_READ_TOOLS,
)
EXECUTOR = RoleCapabilities(
    role="executor",
    write_allow=("**",),
    write_deny=(".plans/**",),
    can_dispatch=False,
    mcp_tools=MCP_READ_TOOLS + MCP_LIFECYCLE_TOOLS,
)
CRITIC = RoleCapabilities(
    role="critic",
    write_allow=(),
    write_deny=("**",),
    can_dispatch=False,
    mcp_tools=MCP_READ_TOOLS,
)
ORCHESTRATOR = RoleCapabilities(
    role="orchestrator",
    write_allow=("**",),
    write_deny=(),
    can_dispatch=True,
    mcp_tools=MCP_READ_TOOLS + MCP_LIFECYCLE_TOOLS,
)

ROLES: dict[str, RoleCapabilities] = {
    r.role: r for r in (PLANNER, EXECUTOR, CRITIC, ORCHESTRATOR)
}


def capabilities_for(role: str) -> RoleCapabilities:
    try:
        return ROLES[role.strip().lower()]
    except KeyError:
        raise RoleError(
            f"unknown role {role!r} (valid: {', '.join(sorted(ROLES))})"
        ) from None


def can_write(caps: RoleCapabilities, path: str, *, extra_deny: tuple[str, ...] = ()) -> bool:
    """True if the role may write ``path``. ``extra_deny`` adds per-task
    forbidden paths (e.g. an executor's own task-spec file)."""
    if any(path_matches(path, d) for d in (*caps.write_deny, *extra_deny)):
        return False
    return any(path_matches(path, a) for a in caps.write_allow)


@dataclass(frozen=True)
class RoleWriteVerdict:
    ok: bool
    role: str
    offending: tuple[str, ...] = ()
    message: str = ""


def check_role_writes(
    caps: RoleCapabilities,
    paths: list[str] | tuple[str, ...],
    *,
    extra_deny: tuple[str, ...] = (),
) -> RoleWriteVerdict:
    """Classify a set of written paths against a role's write boundary.

    Unlike the scope gate (which is inactive without a declared scope), the
    role boundary is always active: an empty ``write_allow`` denies everything.
    """
    offending = tuple(
        p for p in paths if not can_write(caps, p, extra_deny=extra_deny)
    )
    if not offending:
        return RoleWriteVerdict(
            ok=True, role=caps.role,
            message=f"role OK: all writes within the {caps.role} boundary",
        )
    lines = [
        f"ROLE VIOLATION: {caps.role} wrote outside its capability boundary.",
        "Offending paths:",
        *(f"  - {p}" for p in offending),
        f"Allowed: {', '.join(caps.write_allow) or '(read-only)'}",
    ]
    denied = (*caps.write_deny, *extra_deny)
    if denied:
        lines.append(f"Denied: {', '.join(denied)}")
    lines.append(
        "Fix: route the change to the role that owns those paths — roles do "
        "not self-promote."
    )
    return RoleWriteVerdict(
        ok=False, role=caps.role, offending=offending, message="\n".join(lines)
    )


def mcp_toolset_for(role: str | None) -> tuple[str, ...]:
    """MCP tool names a session opened as ``role`` may see (deny by omission).

    ``None`` (no role given) keeps the orchestrator's full toolset — the
    pre-role behavior of the server.
    """
    if role is None:
        return ORCHESTRATOR.mcp_tools
    return capabilities_for(role).mcp_tools
