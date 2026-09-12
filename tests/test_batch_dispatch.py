import subprocess
from pathlib import Path

import batch_dispatch as bd
from plan_select import Worker


def _plan(
    path: Path,
    *,
    touch_points: list[str] | None,
    value: str = "medium",
    priority: str | None = None,
    preferred: str | None = "mid",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prio_line = f"- **Priority:** {priority}\n" if priority is not None else ""
    pref_line = f"- **Preferred models:** {preferred}\n" if preferred is not None else ""
    if touch_points is None:
        touch_section = ""
    elif not touch_points:
        touch_section = "## Likely touch points\n- not applicable\n\n"
    else:
        bullets = "\n".join(f"- `{tp}`" for tp in touch_points)
        touch_section = f"## Likely touch points\n{bullets}\n\n"
    path.write_text(
        f"# Plan: {path.stem}\n\n"
        f"- **Value:** {value}\n"
        f"{prio_line}"
        f"{pref_line}\n"
        f"{touch_section}"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def _tree(tmp_path: Path) -> Path:
    plans = tmp_path / ".plans"
    for lane in ("bugs", "features", "in-progress", "drafts", "completed", ".leases"):
        (plans / lane).mkdir(parents=True)
    return plans


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)


# --- parse_touch_points ------------------------------------------------

def test_parse_touch_points_strips_symbol_suffix():
    text = (
        "## Likely touch points\n"
        "- `scripts/foo.py: bar()` — why\n"
        "- `docs/x.md`\n\n"
        "## Progress\n"
    )
    tps = bd.parse_touch_points(text)
    paths = sorted(tp.path for tp in tps)
    assert paths == ["docs/x.md", "scripts/foo.py"]


def test_parse_touch_points_not_applicable_is_empty():
    text = "## Likely touch points\n- not applicable\n\n## Progress\n"
    assert bd.parse_touch_points(text) == []


def test_parse_touch_points_missing_section_is_empty():
    assert bd.parse_touch_points("## Goal\ng\n") == []


def test_parse_touch_points_directory_inferred_from_sibling():
    text = (
        "## Likely touch points\n"
        "- `docs/docs/tooling/`\n"
        "- `docs/docs/tooling/scripts.md`\n\n"
        "## Progress\n"
    )
    tps = {tp.path: tp.is_dir for tp in bd.parse_touch_points(text)}
    assert tps["docs/docs/tooling"] is True


# --- touch_points_overlap ------------------------------------------------

def test_overlap_exact_file_match():
    a = [bd.TouchPoint("scripts/plan_select.py", False)]
    b = [bd.TouchPoint("scripts/plan_select.py", False)]
    assert bd.touch_points_overlap(a, b) is not None


def test_overlap_dir_ancestor_match():
    a = [bd.TouchPoint("docs/docs/tooling", True)]
    b = [bd.TouchPoint("docs/docs/tooling/fleet-workers.md", False)]
    assert bd.touch_points_overlap(a, b) is not None


def test_no_overlap_distinct_files_same_dir_not_declared():
    a = [bd.TouchPoint("docs/docs/tooling/scripts.md", False)]
    b = [bd.TouchPoint("docs/docs/tooling/fleet-workers.md", False)]
    assert bd.touch_points_overlap(a, b) is None


# --- select_batch (Step 2 fixture: 6 ready plans) ------------------------

def test_select_batch_worked_example(tmp_path):
    plans = _tree(tmp_path)
    # Priority order A > B > C > D > E > F (all P1, filename tiebreak)
    _plan(plans / "features/planA.md", touch_points=["scripts/plan_select.py", "CHANGELOG.md"])
    _plan(plans / "features/planB.md", touch_points=["scripts/plan_select.py", "docs/docs/tooling/scripts.md"])
    _plan(plans / "features/planC.md", touch_points=["docs/docs/tooling/fleet-workers.md"])
    _plan(plans / "features/planD.md", touch_points=["docs/docs/tooling/fleet-workers.md", "CHANGELOG.md"])
    _plan(plans / "features/planE.md", touch_points=["scripts/release_progress.py", "tests/test_release_progress.py"])
    _plan(plans / "features/planF.md", touch_points=None)  # no section at all

    worker = Worker(name="unknown", tier="mid")
    result = bd.select_batch(plans, tmp_path, worker, max_n=10)

    selected_slugs = [c.record.slug for c in result.selected]
    # A conflicts with B (shared file); C conflicts with D (shared dir-declared file).
    # Greedy priority order keeps the first of each conflicting pair.
    assert "planA" in selected_slugs
    assert "planB" not in selected_slugs
    assert "planC" in selected_slugs
    assert "planD" not in selected_slugs
    assert "planE" in selected_slugs
    assert [r.slug for r in result.excluded_no_touch_map] == ["planF"]
    assert len(result.skipped_conflict) == 2


def test_select_batch_respects_max_cap(tmp_path):
    plans = _tree(tmp_path)
    for i in range(3):
        _plan(plans / f"features/plan{i}.md", touch_points=[f"scripts/independent{i}.py"])
    worker = Worker(name="unknown", tier="mid")
    result = bd.select_batch(plans, tmp_path, worker, max_n=2)
    assert len(result.selected) == 2


def test_select_batch_excludes_unmet_deps(tmp_path):
    plans = _tree(tmp_path)
    path = plans / "features/blocked.md"
    path.write_text(
        "# Plan: blocked\n\n- **Value:** medium\n- **Preferred models:** mid\n"
        "- **Depends on:** never-shipped\n\n"
        "## Likely touch points\n- `scripts/blocked.py`\n\n"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )
    worker = Worker(name="unknown", tier="mid")
    result = bd.select_batch(plans, tmp_path, worker, max_n=10)
    assert result.selected == []
    assert result.excluded_no_touch_map == []  # excluded via deps, not touch-map


# --- prepare_batch (Step 3 fixture: mid-batch claim race) ----------------

def test_prepare_batch_partial_success_on_claim_race(tmp_path):
    plans = _tree(tmp_path)
    _init_git(tmp_path)
    _plan(plans / "features/plan1.md", touch_points=["scripts/one.py"])
    _plan(plans / "features/plan2.md", touch_points=["scripts/two.py"])
    worker = Worker(name="unknown", tier="mid")
    result = bd.select_batch(plans, tmp_path, worker, max_n=10)
    assert len(result.selected) == 2

    # Simulate a lease race: pre-claim plan2 under a different agent before
    # prepare_batch gets to it.
    from plan_lease import claim_and_move
    claim_and_move(plans, "features/plan2.md", "someone-else")

    prep = bd.prepare_batch(tmp_path, plans, result.selected, agent_prefix="batch")
    by_slug = {p.slug: p for p in prep}
    assert by_slug["plan1"].ok is True
    assert by_slug["plan2"].ok is False
    assert "claim failed" in by_slug["plan2"].error
