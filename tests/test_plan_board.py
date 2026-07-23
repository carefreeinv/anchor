import datetime
import os
import subprocess
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
