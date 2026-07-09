"""Tests for scripts/pending_merges.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pending_merges import (
    completed_slugs,
    find_pending,
    format_report,
    merge_target,
)

REPO = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A fresh git repo with one committed file (README) on branch main.

    Defined locally so this test file is self-contained across independent
    feature branches (a shared conftest fixture may not exist yet on dev).
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README").write_text("hi\n", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")
    _git(root, "branch", "-M", "main")
    return root


def _commit(root: Path, name: str, content: str = "x") -> None:
    (root / name).write_text(content, encoding="utf-8")
    _git(root, "add", name)
    _git(root, "commit", "-m", f"add {name}")


def test_merge_target_routing():
    branches = {"main", "dev", "feature/x"}
    assert merge_target("feature/x", branches) == "dev"
    assert merge_target("dev", branches) == "main"
    assert merge_target("main", branches) is None
    # no dev → feature targets main
    assert merge_target("feature/x", {"main", "feature/x"}) == "main"


def test_find_pending_feature_and_dev(git_repo: Path):
    # dev ahead of main
    _git(git_repo, "checkout", "-b", "dev")
    _commit(git_repo, "dev1.txt")
    # feature ahead of dev
    _git(git_repo, "checkout", "-b", "feature/cool-thing")
    _commit(git_repo, "feat1.txt")
    _git(git_repo, "checkout", "dev")

    pending = find_pending(git_repo)
    by_branch = {p.branch: p for p in pending}

    assert "feature/cool-thing" in by_branch
    assert by_branch["feature/cool-thing"].target == "dev"
    assert by_branch["feature/cool-thing"].ahead == 1

    assert "dev" in by_branch
    assert by_branch["dev"].target == "main"
    assert by_branch["dev"].ahead == 1


def test_merged_branch_not_reported(git_repo: Path):
    _git(git_repo, "checkout", "-b", "dev")
    _git(git_repo, "checkout", "-b", "feature/done")
    _commit(git_repo, "f.txt")
    # merge it into dev → no longer pending
    _git(git_repo, "checkout", "dev")
    _git(git_repo, "merge", "--no-ff", "feature/done", "-m", "merge")

    pending = find_pending(git_repo)
    branches = {p.branch for p in pending}
    assert "feature/done" not in branches  # fully merged


def test_completed_plan_flagged(git_repo: Path):
    comp = git_repo / ".plans" / "completed"
    comp.mkdir(parents=True)
    (comp / "2026-07-09-cool-thing.md").write_text("# plan\n", encoding="utf-8")

    _git(git_repo, "checkout", "-b", "dev")
    _git(git_repo, "checkout", "-b", "feature/cool-thing")
    _commit(git_repo, "f.txt")
    _git(git_repo, "checkout", "dev")

    pending = find_pending(git_repo)
    feat = next(p for p in pending if p.branch == "feature/cool-thing")
    assert feat.completed_plan is True
    assert feat.plan_slug == "cool-thing"
    assert "awaiting merge" in format_report(pending)


def test_completed_slugs_strips_date_and_local(git_repo: Path):
    comp = git_repo / ".plans" / "completed"
    comp.mkdir(parents=True)
    (comp / "2026-07-09-alpha.md").write_text("x", encoding="utf-8")
    (comp / "beta.local.md").write_text("x", encoding="utf-8")
    (comp / "README.md").write_text("x", encoding="utf-8")
    assert completed_slugs(git_repo) == {"alpha", "beta"}


def test_clean_repo_reports_nothing(git_repo: Path):
    assert find_pending(git_repo) == []
    assert "nothing pending" in format_report([])


def test_cli_json(git_repo: Path):
    _git(git_repo, "checkout", "-b", "dev")
    _git(git_repo, "checkout", "-b", "feature/x")
    _commit(git_repo, "f.txt")
    script = REPO / "scripts" / "pending_merges.py"
    r = subprocess.run(
        [sys.executable, str(script), "--root", str(git_repo), "--json", "--exit-code"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1  # pending exists
    assert "feature/x" in r.stdout
