from pathlib import Path

import check_plans


def _write_ready(path: Path, status: str = "ready") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Plan: t\n\n- **Status:** {status}\n\n"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n"
    )


def test_check_plans_ok_for_valid_tree(tmp_path):
    root = tmp_path
    (root / ".plans").mkdir()
    (root / ".plans" / "README.md").write_text("# plans\n")
    _write_ready(root / ".plans" / "features" / "foo.md")
    assert check_plans.check_plans(root) == []


def test_check_plans_flags_draft_status_outside_drafts(tmp_path):
    _write_ready(tmp_path / ".plans" / "features" / "bad.md", status="draft")
    problems = check_plans.check_plans(tmp_path)
    assert any("Status draft" in p for p in problems)


def test_check_plans_flags_missing_sections(tmp_path):
    p = tmp_path / ".plans" / "bugs" / "thin.md"
    p.parent.mkdir(parents=True)
    p.write_text("# Plan: thin\n\n## Goal\nonly goal\n")
    problems = check_plans.check_plans(tmp_path)
    assert any("## Steps" in p for p in problems)
    assert any("## Done when" in p for p in problems)


def test_check_plans_flags_todo_lane(tmp_path):
    (tmp_path / ".plans" / "todo").mkdir(parents=True)
    problems = check_plans.check_plans(tmp_path)
    assert any("todo" in p for p in problems)
