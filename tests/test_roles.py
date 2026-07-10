"""Tests for scripts/roles.py — the role→capability map."""
import pytest
from roles import (
    CRITIC,
    EXECUTOR,
    ORCHESTRATOR,
    PLANNER,
    RoleError,
    can_write,
    capabilities_for,
    check_role_writes,
    mcp_toolset_for,
)


def test_planner_write_to_src_denied():
    verdict = check_role_writes(PLANNER, ["src/api.py"])
    assert not verdict.ok
    assert verdict.offending == ("src/api.py",)
    assert "ROLE VIOLATION" in verdict.message


def test_planner_may_write_plans_tree():
    verdict = check_role_writes(
        PLANNER, [".plans/drafts/foo.md", ".plans/features/bar.local.md"]
    )
    assert verdict.ok


def test_executor_write_to_plans_denied():
    verdict = check_role_writes(EXECUTOR, ["src/api.py", ".plans/features/foo.md"])
    assert not verdict.ok
    assert verdict.offending == (".plans/features/foo.md",)


def test_executor_cannot_edit_own_spec_via_extra_deny():
    verdict = check_role_writes(
        EXECUTOR, ["src/api.py", "specs/task-1.md"], extra_deny=("specs/task-1.md",)
    )
    assert not verdict.ok
    assert verdict.offending == ("specs/task-1.md",)


def test_critic_write_denied():
    verdict = check_role_writes(CRITIC, ["docs/review.md"])
    assert not verdict.ok
    assert "read-only" in verdict.message


def test_critic_no_writes_is_ok():
    assert check_role_writes(CRITIC, []).ok


def test_orchestrator_unrestricted():
    assert check_role_writes(ORCHESTRATOR, [".plans/bugs/a.md", "src/x.py"]).ok
    assert ORCHESTRATOR.can_dispatch


def test_only_orchestrator_dispatches():
    assert not PLANNER.can_dispatch
    assert not EXECUTOR.can_dispatch
    assert not CRITIC.can_dispatch


def test_can_write_deny_beats_allow():
    assert can_write(EXECUTOR, "src/x.py")
    assert not can_write(EXECUTOR, ".plans/in-progress/x.md")


def test_capabilities_for_normalizes_and_rejects_unknown():
    assert capabilities_for(" Planner ") is PLANNER
    with pytest.raises(RoleError, match="unknown role"):
        capabilities_for("wizard")


def test_mcp_toolset_planner_excludes_write_and_dispatch_tools():
    tools = mcp_toolset_for("planner")
    assert "plans_list" in tools
    assert "plan_read" in tools
    for lifecycle in ("plans_claim", "plans_release", "plans_complete"):
        assert lifecycle not in tools


def test_mcp_toolset_critic_is_read_only():
    tools = mcp_toolset_for("critic")
    assert set(tools) & {"plans_claim", "plans_release", "plans_complete"} == set()


def test_mcp_toolset_default_is_full_orchestrator_surface():
    assert mcp_toolset_for(None) == ORCHESTRATOR.mcp_tools
    assert "plans_claim" in mcp_toolset_for(None)
