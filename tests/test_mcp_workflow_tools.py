"""MCP tools generated from anchor_ops — envelope + refusals."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "mcp" / "project-orchestrator"))

import server  # noqa: E402
from coordinator import CoordinatorError, build_config, plans_claim  # noqa: E402
from test_project_orchestrator import FakeMCP, _plans_tree, _write  # noqa: E402


def test_review_prepare_never_merges(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    (plans / "review-needed").mkdir(exist_ok=True)
    _write(plans / "review-needed" / "r1.md", title="r1")
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    server._CFG = cfg
    raw = server.review_prepare("r1")
    doc = json.loads(raw)
    assert doc.get("ok") is False or doc.get("exit_code") == 3 or "pending" in doc
    pending = doc.get("pending") or []
    assert any(
        (p.get("needs") == "operator") for p in pending
    ) or "operator" in json.dumps(doc).lower()
    assert (plans / "review-needed" / "r1.md").is_file()
    assert list((tmp_path / ".git").glob("*") if (tmp_path / ".git").exists() else []) == []


def test_work_claim_envelope_matches_alias(tmp_path: Path):
    plans = _plans_tree(tmp_path)
    _write(plans / "features" / "mine.md", title="mine", assignee="ai")
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    server._CFG = cfg
    via_alias = plans_claim(cfg, "features/mine.md")
    assert via_alias["ok"] and "in-progress" in via_alias["plan_rel"]


def test_no_approve_parameter_on_review_prepare():
    import inspect

    sig = inspect.signature(server.review_prepare)
    assert "approve" not in sig.parameters
    assert "decision" not in sig.parameters
    assert "confirm" not in sig.parameters


def test_planner_omits_mutating_workflow_tools():
    fake = FakeMCP()
    names = set(server.register_tools(fake, role="planner"))
    for n in ("plans_claim", "work_claim", "work_finish", "draft_create"):
        assert n not in names
    assert "work_list" in names


def test_path_escape_on_work_claim(tmp_path: Path):
    _plans_tree(tmp_path)
    cfg = build_config(tmp_path, agent_id="a", tier="mid")
    with pytest.raises(CoordinatorError):
        plans_claim(cfg, str(tmp_path.parent / "secret.md"))
