"""CLI verb `anchor fleet-watch` wraps fleet_watch.py."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import anchor_cli
import fleet_watch as fw
from test_anchor_cli import write


def test_emit_matches_script(tmp_path: Path):
    root = tmp_path / "app"
    for lane in ("bugs", "features", "in-progress", "drafts", "completed",
                 "review-needed", "ambiguous", "blocked"):
        (root / ".plans" / lane).mkdir(parents=True)
    write(root, "features", "f1")
    worker = "tier=small,agent=s1,interval=10m"
    files = fw.emit_systemd(
        root, Path(fw.SCRIPTS_DIR), [fw.parse_worker(worker)], python="python3",
    )
    script_names = {n for n, _ in files}
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
    names = {u["name"] for u in payload["result"]["units"]}
    assert names == script_names
    joined = "\n".join(u["content"] for u in payload["result"]["units"])
    assert "--watch" in joined
    assert "work_once.py" in joined


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
