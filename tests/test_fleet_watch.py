from pathlib import Path

import fleet_watch as fw
import pytest


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


def test_cmd_list_or_once_builds_triage_command(tmp_path, monkeypatch):
    project = tmp_path / "app"
    (project / ".plans").mkdir(parents=True)
    scripts = Path(fw.SCRIPTS_DIR)
    captured = {}

    def fake_call(cmd, env=None):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(fw.subprocess, "call", fake_call)
    args = fw.argparse.Namespace(
        tier="mid", agent_id="t1", endpoint=None, model=None,
        registry=None, run=False, python="python3",
    )

    code = fw.cmd_list_or_once(project, scripts, args, mode="triage")

    assert code == 0
    assert "--triage" in captured["cmd"]
    assert "--list" not in captured["cmd"]
    assert "--once" not in captured["cmd"]


def test_cmd_list_or_once_builds_list_and_once_commands(tmp_path, monkeypatch):
    project = tmp_path / "app"
    (project / ".plans").mkdir(parents=True)
    scripts = Path(fw.SCRIPTS_DIR)
    captured = []

    def fake_call(cmd, env=None):
        captured.append(cmd)
        return 0

    monkeypatch.setattr(fw.subprocess, "call", fake_call)
    args = fw.argparse.Namespace(
        tier="mid", agent_id="t1", endpoint=None, model=None,
        registry=None, run=False, python="python3",
    )

    fw.cmd_list_or_once(project, scripts, args, mode="list")
    fw.cmd_list_or_once(project, scripts, args, mode="once")

    assert "--list" in captured[0] and "--triage" not in captured[0]
    assert "--once" in captured[1] and "--triage" not in captured[1]


def test_cli_triage_needs_tier_or_endpoint(tmp_path, capsys):
    project = tmp_path / "app"
    (project / ".plans").mkdir(parents=True)
    with pytest.raises(SystemExit) as exc_info:
        fw.main(["--project", str(project), "--triage"])
    assert exc_info.value.code == 2
    assert "--triage needs" in capsys.readouterr().err


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


# -- site inference-load passthrough ---------------------------------------

LOAD_ENV = {
    "ANCHOR_MQTT_URL": "mqtt://broker:1883",
    "ANCHOR_MQTT_SITE": "garage",
    "ANCHOR_LOAD_FAILSAFE": "hold",
    "ANCHOR_MQTT_PASSWORD": "hunter2",
}


def test_unit_carries_load_env_when_configured(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    (project / ".plans").mkdir()
    workers = [fw.parse_worker("tier=mid,agent=mid-1,interval=5m")]
    body = next(
        c for n, c in fw.emit_systemd(project, Path(fw.SCRIPTS_DIR), workers,
                                      python="/usr/bin/python3", env=LOAD_ENV)
        if n.endswith(".service")
    )
    assert "Environment=ANCHOR_MQTT_URL=mqtt://broker:1883" in body
    assert "Environment=ANCHOR_MQTT_SITE=garage" in body
    assert "Environment=ANCHOR_LOAD_FAILSAFE=hold" in body


def test_unit_never_writes_the_broker_password(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    (project / ".plans").mkdir()
    workers = [fw.parse_worker("tier=mid,agent=mid-1,interval=5m")]
    body = next(
        c for n, c in fw.emit_systemd(project, Path(fw.SCRIPTS_DIR), workers,
                                      python="/usr/bin/python3", env=LOAD_ENV)
        if n.endswith(".service")
    )
    assert "hunter2" not in body
    assert "ANCHOR_MQTT_PASSWORD" not in body


def test_unit_has_no_load_env_when_unconfigured(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    (project / ".plans").mkdir()
    workers = [fw.parse_worker("tier=mid,agent=mid-1,interval=5m")]
    body = next(
        c for n, c in fw.emit_systemd(project, Path(fw.SCRIPTS_DIR), workers,
                                      python="/usr/bin/python3", env={})
        if n.endswith(".service")
    )
    assert "ANCHOR_MQTT" not in body
    assert "ExecStart=" in body


def test_cron_lines_carry_load_env(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    (project / ".plans").mkdir()
    workers = [fw.parse_worker("tier=small,agent=swarm-1,interval=10m")]
    lines = fw.emit_cron_lines(project, Path(fw.SCRIPTS_DIR), workers,
                               python="/usr/bin/python3", env=LOAD_ENV)
    body = "\n".join(lines)
    assert "ANCHOR_MQTT_SITE=garage" in body
    assert "hunter2" not in body


def test_worker_spec_local_flag_reaches_work_once(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    w = fw.parse_worker("tier=small,agent=swarm-1,local=1")
    assert w.local is True
    cmd = fw.work_once_cmd(Path(fw.SCRIPTS_DIR), project, w, python="/usr/bin/python3")
    assert "--local-worker" in cmd
    plain = fw.parse_worker("tier=small,agent=swarm-2")
    assert "--local-worker" not in fw.work_once_cmd(
        Path(fw.SCRIPTS_DIR), project, plain, python="/usr/bin/python3"
    )
