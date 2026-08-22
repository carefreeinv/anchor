import datetime
import os
import subprocess
import sys
from pathlib import Path

import plan_board as pb


def _plan(path: Path, *, value: str = "medium", priority: str | None = None, title: str = "t") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prio_line = f"- **Priority:** {priority}\n" if priority is not None else ""
    path.write_text(
        f"# Plan: {title}\n\n"
        f"- **Value:** {value}\n"
        f"{prio_line}"
        "- **Preferred models:** mid\n\n"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def _tree(tmp_path: Path) -> Path:
    plans = tmp_path / ".plans"
    for lane in (
        "drafts",
        "bugs",
        "features",
        "in-progress",
        "review-needed",
        "completed",
        "ambiguous",
        "blocked",
    ):
        (plans / lane).mkdir(parents=True)
    return plans


def _git(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True, env=env
    )


def _git_repo(tmp_path: Path) -> None:
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)


def _commit_file(tmp_path: Path, rel: str, when_iso: str) -> None:
    env = dict(os.environ)
    env["GIT_AUTHOR_DATE"] = when_iso
    env["GIT_COMMITTER_DATE"] = when_iso
    _git("add", rel, cwd=tmp_path)
    _git("commit", "-q", "-m", f"add {rel}", cwd=tmp_path, env=env)


# --- Column membership + sort order (Steps 1-2) ---------------------------


def test_build_columns_five_default_lanes(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "drafts" / "d.md")
    _plan(plans / "bugs" / "b.md")
    _plan(plans / "features" / "f.md")
    _plan(plans / "in-progress" / "ip.md")
    _plan(plans / "review-needed" / "rn.md")
    _plan(plans / "completed" / "c.md")

    columns = pb.build_columns(plans, include_parked=False)
    names = [name for name, _ in columns]
    assert names == ["Drafts", "Ready", "In Progress", "Review Needed", "Completed"]

    by_name = dict(columns)
    assert [r.slug for r in by_name["Drafts"]] == ["d"]
    assert {r.slug for r in by_name["Ready"]} == {"b", "f"}
    assert [r.slug for r in by_name["In Progress"]] == ["ip"]
    assert [r.slug for r in by_name["Review Needed"]] == ["rn"]
    assert [r.slug for r in by_name["Completed"]] == ["c"]


def test_include_parked_adds_two_columns(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "ambiguous" / "a.md")
    _plan(plans / "blocked" / "bl.md")

    without = pb.build_columns(plans, include_parked=False)
    assert len(without) == 5

    with_parked = pb.build_columns(plans, include_parked=True)
    assert len(with_parked) == 7
    names = [name for name, _ in with_parked]
    assert names[-2:] == ["Ambiguous", "Blocked"]


def test_ready_column_sorts_bugs_before_features_then_priority_value(tmp_path):
    plans = _tree(tmp_path)
    # Higher Value/Priority feature should still rank after any bug.
    _plan(plans / "features" / "high.md", value="high", priority="P1", title="feature high")
    _plan(plans / "bugs" / "low.md", value="low", priority="P3", title="bug low")
    _plan(plans / "features" / "low.md", value="low", priority="P2", title="feature low")
    _plan(plans / "features" / "hi2.md", value="high", priority="P2", title="feature hi2")

    columns = pb.build_columns(plans, include_parked=False)
    ready = dict(columns)["Ready"]
    slugs = [r.slug for r in ready]
    assert slugs[0] == "low"  # only bug, always first regardless of P3/low
    # remaining features ordered by Priority then Value
    assert slugs[1:] == ["high", "hi2", "low"]


# --- Log parsing + per-card labels (Step 6) --------------------------------


def _write_log(plans: Path, name: str, row: list[str]) -> Path:
    logs = plans / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / name
    path.write_text(",".join(row) + "\n", encoding="utf-8")
    return path


def test_latest_event_label_picks_most_recent_by_content_timestamp(tmp_path):
    plans = _tree(tmp_path)
    _write_log(
        plans,
        "1.local.csv",
        [
            "2026-07-01T00:00:00+00:00",
            "foo",
            "entered-review-needed",
            "in-progress",
            "review-needed",
        ],
    )
    _write_log(
        plans, "2.local.csv", ["2026-07-05T00:00:00+00:00", "foo", "entered-completed", "review-needed", "completed"]
    )
    events = pb.load_log_events(plans)
    latest = pb.latest_events_by_slug(events)
    assert latest["foo"].event == "entered-completed"
    assert pb.humanize_event(latest["foo"].event) == "Completed"


def test_unrecognized_event_falls_back_to_title_case(tmp_path):
    plans = _tree(tmp_path)
    _write_log(plans, "1.local.csv", ["2026-07-01T00:00:00+00:00", "foo", "sent-back-for-changes"])
    events = pb.load_log_events(plans)
    latest = pb.latest_events_by_slug(events)
    assert pb.humanize_event(latest["foo"].event) == "Sent Back For Changes"


def test_card_with_no_matching_event_renders_without_label(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "nolabel.md")
    frame, _ = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=None, flash_state={}
    )
    assert "nolabel" in frame
    assert "↳" not in frame


def test_card_with_event_shows_label(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "300")
    plans = _tree(tmp_path)
    _plan(plans / "features" / "labeled.md")
    _write_log(plans, "1.local.csv", ["2026-07-01T00:00:00+00:00", "labeled", "entered-review-needed"])
    frame, _ = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=None, flash_state={}
    )
    assert "↳ Sent for review" in frame


# --- Throughput stats: log-preferred, git/mtime fallback (Step 5) --------


def test_throughput_prefers_log_over_fallback(tmp_path):
    plans = _tree(tmp_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    recent = (now - datetime.timedelta(days=1)).isoformat()
    _write_log(plans, "1.local.csv", [recent, "a", "entered-completed"])
    _write_log(plans, "2.local.csv", [recent, "b", "entered-review-needed"])
    _write_log(plans, "3.local.csv", [recent, "c", "entered-review-needed"])

    # Fallback data present too, but must be ignored since the log has entries.
    _plan(plans / "completed" / "stale.md")
    old = now - datetime.timedelta(days=400)
    os.utime(plans / "completed" / "stale.md", (old.timestamp(), old.timestamp()))

    completed, processed = pb.compute_throughput(plans, tmp_path, pb.load_log_events(plans), now=now)
    assert (completed, processed) == (1, 2)


def test_throughput_falls_back_when_log_absent(tmp_path):
    plans = _tree(tmp_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    _plan(plans / "completed" / "recent.md")
    _plan(plans / "review-needed" / "pending.md")

    completed, processed = pb.compute_throughput(plans, tmp_path, [], now=now)
    assert completed == 1
    assert processed == 1


def test_throughput_uses_git_commit_time_not_mtime_for_tracked_files(tmp_path):
    """A fresh clone/checkout resets mtimes to 'now' -- git commit time must win
    for tracked .md files so throughput doesn't look artificially recent/stale."""
    plans = _tree(tmp_path)
    _git_repo(tmp_path)

    old_date = "2020-01-01T00:00:00+00:00"
    tracked = plans / "completed" / "old.md"
    _plan(tracked)
    _commit_file(tmp_path, ".plans/completed/old.md", old_date)

    # Simulate a fresh checkout: mtime looks like "now" even though the
    # commit (and thus the real "entered completed" time) is old.
    now = datetime.datetime.now(datetime.timezone.utc)
    os.utime(tracked, (now.timestamp(), now.timestamp()))

    completed, _ = pb.compute_throughput(plans, tmp_path, [], now=now)
    assert completed == 0  # git date is 2020 -- outside the 7-day window

    t = pb.entered_lane_time(tmp_path, tracked)
    assert t is not None
    assert t.year == 2020  # proves git time was used, not the "now" mtime


def test_local_md_falls_back_to_mtime_no_git_history(tmp_path):
    plans = _tree(tmp_path)
    _git_repo(tmp_path)
    local_plan = plans / "completed" / "priv.local.md"
    _plan(local_plan)
    now = datetime.datetime.now(datetime.timezone.utc)
    os.utime(local_plan, (now.timestamp(), now.timestamp()))

    t = pb.entered_lane_time(tmp_path, local_plan)
    assert t is not None
    assert abs((t - now).total_seconds()) < 5


# --- Move detection / animation (Step 4) -----------------------------------


def test_move_detected_between_two_frames(tmp_path):
    plans = _tree(tmp_path)
    plan_path = plans / "in-progress" / "moving.md"
    _plan(plan_path)

    _, positions1 = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=None, flash_state={}
    )
    assert positions1["moving"] == "In Progress"

    plan_path.rename(plans / "review-needed" / "moving.md")
    flash_state: dict[str, int] = {}
    frame2, positions2 = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=positions1, flash_state=flash_state
    )
    assert positions2["moving"] == "Review Needed"
    assert "moving moved: In Progress → Review Needed" in frame2
    assert "moving" in flash_state  # still flashing for the next frame(s)


def test_no_move_no_transition_line(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "still.md")
    _, positions1 = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=None, flash_state={}
    )
    frame2, _ = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=positions1, flash_state={}
    )
    assert "moved:" not in frame2


# --- Color: 256-color detection + fallback, no-color/non-tty --------------


def test_supports_256color_detection():
    assert pb.supports_256color({"TERM": "xterm-256color"}) is True
    assert pb.supports_256color({"COLORTERM": "truecolor"}) is True
    assert pb.supports_256color({"TERM": "xterm"}) is False
    assert pb.supports_256color({}) is False


def test_column_color_mapping_and_orange_fallback():
    assert pb.column_color("Completed") == pb.GREEN
    assert pb.column_color("Review Needed") == pb.YELLOW
    assert pb.column_color("Drafts") == pb.RED
    assert pb.column_color("Ambiguous") == pb.RED
    # In Progress: real orange on a 256-color terminal, distinct fallback otherwise
    assert pb.column_color("In Progress", {"TERM": "xterm-256color"}) == pb.ORANGE_256
    assert pb.column_color("In Progress", {"TERM": "xterm"}) == pb.ORANGE_FALLBACK
    assert pb.ORANGE_FALLBACK not in (pb.GREEN, pb.YELLOW, pb.RED)


def test_no_color_frame_has_no_ansi_codes(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "completed" / "x.md")
    frame, _ = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=None, flash_state={}
    )
    assert "\x1b[" not in frame


def test_color_frame_has_ansi_codes(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "completed" / "x.md")
    frame, _ = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=True, prev_positions=None, flash_state={}
    )
    assert "\x1b[" in frame


def test_strip_ansi_removes_escape_codes():
    colored = f"{pb.GREEN}hello{pb.RESET}"
    assert pb.strip_ansi(colored) == "hello"


# --- CLI smoke ---------------------------------------------------------


def test_main_once_no_color_no_ansi(tmp_path, capsys):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "smoke.md")
    rc = pb.main(["--project", str(tmp_path), "--once", "--no-color"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "smoke" in out
    assert "\x1b[" not in out


def test_main_missing_plans_dir_errors(tmp_path, capsys):
    rc = pb.main(["--project", str(tmp_path), "--once"])
    assert rc == 1


# --- JSON export (plan-board-json-export) ---------------------------------


def _plan_rich(
    path: Path,
    *,
    value: str = "medium",
    priority: str = "P2",
    title: str = "t",
    preferred: str = "mid",
    assignee: str | None = None,
    depends_on: str = "none",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assignee_line = f"- **Assignee:** {assignee}\n" if assignee is not None else ""
    path.write_text(
        f"# Plan: {title}\n\n"
        f"- **Value:** {value}\n"
        f"- **Priority:** {priority}\n"
        f"- **Preferred models:** {preferred}\n"
        f"{assignee_line}"
        f"- **Depends on:** {depends_on}\n\n"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def test_scan_lane_enriches_preferred_depends_assignee(tmp_path):
    plans = _tree(tmp_path)
    _plan_rich(
        plans / "features" / "rich.md",
        preferred="mid, Grok 4.5",
        assignee="alice@corp.com — owns it",
        depends_on="other-slug",
    )
    recs = pb.scan_lane(plans, "features")
    assert len(recs) == 1
    r = recs[0]
    assert r.preferred == "mid, Grok 4.5"
    assert r.depends_on == ("other-slug",)
    assert r.assignee is not None and "alice@corp.com" in r.assignee
    assert r.agent_assignable is False


def test_board_status_payload_schema_and_ready_merge(tmp_path):
    plans = _tree(tmp_path)
    _plan_rich(plans / "bugs" / "b.md", priority="P3", title="bug")
    _plan_rich(plans / "features" / "f.md", priority="P1", title="feat")
    _plan_rich(plans / "drafts" / "d.md", title="draft")

    payload = pb.board_status_payload(plans, tmp_path, include_parked=False)
    assert payload["schema_version"] == pb.SCHEMA_VERSION == 1
    assert set(payload) >= {
        "schema_version",
        "project_root",
        "plans_root",
        "generated_at",
        "include_parked",
        "throughput",
        "columns",
    }
    assert payload["include_parked"] is False
    assert payload["throughput"]["window_days"] == pb.WINDOW_DAYS
    assert "completed" in payload["throughput"]
    assert "processed" in payload["throughput"]

    names = [c["name"] for c in payload["columns"]]
    assert names == ["Drafts", "Ready", "In Progress", "Review Needed", "Completed"]
    by_name = {c["name"]: c for c in payload["columns"]}
    assert by_name["Ready"]["lanes"] == ["bugs", "features"]
    assert by_name["Ready"]["count"] == 2
    ready_slugs = [p["slug"] for p in by_name["Ready"]["plans"]]
    assert ready_slugs[0] == "b"  # bugs before features
    assert set(ready_slugs) == {"b", "f"}
    assert by_name["Drafts"]["plans"][0]["slug"] == "d"

    card = by_name["Ready"]["plans"][0]
    for key in (
        "slug",
        "rel",
        "lane",
        "title",
        "priority",
        "value",
        "preferred",
        "assignee",
        "agent_assignable",
        "depends_on",
        "path",
        "last_event",
    ):
        assert key in card
    assert card["lane"] == "bugs"
    assert card["preferred"] == "mid"
    assert card["depends_on"] == []
    assert card["last_event"] is None
    assert card["path"].endswith("bugs/b.md")


def test_board_status_payload_include_parked_and_empty_lanes(tmp_path):
    plans = _tree(tmp_path)
    _plan_rich(plans / "ambiguous" / "a.md")
    _plan_rich(plans / "blocked" / "bl.md")

    default = pb.board_status_payload(plans, tmp_path, include_parked=False)
    assert [c["name"] for c in default["columns"]] == [
        "Drafts",
        "Ready",
        "In Progress",
        "Review Needed",
        "Completed",
    ]
    for c in default["columns"]:
        assert c["plans"] == []
        assert c["count"] == 0

    parked = pb.board_status_payload(plans, tmp_path, include_parked=True)
    names = [c["name"] for c in parked["columns"]]
    assert names[-2:] == ["Ambiguous", "Blocked"]
    assert parked["include_parked"] is True
    by_name = {c["name"]: c for c in parked["columns"]}
    assert by_name["Ambiguous"]["plans"][0]["slug"] == "a"
    assert by_name["Blocked"]["plans"][0]["slug"] == "bl"


def test_board_status_payload_last_event_from_log(tmp_path):
    plans = _tree(tmp_path)
    _plan_rich(plans / "features" / "labeled.md")
    _write_log(
        plans,
        "1.local.csv",
        ["2026-07-01T00:00:00+00:00", "labeled", "entered-review-needed"],
    )
    payload = pb.board_status_payload(plans, tmp_path, include_parked=False)
    ready = {c["name"]: c for c in payload["columns"]}["Ready"]
    card = ready["plans"][0]
    assert card["last_event"] == "Sent for review"


def test_board_status_payload_sort_matches_terminal(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "high.md", value="high", priority="P1", title="feature high")
    _plan(plans / "bugs" / "low.md", value="low", priority="P3", title="bug low")
    _plan(plans / "features" / "low.md", value="low", priority="P2", title="feature low")
    _plan(plans / "features" / "hi2.md", value="high", priority="P2", title="feature hi2")

    columns = pb.build_columns(plans, include_parked=False)
    ready_term = [r.slug for r in dict(columns)["Ready"]]
    payload = pb.board_status_payload(plans, tmp_path, include_parked=False)
    ready_json = [
        p["slug"]
        for p in next(c for c in payload["columns"] if c["name"] == "Ready")["plans"]
    ]
    assert ready_json == ready_term == ["low", "high", "hi2", "low"]


def test_main_json_stdout(tmp_path, capsys):
    plans = _tree(tmp_path)
    _plan_rich(plans / "features" / "smoke.md")
    rc = pb.main(["--project", str(tmp_path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = __import__("json").loads(out)
    assert data["schema_version"] == 1
    assert any(c["name"] == "Ready" and c["count"] == 1 for c in data["columns"])


def test_main_json_missing_plans_dir_errors(tmp_path, capsys):
    rc = pb.main(["--project", str(tmp_path), "--json"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no .plans/" in err


# --- Extra kanban coverage (from parked WIP) -------------------------------


def test_render_frame_shows_throughput_headers_counts_and_cards(tmp_path, monkeypatch):
    """Full terminal frame: header stats, column titles with counts, cards."""
    monkeypatch.setenv("COLUMNS", "200")
    plans = _tree(tmp_path)
    now = datetime.datetime(2026, 8, 8, 12, 0, tzinfo=datetime.timezone.utc)
    _plan(plans / "drafts" / "wip-idea.md", title="Draft idea", priority="P2")
    _plan(plans / "bugs" / "crash.md", title="Fix crash", priority="P1", value="high")
    _plan(plans / "features" / "shiny.md", title="Add shiny", priority="P2", value="medium")
    _plan(plans / "in-progress" / "doing.md", title="Doing work", priority="P2")
    _plan(plans / "review-needed" / "check.md", title="Needs eyes", priority="P2")
    _plan(plans / "completed" / "done.md", title="Shipped", priority="P3")
    recent = (now - datetime.timedelta(days=1)).isoformat()
    _write_log(plans, "done.local.csv", [recent, "done", "entered-completed"])
    _write_log(plans, "check.local.csv", [recent, "check", "entered-review-needed"])

    frame, positions = pb.render_frame(
        plans,
        tmp_path,
        include_parked=False,
        color_on=False,
        prev_positions=None,
        flash_state={},
        now=now,
    )

    assert "Completed (7d): 1" in frame
    assert "Processed (7d): 1" in frame
    assert "Drafts (1)" in frame
    assert "Ready (2)" in frame
    assert "In Progress (1)" in frame
    assert "Review Needed (1)" in frame
    assert "Completed (1)" in frame
    assert "crash" in frame
    assert "Fix crash" in frame
    assert "[P1/high]" in frame
    assert "shiny" in frame
    assert "doing" in frame
    assert "wip-idea" in frame
    assert "Ambiguous" not in frame
    assert "Blocked" not in frame
    assert positions == {
        "wip-idea": "Drafts",
        "crash": "Ready",
        "shiny": "Ready",
        "doing": "In Progress",
        "check": "Review Needed",
        "done": "Completed",
    }


def test_render_frame_include_parked_shows_ambiguous_and_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    plans = _tree(tmp_path)
    _plan(plans / "ambiguous" / "unclear.md", title="Unclear scope")
    _plan(plans / "blocked" / "stuck.md", title="Waiting on API")

    frame_default, _ = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=None, flash_state={}
    )
    assert "Ambiguous" not in frame_default
    assert "unclear" not in frame_default

    frame, positions = pb.render_frame(
        plans, tmp_path, include_parked=True, color_on=False, prev_positions=None, flash_state={}
    )
    assert "Ambiguous (1)" in frame
    assert "Blocked (1)" in frame
    assert "unclear" in frame
    assert "stuck" in frame
    assert positions["unclear"] == "Ambiguous"
    assert positions["stuck"] == "Blocked"


def test_all_columns_sort_by_priority_then_value(tmp_path):
    """Sort order is uniform across columns — not only Ready."""
    plans = _tree(tmp_path)
    for lane in ("drafts", "in-progress", "completed"):
        _plan(plans / lane / "p3.md", priority="P3", value="high", title="p3")
        _plan(plans / lane / "p1-low.md", priority="P1", value="low", title="p1 low")
        _plan(plans / lane / "p1-high.md", priority="P1", value="high", title="p1 high")

    columns = dict(pb.build_columns(plans, include_parked=False))
    for name in ("Drafts", "In Progress", "Completed"):
        slugs = [r.slug for r in columns[name]]
        assert slugs == ["p1-high", "p1-low", "p3"], f"{name}: {slugs}"


def test_scan_lane_skips_readme_and_unreadable_handles_local_md(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "real.local.md", title="Private plan")
    (plans / "features" / "README.md").write_text("# lane readme\n", encoding="utf-8")
    (plans / "features" / "notes.txt").write_text("not a plan\n", encoding="utf-8")
    (plans / "features" / "empty.md").write_text("", encoding="utf-8")

    recs = pb.scan_lane(plans, "features")
    slugs = {r.slug for r in recs}
    assert "real" in slugs
    assert "README" not in slugs
    assert "notes" not in slugs
    assert "empty" in slugs
    private = next(r for r in recs if r.slug == "real")
    assert private.rel == "features/real.local.md"
    assert private.lane == "features"


def test_scan_lane_missing_lane_dir_returns_empty(tmp_path):
    plans = tmp_path / ".plans"
    plans.mkdir()
    assert pb.scan_lane(plans, "features") == []
    assert pb.build_columns(plans, include_parked=False)
    for _name, records in pb.build_columns(plans, include_parked=True):
        assert records == []


def test_parse_log_file_malformed_and_valid(tmp_path):
    plans = _tree(tmp_path)
    logs = plans / "logs"
    logs.mkdir()
    (logs / "bad-short.csv").write_text("only-one-field\n", encoding="utf-8")
    (logs / "bad-ts.csv").write_text("not-a-date,slug,entered-completed\n", encoding="utf-8")
    (logs / "ok.csv").write_text(
        "2026-08-01T10:00:00,foo,entered-completed,review-needed,completed\n",
        encoding="utf-8",
    )
    assert pb.parse_log_file(logs / "bad-short.csv") is None
    assert pb.parse_log_file(logs / "bad-ts.csv") is None
    assert pb.parse_log_file(logs / "missing.csv") is None
    ev = pb.parse_log_file(logs / "ok.csv")
    assert ev is not None
    assert ev.slug == "foo"
    assert ev.event == "entered-completed"
    assert ev.from_lane == "review-needed"
    assert ev.to_lane == "completed"
    assert ev.timestamp.tzinfo is not None

    events = pb.load_log_events(plans)
    assert len(events) == 1
    assert events[0].slug == "foo"


def test_throughput_excludes_events_outside_window(tmp_path):
    plans = _tree(tmp_path)
    now = datetime.datetime(2026, 8, 8, 12, 0, tzinfo=datetime.timezone.utc)
    old = (now - datetime.timedelta(days=10)).isoformat()
    recent = (now - datetime.timedelta(days=2)).isoformat()
    _write_log(plans, "old.csv", [old, "a", "entered-completed"])
    _write_log(plans, "new.csv", [recent, "b", "entered-completed"])
    _write_log(plans, "old-rn.csv", [old, "c", "entered-review-needed"])
    _write_log(plans, "new-rn.csv", [recent, "d", "entered-review-needed"])

    completed, processed = pb.compute_throughput(
        plans, tmp_path, pb.load_log_events(plans), now=now
    )
    assert (completed, processed) == (1, 1)


def test_board_status_throughput_matches_compute_throughput(tmp_path):
    """JSON throughput block is the same counters as the terminal header."""
    plans = _tree(tmp_path)
    now = datetime.datetime(2026, 8, 8, 12, 0, tzinfo=datetime.timezone.utc)
    recent = (now - datetime.timedelta(hours=6)).isoformat()
    _write_log(plans, "c.csv", [recent, "x", "entered-completed"])
    _write_log(plans, "p1.csv", [recent, "y", "entered-review-needed"])
    _write_log(plans, "p2.csv", [recent, "z", "entered-review-needed"])
    events = pb.load_log_events(plans)
    expected = pb.compute_throughput(plans, tmp_path, events, now=now)
    payload = pb.board_status_payload(plans, tmp_path, include_parked=False, now=now)
    assert payload["throughput"]["window_days"] == 7
    assert payload["throughput"]["completed"] == expected[0] == 1
    assert payload["throughput"]["processed"] == expected[1] == 2


def test_format_card_lines_and_truncate():
    from plan_select import PlanRecord

    rec = PlanRecord(
        path=Path("/tmp/.plans/features/long-slug-name.md"),
        rel="features/long-slug-name.md",
        lane="features",
        slug="long-slug-name",
        value="high",
        priority="P1",
        preferred="mid",
        title="A very long plan title for truncation",
    )
    lines = pb.format_card_lines(rec, "Sent for review", width=12)
    assert lines[0] == pb.truncate("long-slug-name", 12) == "long-slug-n…"
    assert lines[2] == "[P1/high]"
    assert lines[3].startswith("↳ ")
    assert lines[-1] == ""
    assert pb.truncate("abc", 10) == "abc"
    assert pb.truncate("abcdef", 4) == "abc…"
    assert pb.truncate("x", 0) == ""
    assert pb.truncate("xy", 1) == "x"


def test_cli_subprocess_once_and_json(tmp_path):
    """Real script entrypoint (not only imported main) works for kanban consumers."""
    plans = _tree(tmp_path)
    _plan(plans / "bugs" / "cli-bug.md", title="CLI bug", priority="P1", value="high")
    script = Path(pb.__file__).resolve()

    once = subprocess.run(
        [sys.executable, str(script), "--project", str(tmp_path), "--once", "--no-color"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert once.returncode == 0, once.stderr
    assert "cli-bug" in once.stdout
    assert "Ready (1)" in once.stdout
    assert "Completed (7d):" in once.stdout
    assert "\x1b[" not in once.stdout

    js = subprocess.run(
        [sys.executable, str(script), "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert js.returncode == 0, js.stderr
    data = __import__("json").loads(js.stdout)
    assert data["schema_version"] == 1
    ready = next(c for c in data["columns"] if c["name"] == "Ready")
    assert ready["count"] == 1
    assert ready["plans"][0]["slug"] == "cli-bug"
    assert ready["plans"][0]["lane"] == "bugs"
    assert ready["plans"][0]["priority"] == "P1"

    missing = subprocess.run(
        [sys.executable, str(script), "--project", str(tmp_path / "nope"), "--once"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 1
    assert "no .plans/" in missing.stderr


def test_main_include_parked_once(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    plans = _tree(tmp_path)
    _plan(plans / "blocked" / "gate.md", title="Blocked gate")
    rc = pb.main(["--project", str(tmp_path), "--once", "--no-color", "--include-parked"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Blocked (1)" in out
    assert "gate" in out


def test_flash_expires_after_flash_frames(tmp_path):
    plans = _tree(tmp_path)
    src = plans / "features" / "flashy.md"
    _plan(src)
    _, pos1 = pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=None, flash_state={}
    )
    src.rename(plans / "in-progress" / "flashy.md")
    flash: dict[str, int] = {}
    pb.render_frame(
        plans, tmp_path, include_parked=False, color_on=False, prev_positions=pos1, flash_state=flash
    )
    assert flash.get("flashy") in (pb.FLASH_FRAMES, pb.FLASH_FRAMES - 1)
    pos = pos1
    for _ in range(pb.FLASH_FRAMES + 2):
        _, pos = pb.render_frame(
            plans,
            tmp_path,
            include_parked=False,
            color_on=False,
            prev_positions=pos,
            flash_state=flash,
        )
    assert "flashy" not in flash


def test_default_priority_and_value_when_headers_absent(tmp_path):
    plans = _tree(tmp_path)
    path = plans / "features" / "bare.md"
    path.write_text("# Plan: Bare\n\n## Goal\nx\n", encoding="utf-8")
    rec = pb.scan_lane(plans, "features")[0]
    assert rec.priority == "P2"
    assert rec.value == "medium"
    assert rec.title == "Plan: Bare"
