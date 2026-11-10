"""commit_prep after --run: green commit, red no-commit, --no-commit skip."""
from __future__ import annotations

import subprocess
from pathlib import Path

import commit_prep
import work_once


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _plan(root: Path) -> Path:
    p = root / ".plans" / "in-progress" / "a.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# Plan: t\n\n## Goal\nFix the widget.\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )
    return p


def test_commit_on_feature_when_dirty(git_repo: Path):
    _git(git_repo, "checkout", "-b", "feature/a")
    (git_repo / "widget.py").write_text("x = 1\n", encoding="utf-8")
    r = commit_prep.commit_on_feature(git_repo, "a", "Fix the widget.")
    assert r.ok, r.error
    assert r.sha
    assert _git(git_repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/a"
    assert "widget.py" in _git(git_repo, "show", "--name-only", "--pretty=")
    assert _git(git_repo, "log", "-1", "--format=%s") == "Fix the widget."


def test_red_prep_does_not_commit(git_repo: Path):
    _git(git_repo, "checkout", "-b", "feature/a")
    tests = git_repo / "tests"
    tests.mkdir()
    (tests / "test_fail.py").write_text("def test_no():\n    assert False\n", encoding="utf-8")
    (git_repo / "widget.py").write_text("x = 1\n", encoding="utf-8")
    before = _git(git_repo, "rev-parse", "HEAD")
    r = commit_prep.commit_on_feature(git_repo, "a", "Fix the widget.")
    assert not r.ok
    assert _git(git_repo, "rev-parse", "HEAD") == before
    assert "widget.py" in commit_prep.dirty_paths(git_repo)


def test_no_commit_skips(git_repo: Path):
    _git(git_repo, "checkout", "-b", "feature/a")
    (git_repo / "widget.py").write_text("x = 1\n", encoding="utf-8")
    r = commit_prep.commit_on_feature(
        git_repo, "a", "Fix the widget.", no_commit=True,
    )
    assert r.ok
    assert r.sha is None
    assert "widget.py" in commit_prep.dirty_paths(git_repo)


def test_refuses_protected_branch(git_repo: Path):
    (git_repo / "widget.py").write_text("x = 1\n", encoding="utf-8")
    r = commit_prep.commit_on_feature(git_repo, "a", "nope")
    assert not r.ok
    assert "protected" in (r.error or "")


def test_work_once_run_commits_then_finishes(git_repo: Path, monkeypatch):
    root = git_repo
    for lane in ("bugs", "features", "in-progress", "review-needed", "drafts",
                 "completed", "ambiguous", "blocked"):
        (root / ".plans" / lane).mkdir(parents=True, exist_ok=True)
    (root / ".plans" / "features" / "a.md").write_text(
        "# Plan: t\n\n- **Value:** high\n- **Preferred models:** mid\n\n"
        "## Goal\nFix the widget.\n",
        encoding="utf-8",
    )
    _git(root, "checkout", "-b", "feature/a")

    def fake_run(plan_path, extra):
        wt = Path(extra[extra.index("--worktree") + 1]) if "--worktree" in extra else root
        (wt / "widget.py").write_text("x = 1\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(work_once, "run_orchestrate", fake_run)
    monkeypatch.setattr(
        work_once,
        "orchestrate_worktree_args",
        lambda *a, **k: ["--worktree", str(root)],
    )
    code = work_once.main([
        "--root", str(root), "--once", "--slug", "a", "--run",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 0
    assert (root / ".plans" / "review-needed" / "a.md").is_file()
    assert "widget.py" in _git(root, "show", "--name-only", "--pretty=")
    assert _git(root, "log", "-1", "--format=%s") == "Fix the widget."


def test_work_once_red_prep_stays_in_progress(git_repo: Path, monkeypatch):
    root = git_repo
    for lane in ("bugs", "features", "in-progress", "review-needed", "drafts",
                 "completed", "ambiguous", "blocked"):
        (root / ".plans" / lane).mkdir(parents=True, exist_ok=True)
    (root / ".plans" / "features" / "a.md").write_text(
        "# Plan: t\n\n- **Preferred models:** mid\n\n## Goal\nFix the widget.\n",
        encoding="utf-8",
    )
    _git(root, "checkout", "-b", "feature/a")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_fail.py").write_text("def test_no():\n    assert False\n", encoding="utf-8")

    def fake_run(plan_path, extra):
        (root / "widget.py").write_text("x = 1\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(work_once, "run_orchestrate", fake_run)
    monkeypatch.setattr(
        work_once,
        "orchestrate_worktree_args",
        lambda *a, **k: ["--worktree", str(root)],
    )
    code = work_once.main([
        "--root", str(root), "--once", "--slug", "a", "--run",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 2
    assert (root / ".plans" / "in-progress" / "a.md").is_file()
    assert not (root / ".plans" / "review-needed" / "a.md").is_file()
    assert "widget.py" in commit_prep.dirty_paths(root)


def test_work_once_no_commit_still_finishes(git_repo: Path, monkeypatch):
    root = git_repo
    for lane in ("bugs", "features", "in-progress", "review-needed", "drafts",
                 "completed", "ambiguous", "blocked"):
        (root / ".plans" / lane).mkdir(parents=True, exist_ok=True)
    (root / ".plans" / "features" / "a.md").write_text(
        "# Plan: t\n\n- **Preferred models:** mid\n\n## Goal\nFix the widget.\n",
        encoding="utf-8",
    )
    _git(root, "checkout", "-b", "feature/a")

    def fake_run(plan_path, extra):
        (root / "widget.py").write_text("x = 1\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(work_once, "run_orchestrate", fake_run)
    monkeypatch.setattr(
        work_once,
        "orchestrate_worktree_args",
        lambda *a, **k: ["--worktree", str(root)],
    )
    code = work_once.main([
        "--root", str(root), "--once", "--slug", "a", "--run", "--no-commit",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 0
    # no-empty-work-to-review-needed: apply-only (no SHA) stays in-progress/
    assert (root / ".plans" / "in-progress" / "a.md").is_file()
    assert not (root / ".plans" / "review-needed" / "a.md").is_file()
    assert "widget.py" in commit_prep.dirty_paths(root)
