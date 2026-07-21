#!/usr/bin/env python3
"""Read-only terminal kanban board for a project's ``.plans/`` tree.

Renders five default columns — Drafts | Ready (bugs/+features/ merged) |
In Progress | Review Needed | Completed — sorted uniformly by the same
Priority -> Value -> mtime order ``plan_select.py`` already uses for ready-lane
picking. Never writes, moves, or edits anything under ``.plans/``.

Header shows two rolling 7-day throughput counters, Completed and Processed
(entered review-needed/), preferring ``.plans/logs/*.csv``/``*.local.csv``
event files (see the lane-transition-log design) when present, falling back to
git commit time (tracked ``.md``) or filesystem mtime (``.local.md``) when the
log is absent or empty. Each card also shows a brief label for the most recent
logged event on record for its slug, if any.

Usage:
  python3 scripts/plan_board.py               # live, redraws every 60s
  python3 scripts/plan_board.py --once         # single frame, for piping/CI
  python3 scripts/plan_board.py --interval 5
  python3 scripts/plan_board.py --include-parked
  python3 scripts/plan_board.py --no-color
"""
from __future__ import annotations

import argparse
import csv
import datetime
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plan_select import (  # noqa: E402
    PlanRecord,
    parse_priority,
    parse_title,
    parse_value,
    plan_slug,
    plan_sort_key,
)

READY_LANES = ("bugs", "features")
COLUMN_LANES: list[tuple[str, tuple[str, ...]]] = [
    ("Drafts", ("drafts",)),
    ("Ready", READY_LANES),
    ("In Progress", ("in-progress",)),
    ("Review Needed", ("review-needed",)),
    ("Completed", ("completed",)),
]
PARKED_COLUMN_LANES: list[tuple[str, tuple[str, ...]]] = [
    ("Ambiguous", ("ambiguous",)),
    ("Blocked", ("blocked",)),
]

WINDOW_DAYS = 7
FLASH_FRAMES = 2  # redraws a moved card stays highlighted for

# ANSI color accents. Standard 8/16-color has no true "orange"; on a
# 256-color-capable terminal we use a real orange, otherwise a bright-red
# approximation distinct from the plain "other columns" red and from yellow.
RESET = "\x1b[0m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
ORANGE_256 = "\x1b[38;5;208m"
ORANGE_FALLBACK = "\x1b[91m"  # bright red, distinct from plain red + yellow

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

LOG_EVENT_LABELS = {
    "entered-completed": "Completed",
    "entered-review-needed": "Sent for review",
}


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def supports_256color(env: dict[str, str] | None = None) -> bool:
    env = env if env is not None else os.environ
    term = env.get("TERM", "")
    colorterm = env.get("COLORTERM", "")
    return "256color" in term or "truecolor" in colorterm or "24bit" in colorterm


def orange_code(env: dict[str, str] | None = None) -> str:
    return ORANGE_256 if supports_256color(env) else ORANGE_FALLBACK


def column_color(name: str, env: dict[str, str] | None = None) -> str:
    if name == "Completed":
        return GREEN
    if name == "Review Needed":
        return YELLOW
    if name == "In Progress":
        return orange_code(env)
    return RED  # Drafts, Ready, Ambiguous, Blocked


def humanize_event(event: str) -> str:
    label = LOG_EVENT_LABELS.get(event)
    if label:
        return label
    return event.replace("-", " ").replace("_", " ").strip().title()


@dataclass(frozen=True)
class LogEvent:
    timestamp: datetime.datetime
    slug: str
    event: str
    from_lane: str
    to_lane: str


def parse_log_file(path: Path) -> LogEvent | None:
    """Parse one lane-transition-log CSV event file. Content is authoritative
    (not the filename) — a manually renamed file still parses correctly."""
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            row = next(csv.reader(fh), None)
    except OSError:
        return None
    if not row or len(row) < 3:
        return None
    ts_raw, slug, event = row[0].strip(), row[1].strip(), row[2].strip()
    from_lane = row[3].strip() if len(row) > 3 else ""
    to_lane = row[4].strip() if len(row) > 4 else ""
    if not slug or not event:
        return None
    try:
        ts = datetime.datetime.fromisoformat(ts_raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return LogEvent(timestamp=ts, slug=slug, event=event, from_lane=from_lane, to_lane=to_lane)


def load_log_events(plans_root: Path) -> list[LogEvent]:
    logs_dir = plans_root / "logs"
    if not logs_dir.is_dir():
        return []
    events: list[LogEvent] = []
    for path in logs_dir.glob("*.csv"):
        ev = parse_log_file(path)
        if ev is not None:
            events.append(ev)
    return events


def latest_events_by_slug(log_events: list[LogEvent]) -> dict[str, LogEvent]:
    latest: dict[str, LogEvent] = {}
    for ev in log_events:
        cur = latest.get(ev.slug)
        if cur is None or ev.timestamp > cur.timestamp:
            latest[ev.slug] = ev
    return latest


def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def git_commit_time(project_root: Path, path: Path) -> datetime.datetime | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(project_root), "log", "-1", "--format=%cI", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    if not out:
        return None
    try:
        return datetime.datetime.fromisoformat(out)
    except ValueError:
        return None


def entered_lane_time(project_root: Path, path: Path) -> datetime.datetime | None:
    """Best-effort timestamp a file landed in its current lane.

    Prefers git commit time for a tracked ``.md`` file (immune to clone/
    checkout mtime resets); falls back to filesystem mtime for ``.local.md``
    (no git history) or when git has nothing for the path.
    """
    if not path.name.endswith(".local.md"):
        t = git_commit_time(project_root, path)
        if t is not None:
            return t
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)


def compute_throughput(
    plans_root: Path,
    project_root: Path,
    log_events: list[LogEvent],
    *,
    now: datetime.datetime | None = None,
) -> tuple[int, int]:
    """Return (completed_7d, processed_7d).

    Prefers parsed log events (exact, immune to mtime resets); falls back to
    git-commit-time/mtime heuristics only when the log has zero parseable
    events at all (folder absent or empty/malformed) -- a log that legitimately
    contains zero matching events is still authoritative, not "absent".
    """
    window_start = (now or now_utc()) - datetime.timedelta(days=WINDOW_DAYS)

    if log_events:
        completed = sum(
            1 for e in log_events if e.event == "entered-completed" and e.timestamp >= window_start
        )
        processed = sum(
            1 for e in log_events if e.event == "entered-review-needed" and e.timestamp >= window_start
        )
        return completed, processed

    def _count(lane: str) -> int:
        lane_dir = plans_root / lane
        if not lane_dir.is_dir():
            return 0
        n = 0
        for path in lane_dir.glob("*.md"):
            if path.name == "README.md":
                continue
            t = entered_lane_time(project_root, path)
            if t is not None and t >= window_start:
                n += 1
        return n

    return _count("completed"), _count("review-needed")


def scan_lane(plans_root: Path, lane: str) -> list[PlanRecord]:
    lane_dir = plans_root / lane
    if not lane_dir.is_dir():
        return []
    records: list[PlanRecord] = []
    for path in sorted(lane_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        records.append(
            PlanRecord(
                path=path.resolve(),
                rel=f"{lane}/{path.name}",
                lane=lane,
                slug=plan_slug(path),
                value=parse_value(text),
                priority=parse_priority(text),
                preferred=None,
                title=parse_title(text, path.name),
            )
        )
    return records


def build_columns(plans_root: Path, *, include_parked: bool) -> list[tuple[str, list[PlanRecord]]]:
    spec = COLUMN_LANES + (PARKED_COLUMN_LANES if include_parked else [])
    columns: list[tuple[str, list[PlanRecord]]] = []
    for name, lanes in spec:
        records: list[PlanRecord] = []
        for lane in lanes:
            records.extend(scan_lane(plans_root, lane))
        records.sort(key=plan_sort_key)
        columns.append((name, records))
    return columns


def truncate(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width == 1:
        return s[:1]
    return s[: width - 1] + "…"


def format_card_lines(rec: PlanRecord, label: str | None, width: int) -> list[str]:
    lines = [
        truncate(rec.slug, width),
        truncate(rec.title, width),
        truncate(f"[{rec.priority}/{rec.value}]", width),
    ]
    if label:
        lines.append(truncate(f"↳ {label}", width))
    lines.append("")
    return lines


def render_column(
    name: str,
    records: list[PlanRecord],
    width: int,
    *,
    color_on: bool,
    labels: dict[str, str],
    flashing: set[str],
) -> list[str]:
    header_plain = truncate(f"── {name} ({len(records)}) ──", width)
    color = column_color(name) if color_on else ""
    lines = [f"{color}{header_plain}{RESET}" if color_on else header_plain]
    for rec in records:
        flash = color_on and rec.slug in flashing
        for line in format_card_lines(rec, labels.get(rec.slug), width):
            if flash and line:
                lines.append(f"{color}{line}{RESET}")
            else:
                lines.append(line)
    return lines


def render_frame(
    plans_root: Path,
    project_root: Path,
    *,
    include_parked: bool,
    color_on: bool,
    prev_positions: dict[str, str] | None,
    flash_state: dict[str, int],
    now: datetime.datetime | None = None,
) -> tuple[str, dict[str, str]]:
    columns = build_columns(plans_root, include_parked=include_parked)
    log_events = load_log_events(plans_root)
    completed_n, processed_n = compute_throughput(plans_root, project_root, log_events, now=now)
    labels = {
        slug: humanize_event(ev.event) for slug, ev in latest_events_by_slug(log_events).items()
    }

    new_positions: dict[str, str] = {}
    for name, records in columns:
        for rec in records:
            new_positions[rec.slug] = name

    moves: list[tuple[str, str, str]] = []
    if prev_positions is not None:
        for slug, col in new_positions.items():
            prev_col = prev_positions.get(slug)
            if prev_col is not None and prev_col != col:
                moves.append((slug, prev_col, col))
                flash_state[slug] = FLASH_FRAMES

    flashing = {slug for slug, remaining in flash_state.items() if remaining > 0}
    for slug in list(flash_state):
        flash_state[slug] -= 1
        if flash_state[slug] <= 0:
            del flash_state[slug]

    term_width, _ = shutil.get_terminal_size(fallback=(80, 24))
    col_count = max(1, len(columns))
    col_width = max(14, term_width // col_count - 1)

    col_blocks = [
        render_column(name, records, col_width, color_on=color_on, labels=labels, flashing=flashing)
        for name, records in columns
    ]
    height = max((len(b) for b in col_blocks), default=0)
    for block in col_blocks:
        block.extend([""] * (height - len(block)))

    out_lines = [f"Completed (7d): {completed_n}   Processed (7d): {processed_n}", ""]
    for row in range(height):
        parts = []
        for block in col_blocks:
            cell = block[row]
            pad = " " * max(0, col_width - len(strip_ansi(cell)))
            parts.append(cell + pad)
        out_lines.append(" ".join(parts))
    for slug, prev_col, cur_col in moves:
        out_lines.append(f"→ {slug} moved: {prev_col} → {cur_col}")

    return "\n".join(out_lines), new_positions


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--project", default=".", help="project root (default: current directory)")
    ap.add_argument(
        "--interval", type=float, default=60.0, help="redraw interval in seconds (default: 60)"
    )
    ap.add_argument("--once", action="store_true", help="render a single frame and exit")
    ap.add_argument(
        "--include-parked",
        action="store_true",
        help="also show Ambiguous/Blocked columns (ambiguous/, blocked/)",
    )
    ap.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI color output (also auto-disabled on non-TTY stdout)",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    project_root = Path(args.project).resolve()
    plans_root = project_root / ".plans"
    if not plans_root.is_dir():
        print(f"no .plans/ directory under {project_root}", file=sys.stderr)
        return 1

    color_on = (not args.no_color) and sys.stdout.isatty()

    prev_positions: dict[str, str] | None = None
    flash_state: dict[str, int] = {}

    if args.once:
        frame, _ = render_frame(
            plans_root,
            project_root,
            include_parked=args.include_parked,
            color_on=color_on,
            prev_positions=prev_positions,
            flash_state=flash_state,
        )
        print(frame)
        return 0

    try:
        while True:
            frame, prev_positions = render_frame(
                plans_root,
                project_root,
                include_parked=args.include_parked,
                color_on=color_on,
                prev_positions=prev_positions,
                flash_state=flash_state,
            )
            if sys.stdout.isatty():
                print("\x1b[2J\x1b[H", end="")
            print(frame)
            time.sleep(max(1.0, args.interval))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
