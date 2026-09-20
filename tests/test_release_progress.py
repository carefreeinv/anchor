from pathlib import Path

from release_progress import parse_release_field, scan_releases


def _plan(path: Path, *, release: str | None = None, title: str = "t") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rel_line = f"- **Release:** {release}\n" if release is not None else ""
    path.write_text(
        f"# Plan: {title}\n\n"
        "- **Value:** medium\n"
        "- **Priority:** P2\n"
        "- **Preferred models:** mid\n"
        f"{rel_line}\n"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def _release_file(path: Path, *, status: str = "open", target: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_line = f"- **Target:** {target}\n" if target is not None else ""
    path.write_text(
        f"# Release: {path.stem}\n\n"
        f"- **Status:** {status}\n"
        f"{target_line}",
        encoding="utf-8",
    )


def _tree(tmp_path: Path) -> Path:
    plans = tmp_path / ".plans"
    for lane in ("bugs", "features", "in-progress", "drafts", "completed"):
        (plans / lane).mkdir(parents=True)
    return plans


def test_parse_release_field_accepts_slug_rejects_prose():
    assert parse_release_field("- **Release:** v0.3.0\n") == "v0.3.0"
    assert parse_release_field("- **Release:** none\n") is None
    assert parse_release_field("no field here") is None
    # A pre-existing, unrelated convention: "Release:" cited as a changelog
    # link in prose, not this plan-header field — must not be misparsed.
    assert parse_release_field("- **Release:** [Introducing Foo](https://x) — note\n") is None


def test_release_with_no_file_reports_unknown(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "a.md", release="ghost-release")
    releases = scan_releases(plans)
    info = releases["ghost-release"]
    assert info.file_exists is False
    assert info.total == 1
    assert info.is_complete is False  # never "complete" without a real file


def test_release_file_with_zero_members_is_not_complete(tmp_path):
    plans = _tree(tmp_path)
    _release_file(plans / ".releases" / "empty.md")
    releases = scan_releases(plans)
    info = releases["empty"]
    assert info.file_exists is True
    assert info.total == 0
    assert info.is_complete is False  # empty set is "doesn't exist," not "100% done"


def test_completion_fraction_from_plan_headers_only_no_static_list(tmp_path):
    plans = _tree(tmp_path)
    _release_file(plans / ".releases" / "v1.md", status="open")
    # 3 plans point at v1; 2 completed, 1 still in features/. The release file
    # itself lists no members — membership is entirely derived from scanning.
    _plan(plans / "completed" / "one.md", release="v1")
    _plan(plans / "completed" / "two.md", release="v1")
    _plan(plans / "features" / "three.md", release="v1")
    releases = scan_releases(plans)
    info = releases["v1"]
    assert info.total == 3
    assert info.completed == 2
    assert [m.rel for m in info.remaining] == ["features/three.md"]
    assert info.is_complete is False


def test_release_is_complete_only_when_every_member_is_completed(tmp_path):
    plans = _tree(tmp_path)
    _release_file(plans / ".releases" / "v2.md", status="open")
    _plan(plans / "completed" / "one.md", release="v2")
    _plan(plans / "completed" / "two.md", release="v2")
    releases = scan_releases(plans)
    info = releases["v2"]
    assert info.total == 2
    assert info.completed == 2
    assert info.is_complete is True


def test_plans_with_no_release_header_are_ignored(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "untagged.md")  # no Release: line at all
    releases = scan_releases(plans)
    assert releases == {}


def test_target_and_status_read_from_release_file(tmp_path):
    plans = _tree(tmp_path)
    _release_file(plans / ".releases" / "v3.md", status="ready", target="v3.0.0")
    releases = scan_releases(plans)
    info = releases["v3"]
    assert info.status == "ready"
    assert info.target == "v3.0.0"


def test_invalid_status_falls_back_to_open(tmp_path):
    plans = _tree(tmp_path)
    _release_file(plans / ".releases" / "v4.md", status="banana")
    releases = scan_releases(plans)
    assert releases["v4"].status == "open"


def test_set_status_rewrites_in_place_preserving_surrounding_lines(tmp_path):
    from release_progress import set_status

    plans = _tree(tmp_path)
    path = plans / ".releases" / "v5.md"
    _release_file(path, status="open")
    before = path.read_text(encoding="utf-8")
    assert "\n\n- **Status:** open\n" in before  # blank line before the field

    ok = set_status(plans, "v5", "ready")
    assert ok is True

    after = path.read_text(encoding="utf-8")
    assert "\n\n- **Status:** ready\n" in after  # blank line survives the rewrite
    assert "open" not in after


def test_set_status_rejects_invalid_status(tmp_path):
    from release_progress import set_status

    plans = _tree(tmp_path)
    _release_file(plans / ".releases" / "v6.md", status="open")
    assert set_status(plans, "v6", "bogus") is False


def test_set_status_false_when_release_file_missing(tmp_path):
    from release_progress import set_status

    plans = _tree(tmp_path)
    assert set_status(plans, "does-not-exist", "ready") is False


def test_reconcile_reopen_flips_ready_back_to_open_on_new_incomplete_member(tmp_path):
    from release_progress import reconcile_reopen

    plans = _tree(tmp_path)
    _release_file(plans / ".releases" / "r1.md", status="ready")
    _plan(plans / "completed" / "done.md", release="r1")
    _plan(plans / "features" / "new.md", release="r1")  # joined after "ready"

    releases = scan_releases(plans)
    assert releases["r1"].status == "ready"  # file still says ready before reconcile

    reopened = reconcile_reopen(plans, releases)
    assert reopened == ["r1"]
    assert releases["r1"].status == "open"  # in-memory info updated too

    # Persisted to disk.
    releases_after = scan_releases(plans)
    assert releases_after["r1"].status == "open"


def test_reconcile_reopen_leaves_complete_ready_release_alone(tmp_path):
    from release_progress import reconcile_reopen

    plans = _tree(tmp_path)
    _release_file(plans / ".releases" / "r2.md", status="ready")
    _plan(plans / "completed" / "done.md", release="r2")

    releases = scan_releases(plans)
    reopened = reconcile_reopen(plans, releases)
    assert reopened == []
    assert releases["r2"].status == "ready"
