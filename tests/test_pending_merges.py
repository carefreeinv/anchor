"""Tests for scripts/pending_merges.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pending_merges import (
    completed_slugs,
    find_pending,
    format_brief,
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


# --- worktree / plan-state joins ---------------------------------------------
# "Which branch is ahead" is only half the answer; the other half is where the
# work physically sits and whether anyone is still holding it.


@pytest.fixture
def repo_with_feature(git_repo: Path) -> Path:
    _git(git_repo, "checkout", "-b", "dev")
    _git(git_repo, "checkout", "-b", "feature/cool-thing")
    _commit(git_repo, "f.txt")
    _git(git_repo, "checkout", "dev")
    return git_repo


def _plan(root: Path, lane: str, name: str, body: str = "# plan\n") -> Path:
    lane_dir = root / ".plans" / lane
    lane_dir.mkdir(parents=True, exist_ok=True)
    path = lane_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def test_worktree_path_is_joined_onto_the_branch(repo_with_feature: Path, tmp_path: Path):
    tree = tmp_path / "wt"
    _git(repo_with_feature, "worktree", "add", str(tree), "feature/cool-thing")

    feat = next(p for p in find_pending(repo_with_feature) if p.branch == "feature/cool-thing")

    assert feat.worktree is not None
    assert Path(feat.worktree).name == "wt"
    assert feat.stale_registry is False


def test_dirty_worktree_is_flagged(repo_with_feature: Path, tmp_path: Path):
    tree = tmp_path / "wt"
    _git(repo_with_feature, "worktree", "add", str(tree), "feature/cool-thing")
    (tree / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")

    feat = next(p for p in find_pending(repo_with_feature) if p.branch == "feature/cool-thing")

    assert feat.dirty is True
    assert "worktree dirty" in format_report(find_pending(repo_with_feature))


def test_plan_lane_is_reported_from_wherever_the_plan_lives(repo_with_feature: Path):
    _plan(repo_with_feature, "review-needed", "cool-thing.local.md")

    feat = next(p for p in find_pending(repo_with_feature) if p.branch == "feature/cool-thing")

    assert feat.plan_lane == "review-needed"
    assert feat.completed_plan is False  # lane is reported, not assumed to be completed


def test_held_plan_is_detected_from_its_handoff_note(repo_with_feature: Path):
    _plan(repo_with_feature, "review-needed", "cool-thing.md",
          "# plan\n\n## Handoff\n\nhold — waiting on staging data — 2026-08-01\n")

    pending = find_pending(repo_with_feature)
    feat = next(p for p in pending if p.branch == "feature/cool-thing")

    assert feat.held is True
    assert "held for testing" in format_report(pending)
    assert "1 held" in format_brief(pending)


def test_handoff_note_without_a_hold_is_not_held(repo_with_feature: Path):
    _plan(repo_with_feature, "completed", "cool-thing.md",
          "# plan\n\n## Handoff\n\nmerged to dev by /work 2026-08-01 — no /review sign-off\n")

    feat = next(p for p in find_pending(repo_with_feature) if p.branch == "feature/cool-thing")

    assert feat.held is False


def test_registry_only_worktree_is_reported_and_labeled_stale(repo_with_feature: Path,
                                                              tmp_path: Path):
    """Git is the authority; a registry entry git does not know about is labeled."""
    reg = repo_with_feature / "var" / "worktrees"
    reg.mkdir(parents=True)
    (reg / "registry.json").write_text(
        '{"agents": {"a1": {"agent_id": "a1", "path": "/gone/wt", '
        '"branch": "feature/cool-thing", "integration": "dev", "project": "p"}}}\n',
        encoding="utf-8",
    )

    pending = find_pending(repo_with_feature)
    feat = next(p for p in pending if p.branch == "feature/cool-thing")

    assert feat.worktree == "/gone/wt"
    assert feat.stale_registry is True
    assert feat.dirty is False  # never probed — the path is not a live worktree
    assert "stale registry" in format_report(pending)


def test_missing_worktrees_dir_is_not_an_error(repo_with_feature: Path):
    assert not (repo_with_feature / "var" / "worktrees").exists()

    feat = next(p for p in find_pending(repo_with_feature) if p.branch == "feature/cool-thing")

    assert feat.worktree is None
    assert feat.stale_registry is False


def test_no_worktrees_flag_skips_the_join(repo_with_feature: Path, tmp_path: Path):
    tree = tmp_path / "wt"
    _git(repo_with_feature, "worktree", "add", str(tree), "feature/cool-thing")

    feat = next(p for p in find_pending(repo_with_feature, worktrees=False)
                if p.branch == "feature/cool-thing")

    assert feat.worktree is None


def test_brief_is_exactly_one_line(repo_with_feature: Path):
    brief = format_brief(find_pending(repo_with_feature))

    assert "\n" not in brief
    assert "1 branch(es) ahead of dev" in brief


def test_brief_on_a_clean_repo_says_nothing_unmerged(git_repo: Path):
    assert "nothing unmerged" in format_brief(find_pending(git_repo))


def test_json_keeps_every_pre_existing_field(repo_with_feature: Path):
    """The JSON contract is additive — existing consumers must not break."""
    import json as _json

    script = REPO / "scripts" / "pending_merges.py"
    r = subprocess.run(
        [sys.executable, str(script), "--root", str(repo_with_feature), "--json"],
        capture_output=True, text=True, check=False,
    )
    rows = _json.loads(r.stdout)

    assert {"branch", "target", "ahead", "plan_slug", "completed_plan"} <= set(rows[0])
    assert {"worktree", "dirty", "plan_lane", "held", "stale_registry"} <= set(rows[0])


def test_cli_brief_prints_one_line(repo_with_feature: Path):
    script = REPO / "scripts" / "pending_merges.py"
    r = subprocess.run(
        [sys.executable, str(script), "--root", str(repo_with_feature), "--brief"],
        capture_output=True, text=True, check=False,
    )

    assert r.returncode == 0
    assert len(r.stdout.strip().splitlines()) == 1
