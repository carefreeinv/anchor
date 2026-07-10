from pathlib import Path

import fleet_watch as fw


def test_parse_interval_to_systemd():
    assert fw.parse_interval_to_systemd("5m") == "5min"
    assert fw.parse_interval_to_systemd("10min") == "10min"
    assert fw.parse_interval_to_systemd("1h") == "1h"
    assert fw.parse_interval_to_systemd("30s") == "30s"
    assert fw.parse_interval_to_systemd("300") == "300s"


def test_parse_worker():
    w = fw.parse_worker("tier=mid,agent=mid-1,interval=5m")
    assert w.tier == "mid"
    assert w.agent_id == "mid-1"
    assert w.interval == "5m"
    w2 = fw.parse_worker("endpoint=h100-executor,agent=a,run=1")
    assert w2.endpoint == "h100-executor"
    assert w2.run is True


def test_emit_systemd_contains_work_once_and_success_exit(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    (project / ".plans").mkdir()
    scripts = Path(fw.SCRIPTS_DIR)
    workers = [fw.parse_worker("tier=mid,agent=mid-1,interval=5m")]
    files = fw.emit_systemd(project, scripts, workers, python="/usr/bin/python3")
    names = [n for n, _ in files]
    assert any(n.endswith(".service") for n in names)
    assert any(n.endswith(".timer") for n in names)
    body = next(c for n, c in files if n.endswith(".service"))
    assert "work_once.py" in body
    assert "--root" in body
    assert "SuccessExitStatus=0 1" in body
    assert "mid-1" in body
    timer = next(c for n, c in files if n.endswith(".timer"))
    assert "OnUnitActiveSec=5min" in timer
    assert "Persistent=true" in timer


def test_emit_cron_line(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    scripts = Path(fw.SCRIPTS_DIR)
    lines = fw.emit_cron_lines(
        project,
        scripts,
        [fw.parse_worker("tier=small,agent=s1,interval=10m")],
        python="python3",
    )
    assert any(line.startswith("*/10") for line in lines if not line.startswith("#"))
    assert any("work_once.py" in line for line in lines)


def test_status_missing_plans(tmp_path, capsys):
    project = tmp_path / "empty"
    project.mkdir()
    code = fw.cmd_status(project, Path(fw.SCRIPTS_DIR))
    assert code == 2
    assert "MISSING" in capsys.readouterr().out


def test_status_ok(tmp_path, capsys):
    project = tmp_path / "app"
    for lane in ("bugs", "features", "in-progress", "drafts", "completed"):
        (project / ".plans" / lane).mkdir(parents=True)
    (project / ".anchor").mkdir(parents=True, exist_ok=True)
    (project / ".anchor" / "conventions.md").write_text(
        "**Preferred orchestrator:** `claude:opus`\n"
    )
    code = fw.cmd_status(project, Path(fw.SCRIPTS_DIR))
    assert code == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "claude:opus" in out


def test_cli_emit_systemd(tmp_path, capsys):
    project = tmp_path / "app"
    (project / ".plans").mkdir(parents=True)
    code = fw.main(
        [
            "--project",
            str(project),
            "--emit",
            "systemd",
            "--worker",
            "tier=mid,agent=x,interval=5m",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert ".service" in out
    assert "enable-linger" in out
