import subprocess
from pathlib import Path

import plan_finish_gate as gate


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-b", "dev")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "scripts").mkdir()
    (root / "scripts" / "work_once.py").write_text("x\n", encoding="utf-8")
    (root / ".plans" / "in-progress").mkdir(parents=True)
    plan = root / ".plans" / "in-progress" / "demo.md"
    plan.write_text(
        "# Plan\n\n## Steps\n"
        "| # | Task | Touches | Verify by | Route to |\n"
        "| 1 | x | `scripts/work_once.py` | t | mid |\n",
        encoding="utf-8",
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    return root


def test_plan_only_commit_fails(tmp_path):
    root = _repo(tmp_path)
    plan = root / ".plans" / "in-progress" / "demo.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "\n- [x] Step 1\n", encoding="utf-8")
    _git(root, "add", ".plans")
    _git(root, "commit", "-m", "checkbox")
    g = gate.check_finish(root, plan, since_ref="HEAD~1")
    assert not g.ok
    assert "plan-only" in g.reason


def test_touches_path_commit_passes(tmp_path):
    root = _repo(tmp_path)
    plan = root / ".plans" / "in-progress" / "demo.md"
    (root / "scripts" / "work_once.py").write_text("y\n", encoding="utf-8")
    _git(root, "add", "scripts/work_once.py")
    _git(root, "commit", "-m", "real")
    g = gate.check_finish(root, plan, since_ref="HEAD~1")
    assert g.ok
    assert "scripts/work_once.py" in g.changed


def test_missing_since_fails_closed(tmp_path):
    root = _repo(tmp_path)
    plan = root / ".plans" / "in-progress" / "demo.md"
    g = gate.check_finish(root, plan, since_ref="does-not-exist")
    assert not g.ok
    assert "fail closed" in g.reason


def test_infer_finish_git_dir_uses_linked_worktree(tmp_path):
    root = _repo(tmp_path)
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-b", "feature/demo", str(wt), "dev")
    (wt / "scripts" / "work_once.py").write_text("from-wt\n", encoding="utf-8")
    _git(wt, "add", "scripts/work_once.py")
    _git(wt, "commit", "-m", "on worktree")
    plan = root / ".plans" / "in-progress" / "demo.md"
    assert not gate.check_finish(root, plan).ok
    git_dir = gate.infer_finish_git_dir(root, "demo")
    assert git_dir == wt.resolve()
    assert gate.check_finish(git_dir, plan).ok


def test_no_git_skips_evidence(tmp_path):
    d = tmp_path / "nogit"
    d.mkdir()
    p = d / "p.md"
    p.write_text("# x\n", encoding="utf-8")
    g = gate.check_finish(d, p)
    assert g.ok
    assert "no git" in g.reason
