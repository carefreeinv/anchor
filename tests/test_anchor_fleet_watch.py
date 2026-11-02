"""CLI verb `anchor fleet-watch` wraps fleet_watch.py."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import anchor_cli
import fleet_watch as fw
from test_anchor_cli import write


def _plans(root: Path) -> None:
    for lane in ("bugs", "features", "in-progress", "drafts", "completed",
                 "review-needed", "ambiguous", "blocked"):
        (root / ".plans" / lane).mkdir(parents=True)
    write(root, "features", "f1")


def _script_emit(root: Path, worker: str, emit: str) -> str:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        code = fw.main([
            "--project", str(root), "--emit", emit, "--worker", worker,
        ])
    finally:
        sys.stdout = old
    assert code == 0
    return buf.getvalue()


def test_emit_matches_script(tmp_path: Path):
    root = tmp_path / "app"
    _plans(root)
    worker = "tier=small,agent=s1,interval=10m"
    script = _script_emit(root, worker, "systemd")
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        code = anchor_cli.main(
            ["fleet-watch", "--root", str(root), "--emit", "systemd",
             "--worker", worker, "--json", "--non-interactive"],
        )
    finally:
        sys.stdout = old
    payload = json.loads(buf.getvalue())
    assert code == 0
    assert payload["exit_code"] == 0
    assert payload["result"]["text"] == script
    assert "### " in script
    for unit in payload["result"]["units"]:
        assert f"### {unit['name']}" in script
        assert unit["content"] in script


def test_emit_cron_matches_script(tmp_path: Path):
    root = tmp_path / "app"
    _plans(root)
    worker = "tier=small,agent=s1,interval=10m"
    script = _script_emit(root, worker, "cron")
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        code = anchor_cli.main(
            ["fleet-watch", "--root", str(root), "--emit", "cron",
             "--worker", worker, "--json", "--non-interactive"],
        )
    finally:
        sys.stdout = old
    payload = json.loads(buf.getvalue())
    assert code == 0
    assert "units" not in payload["result"]
    assert payload["result"]["text"] == script
    assert payload["result"]["cron"]


def test_list_requires_tier_or_endpoint(tmp_path: Path):
    root = tmp_path / "app"
    _plans(root)
    buf = io.StringIO()
    old = sys.stderr
    sys.stderr = buf
    try:
        code = anchor_cli.main(
            ["fleet-watch", "--root", str(root), "--list", "--non-interactive"],
        )
    finally:
        sys.stderr = old
    assert code == 2


def test_help_names_flags():
    from contextlib import redirect_stderr, redirect_stdout

    out = io.StringIO()
    err = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            anchor_cli.build_parser().parse_args(["fleet-watch", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    text = out.getvalue() + err.getvalue()
    for token in ("--project", "--emit", "--worker", "--install-user", "--triage"):
        assert token in text
