"""commit_lane_move outcomes: committed / untracked / refused."""
from __future__ import annotations

import subprocess
from pathlib import Path

import anchor_ops as ops
from test_anchor_cli import cli, write


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _tracked_plans(git_repo: Path) -> Path:
    for lane in ("bugs", "features", "in-progress", "review-needed", "drafts",
                 "completed", "ambiguous", "blocked"):
        (git_repo / ".plans" / lane).mkdir(parents=True)
    write(git_repo, "features", "f1")
    _git(git_repo, "add", ".plans")
    _git(git_repo, "commit", "-m", "seed plans")
    return git_repo


def test_commit_lane_move_untracked_when_ignored(git_repo: Path):
    (git_repo / ".gitignore").write_text(".plans/\n", encoding="utf-8")
    _git(git_repo, "add", ".gitignore")
    _git(git_repo, "commit", "-m", "ignore")
    write(git_repo, "features", "f1")
    out = ops.commit_lane_move(git_repo, "f1", "review-needed", "anchor work --finish")
    assert out["outcome"] == "untracked"


def test_commit_lane_move_untracked_outside_git(tmp_path: Path):
    write(tmp_path, "features", "f1")
    out = ops.commit_lane_move(tmp_path, "f1", "review-needed", "why")
    assert out["outcome"] == "untracked"


def test_commit_lane_move_committed(git_repo: Path):
    root = _tracked_plans(git_repo)
    src = root / ".plans/features/f1.md"
    dst = root / ".plans/review-needed/f1.md"
    src.rename(dst)
    before = _git(root, "rev-parse", "HEAD")
    out = ops.commit_lane_move(root, "f1", "review-needed", "anchor work --finish")
    assert out["outcome"] == "committed"
    assert out["message"] == "Plans: f1 → review-needed (anchor work --finish)"
    assert out["sha"] != before
    assert _git(root, "status", "--porcelain") == ""
    assert _git(root, "log", "-1", "--format=%s") == out["message"]


def test_commit_lane_move_refuses_merge_in_progress(git_repo: Path):
    root = _tracked_plans(git_repo)
    _git(root, "checkout", "-b", "other")
    (root / "other.txt").write_text("o\n", encoding="utf-8")
    _git(root, "add", "other.txt")
    _git(root, "commit", "-m", "other")
    _git(root, "checkout", "main")
    subprocess.run(
        ["git", "-C", str(root), "merge", "--no-ff", "--no-commit", "other"],
        check=True, capture_output=True, text=True,
    )
    (root / ".plans/features/f1.md").rename(root / ".plans/review-needed/f1.md")
    out = ops.commit_lane_move(root, "f1", "review-needed", "why")
    assert out["outcome"] == "refused-merge-in-progress"
    assert "f1.md" in _git(root, "status", "--porcelain")


def test_commit_lane_move_refuses_foreign_staged(git_repo: Path):
    root = _tracked_plans(git_repo)
    (root / "other.txt").write_text("o\n", encoding="utf-8")
    _git(root, "add", "other.txt")
    (root / ".plans/features/f1.md").rename(root / ".plans/review-needed/f1.md")
    out = ops.commit_lane_move(root, "f1", "review-needed", "why")
    assert out["outcome"] == "refused-foreign-staged"
    assert "other.txt" in out["paths"]
    log = _git(root, "log", "-1", "--format=%s")
    assert log == "seed plans"


def test_work_claim_commits_on_tracked_plans(git_repo: Path):
    root = _tracked_plans(git_repo)
    code, doc = cli(["work", "f1", "--root", str(root), "--agent-id", "a1", "--no-fit-check"])
    assert code == 0, doc
    assert doc["result"]["lane_commit"]["outcome"] == "committed"
    assert doc["result"]["lane_commit"]["message"] == (
        "Plans: f1 → in-progress (anchor work claim)"
    )
    assert _git(root, "status", "--porcelain") == ""
    assert _git(root, "log", "-1", "--format=%s") == (
        "Plans: f1 → in-progress (anchor work claim)"
    )
    assert (root / ".plans/in-progress/f1.md").is_file()


def test_work_finish_then_review_approve_on_tracked_plans(git_repo: Path):
    root = _tracked_plans(git_repo)
    _git(root, "branch", "dev")
    _git(root, "checkout", "-b", "feature/f1", "dev")
    (root / "thing.txt").write_text("x\n", encoding="utf-8")
    _git(root, "add", "thing.txt")
    _git(root, "commit", "-m", "f1 work")
    code, doc = cli(["work", "f1", "--root", str(root), "--agent-id", "a1", "--no-fit-check"])
    assert code == 0, doc
    code, doc = cli(["work", "--finish", "f1", "--root", str(root), "--agent-id", "a1"])
    assert code == 0, doc
    assert doc["result"]["lane_commit"]["outcome"] == "committed"
    assert _git(root, "status", "--porcelain") == ""
    code, doc = cli(
        ["review", "f1", "--root", str(root), "--json"],
        interactive=True, answers=["approve"],
    )
    assert code == 0, doc
    assert doc["result"]["lane_commit"]["outcome"] == "committed"
    assert (root / ".plans/completed/f1.md").is_file()
    assert _git(root, "status", "--porcelain") == ""
    assert doc["result"]["merge"]["ok"]
    assert _git(root, "log", "-1", "--format=%s") == (
        "Plans: f1 → completed (anchor review approve)"
    )
