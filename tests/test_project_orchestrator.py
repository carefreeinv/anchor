"""Tests for mcp/project-orchestrator (L0+L1 coordinator logic)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "mcp" / "project-orchestrator"))

from coordinator import (  # noqa: E402
    CoordinatorError,
    build_config,
    plan_read,
    plans_claim,
    plans_complete,
    plans_heartbeat,
    plans_list,
    plans_stale_report,
    plans_suggest_dependencies,
    project_info,
)


def _plans_tree(root: Path) -> Path:
    plans = root / ".plans"
    for lane in (
        "bugs",
        "features",
        "in-progress",
        "ambiguous",
        "blocked",
        "drafts",
        "completed",
    ):
        (plans / lane).mkdir(parents=True)
    return plans


def _write(
    path: Path,
    *,
    title: str = "t",
    preferred: str = "mid",
    goal: str = "do the thing",
    depends: str = "none",
    value: str = "medium",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Plan: {title}\n\n"
        f"- **Value:** {value}\n"
        f"- **Slug:** {path.stem.replace('.local', '')}\n"
        f"- **Preferred models:** {preferred}\n"
        f"- **Depends on:** {depends}\n\n"
        f"## Goal\n{goal}\n\n"
        f"## Steps\n| 1 | x |\n\n"
        f"## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def test_path_escape_refused(tmp_path: Path):
    _plans_tree(tmp_path)
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    with pytest.raises(CoordinatorError, match="escapes|outside|only allows"):
        plan_read(cfg, str(tmp_path.parent / "secret.md"))


def test_drafts_claim_refused(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    _write(plans / "drafts" / "idea.md", title="idea")
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    with pytest.raises(CoordinatorError, match="refuse|drafts"):
        plans_claim(cfg, "drafts/idea.md")


def test_claim_double_and_foreign_in_progress(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    _write(plans / "features" / "foo.md", title="foo", goal="implement foo feature")
    cfg_a = build_config(tmp_path, agent_id="agent-a", tier="mid")
    out = plans_claim(cfg_a, "features/foo.md")
    assert out["ok"] is True
    assert out["plan_rel"] == "in-progress/foo.md"
    assert (plans / "in-progress" / "foo.md").is_file()
    assert not (plans / "features" / "foo.md").exists()

    cfg_b = build_config(tmp_path, agent_id="agent-b", tier="mid")
    with pytest.raises(CoordinatorError, match="owned by|foreign|claimed"):
        plans_claim(cfg_b, "in-progress/foo.md")


def test_complete_moves_to_review_needed(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    _write(plans / "features" / "foo.md")
    cfg = build_config(tmp_path, agent_id="agent-a", tier="mid")
    plans_claim(cfg, "features/foo.md")
    done = plans_complete(cfg, "in-progress/foo.md")
    # Agent-complete lands in review-needed/ for human sign-off, not completed/.
    assert done["action"] == "move_to_review_needed"
    assert (plans / "review-needed" / "foo.md").is_file()
    assert not (plans / "completed" / "foo.md").exists()
    assert not (plans / "in-progress" / "foo.md").exists()


def test_heartbeat_extends_and_foreign_refused(tmp_path: Path):
    import plan_lease

    plans = _plans_tree(tmp_path)
    _write(plans / "features" / "foo.md")
    cfg_a = build_config(tmp_path, agent_id="agent-a", tier="mid")
    plans_claim(cfg_a, "features/foo.md")
    before = plan_lease.read_lease(plans, "in-progress/foo.md").expires_at
    hb = plans_heartbeat(cfg_a, "in-progress/foo.md")
    assert hb["ok"] and hb["expires_at"] >= before

    # A different agent can neither heartbeat nor claim the active in-progress plan.
    cfg_b = build_config(tmp_path, agent_id="agent-b", tier="mid")
    with pytest.raises(CoordinatorError, match="agent-a"):
        plans_heartbeat(cfg_b, "in-progress/foo.md")
    with pytest.raises(CoordinatorError, match="agent-a"):
        plans_claim(cfg_b, "in-progress/foo.md")


def test_claim_no_silent_reclaim_then_recover(tmp_path: Path):
    import plan_lease
    from plan_lease import Lease, _write_lease_force, lease_path

    plans = _plans_tree(tmp_path)
    _write(plans / "features" / "foo.md")
    cfg_a = build_config(tmp_path, agent_id="agent-a", tier="mid")
    plans_claim(cfg_a, "features/foo.md")
    # Expire agent-a's lease (simulate crashed agent past the long TTL).
    _write_lease_force(
        lease_path(plans, "in-progress/foo.md"),
        Lease("in-progress/foo.md", "agent-a", time.time() - 100, time.time() - 10),
    )
    cfg_b = build_config(tmp_path, agent_id="agent-b", tier="mid")
    # No active lease → refuse without recover (no silent reclaim).
    with pytest.raises(CoordinatorError, match="no active lease"):
        plans_claim(cfg_b, "in-progress/foo.md")
    # recover=True takes over the abandoned plan.
    res = plans_claim(cfg_b, "in-progress/foo.md", recover=True)
    assert res["ok"] and res["agent_id"] == "agent-b"
    assert plan_lease.owner_of(plans, "in-progress/foo.md") == "agent-b"


def test_complete_refuses_ready_without_claim(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    _write(plans / "features" / "foo.md")
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    with pytest.raises(CoordinatorError, match="in-progress"):
        plans_complete(cfg, "features/foo.md")


def test_unmet_deps_claim_refused(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    _write(
        plans / "features" / "dep.md",
        title="dep",
        goal="foundation api layer for clients",
    )
    _write(
        plans / "features" / "child.md",
        title="child",
        goal="build client on foundation api",
        depends="dep",
    )
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    with pytest.raises(CoordinatorError, match="unmet Depends"):
        plans_claim(cfg, "features/child.md")
    # override works
    out = plans_claim(cfg, "features/child.md", allow_unmet_deps=True)
    assert out["ok"] is True


def test_suggest_dependencies_heuristic(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    _write(
        plans / "features" / "mqtt-broker.md",
        title="mqtt broker",
        goal="central mqtt broker for load signals and inference throttle",
    )
    _write(
        plans / "features" / "other.md",
        title="docs polish",
        goal="fix typos in readme only",
    )
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    text = (
        "Add mqtt client that honors load level from central mqtt broker "
        "for inference throttle"
    )
    sug = plans_suggest_dependencies(cfg, text, exclude_slug="new-mqtt-client")
    assert sug["method"] == "heuristic_token_overlap"
    assert "note" in sug and "Propose only" in sug["note"]
    slugs = [c["slug"] for c in sug["candidates"]]
    assert "mqtt-broker" in slugs


def test_stale_tier_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    plans = _plans_tree(tmp_path)
    p = plans / "features" / "heavy.md"
    _write(p, title="heavy", preferred="frontier", goal="architecture redesign")
    # force old mtime
    old = time.time() - 72 * 3600
    os.utime(p, (old, old))
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    # only mid capacity
    cfg.worker_tiers = ["mid"]
    cfg.default_tier = "mid"
    cfg.stale_after_hours = 48.0
    report = plans_stale_report(cfg)
    codes = {w["code"] for w in report["warnings"]}
    assert "STALE-TIER-GAP" in codes
    causes = {w["cause"] for w in report["warnings"]}
    assert "tier_gap" in causes


def test_project_info_and_list(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    _write(plans / "features" / "foo.md", value="high")
    (tmp_path / "ANCHOR-CONVENTIONS.md").write_text(
        "# Conv\n\n- **Preferred orchestrator:** claude:opus\n",
        encoding="utf-8",
    )
    cfg = build_config(tmp_path, agent_id="ide-mid", tier="mid")
    info = project_info(cfg)
    assert info["agent_id"] == "ide-mid"
    assert info["preferred_orchestrator"]
    listing = plans_list(cfg)
    assert any(p["slug"] == "foo" for p in listing["plans"])


def test_config_yaml(tmp_path: Path):
    _plans_tree(tmp_path)
    anchor = tmp_path / ".anchor"
    anchor.mkdir()
    (anchor / "mcp.yaml").write_text(
        "project_root: .\n"
        "agent_id: from-yaml\n"
        "default_tier: small\n"
        "worker_tiers: [small, mid]\n"
        "stale_after: 24h\n"
        "capabilities: [L0, L1]\n",
        encoding="utf-8",
    )
    cfg = build_config(tmp_path)
    assert cfg.agent_id == "from-yaml"
    assert cfg.default_tier == "small"
    assert "mid" in cfg.worker_tiers
    assert cfg.stale_after_hours == 24.0


# ---- role-scoped toolsets (server.register_tools + scripts/roles.py) ----

import server  # noqa: E402  (mcp/project-orchestrator on sys.path above)


class FakeMCP:
    """Records what a FastMCP server would register — no mcp package needed."""

    def __init__(self):
        self.registered: list[str] = []

    def tool(self):
        def deco(fn):
            self.registered.append(fn.__name__)
            return fn

        return deco


LIFECYCLE = {"plans_claim", "plans_release", "plans_complete"}


def test_planner_session_lists_no_write_or_dispatch_tools():
    fake = FakeMCP()
    server.register_tools(fake, role="planner")
    assert set(fake.registered) & LIFECYCLE == set()
    assert "plans_list" in fake.registered
    assert "plan_read" in fake.registered


def test_critic_session_lists_no_write_or_dispatch_tools():
    fake = FakeMCP()
    server.register_tools(fake, role="critic")
    assert set(fake.registered) & LIFECYCLE == set()


def test_executor_and_default_sessions_get_lifecycle_tools():
    for role in ("executor", None):
        fake = FakeMCP()
        server.register_tools(fake, role=role)
        assert LIFECYCLE <= set(fake.registered)
    # every declared tool name exists as a registered function
    fake = FakeMCP()
    names = server.register_tools(fake, role=None)
    assert names == fake.registered
    assert set(names) == set(server._TOOL_FUNCS)
