from pathlib import Path

from plan_select import (
    Worker,
    evaluate_dependencies,
    inventory_all_plan_summaries,
    parse_depends_on,
    select_one,
)


def _write(path: Path, *, slug: str, goal: str, depends: str = "none") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Plan: {slug}\n\n"
        f"- **Slug:** {slug}\n"
        f"- **Preferred models:** mid\n"
        f"- **Depends on:** {depends}\n\n"
        f"## Goal\n{goal}\n\n"
        "## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def _tree(tmp_path: Path) -> Path:
    plans = tmp_path / ".plans"
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


def test_parse_depends_on_header_and_section():
    text = (
        "- **Depends on:** foo, `bar`\n\n"
        "## Depends on (detail)\n"
        "- `baz` — needs API\n"
        "- none should not appear as slug from header alone\n"
    )
    # header wins first tokens; section adds baz
    deps = parse_depends_on(text)
    assert "foo" in deps and "bar" in deps and "baz" in deps


def test_parse_depends_none():
    assert parse_depends_on("- **Depends on:** none\n") == []
    assert parse_depends_on("- **Depends on:** n/a\n") == []


def test_unmet_when_dependency_still_open(tmp_path):
    plans = _tree(tmp_path)
    _write(plans / "features" / "base.md", slug="base", goal="Build base API")
    _write(
        plans / "features" / "app.md",
        slug="app",
        goal="App on base",
        depends="base",
    )
    met, unmet, notes = evaluate_dependencies(plans, ["base"], git_check=False)
    assert met is False
    assert unmet == ("base",)
    assert any("still open" in n for n in notes)

    worker = Worker("t", "mid")
    # only app depends; base is free — base may sort after/before; app must not win if both fit
    # base has no deps so can be picked; ensure app is never selected while base open
    for _ in range(5):
        p = select_one(plans, worker, no_dep_check=False)
        if p is None:
            break
        assert p.slug != "app" or p.deps_met
        if p.slug == "base":
            break


def test_met_when_in_completed(tmp_path):
    plans = _tree(tmp_path)
    _write(plans / "completed" / "base.md", slug="base", goal="done base")
    _write(
        plans / "features" / "app.md",
        slug="app",
        goal="App on base",
        depends="base",
    )
    met, unmet, _ = evaluate_dependencies(plans, ["base"], git_check=False)
    assert met is True
    assert unmet == ()
    picked = select_one(plans, Worker("t", "mid"))
    assert picked is not None
    assert picked.slug == "app"
    assert picked.deps_met is True


def test_inventory_summaries_for_coordinator(tmp_path):
    plans = _tree(tmp_path)
    _write(plans / "drafts" / "a.md", slug="a", goal="Alpha work")
    _write(plans / "features" / "b.md", slug="b", goal="Beta work", depends="a")
    rows = inventory_all_plan_summaries(plans)
    slugs = {r["slug"] for r in rows}
    assert "a" in slugs and "b" in slugs
    b = next(r for r in rows if r["slug"] == "b")
    assert "a" in b["depends_on"]
