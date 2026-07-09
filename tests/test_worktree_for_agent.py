"""Tests for scripts/worktree_for_agent.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from worktree_for_agent import (  # noqa: E402
    WorktreeError,
    ensure_integration_branch,
    ensure_worktree,
    feature_branch_name,
    get_path,
    remove_worktree,
    safe_agent_id,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README").write_text("hi\n", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")
    # Ensure branch is main for predictable trunk
    _git(root, "branch", "-M", "main")
    return root


def test_safe_agent_id():
    assert safe_agent_id("mid-1") == "mid-1"
    assert "/" not in safe_agent_id("a/b c")
    assert safe_agent_id("!!!") == "agent"


def test_feature_branch_name():
    assert feature_branch_name("fix-login") == "feature/fix-login"
    assert feature_branch_name("feature/x") == "feature/x"


def test_ensure_integration_creates_dev(tmp_path: Path):
    root = _init_repo(tmp_path)
    name, created = ensure_integration_branch(root)
    assert name == "dev"
    assert created is True
    name2, created2 = ensure_integration_branch(root)
    assert name2 == "dev"
    assert created2 is False


def test_ensure_worktree_and_feature(tmp_path: Path):
    root = _init_repo(tmp_path)
    rec = ensure_worktree(root, "mid-1", slug="fix-login")
    assert Path(rec.path).is_dir()
    assert (Path(rec.path) / "README").is_file()
    assert rec.branch == "feature/fix-login"
    assert rec.integration == "dev"
    # second ensure reuses
    rec2 = ensure_worktree(root, "mid-1", slug="fix-login")
    assert Path(rec2.path) == Path(rec.path)
    assert get_path(root, "mid-1") == Path(rec.path)


def test_two_agents_two_worktrees(tmp_path: Path):
    root = _init_repo(tmp_path)
    a = ensure_worktree(root, "agent-a", slug="plan-a")
    b = ensure_worktree(root, "agent-b", slug="plan-b")
    assert Path(a.path) != Path(b.path)
    assert a.branch != b.branch
    # both have independent checkouts
    (Path(a.path) / "a.txt").write_text("a\n", encoding="utf-8")
    (Path(b.path) / "b.txt").write_text("b\n", encoding="utf-8")
    assert not (Path(b.path) / "a.txt").exists()
    assert not (Path(a.path) / "b.txt").exists()


def test_remove_worktree(tmp_path: Path):
    root = _init_repo(tmp_path)
    rec = ensure_worktree(root, "mid-1")
    assert Path(rec.path).is_dir()
    assert remove_worktree(root, "mid-1", force=True) is True
    assert get_path(root, "mid-1") is None


def test_no_trunk_raises(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()
    # not a git repo
    with pytest.raises(WorktreeError, match="not a git"):
        ensure_worktree(root, "x")


def test_cli_ensure(tmp_path: Path):
    root = _init_repo(tmp_path)
    script = REPO / "scripts" / "worktree_for_agent.py"
    r = subprocess.run(
        [
            sys.executable,
            str(script),
            "ensure",
            "--project",
            str(root),
            "--agent-id",
            "cli-1",
            "--slug",
            "demo",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "WORKTREE=" in r.stdout
    assert "BRANCH=feature/demo" in r.stdout
