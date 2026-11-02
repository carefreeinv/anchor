"""Event-driven plan watchers: debounce, poll fallback, MQTT no-op."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import plan_watch as pw
import work_once


def test_debounce_coalesces_burst():
    q = pw.QueueWatch()
    reasons: list[str] = []

    def run():
        for r in pw.run_loop(
            q, debounce_s=0.15, heartbeat_s=30, cycles=1,
        ):
            reasons.append(r)

    t = threading.Thread(target=run)
    t.start()
    q.poke("a")
    q.poke("b")
    q.poke("c")
    t.join(timeout=2)
    assert reasons == ["c"]


def test_heartbeat_when_quiet():
    q = pw.QueueWatch()
    got = list(pw.run_loop(q, debounce_s=0.01, heartbeat_s=0.05, cycles=1))
    assert got == ["heartbeat"]


def test_mqtt_unconfigured_is_noop(monkeypatch):
    monkeypatch.delenv("ANCHOR_MQTT_URL", raising=False)
    monkeypatch.delenv("ANCHOR_MQTT_SITE", raising=False)
    monkeypatch.delenv("ANCHOR_MQTT_PLANS_TOPIC", raising=False)
    assert pw.mqtt_configured({}) is False
    assert pw.open_mqtt_watch({}) is None
    assert pw.publish_mqtt_poke({}) is False


def test_mqtt_topic_from_site():
    env = {"ANCHOR_MQTT_URL": "mqtt://localhost:1883", "ANCHOR_MQTT_SITE": "lab"}
    assert pw.mqtt_configured(env)
    assert pw.mqtt_poke_topic(env) == "anchor/v1/sites/lab/plans/poke"


def test_inotify_or_poll_picks_up_file(tmp_path: Path):
    plans = tmp_path / ".plans"
    for lane in pw.WATCH_LANES:
        (plans / lane).mkdir(parents=True)
    watch = pw.open_watch(plans, env={})
    reasons: list[str] = []

    def drop():
        time.sleep(0.2)
        (plans / "features" / "arrived.local.md").write_text("# Plan: arrived\n")

    t = threading.Thread(target=drop)
    t.start()
    for r in pw.run_loop(watch, debounce_s=0.2, heartbeat_s=2.0, cycles=1):
        reasons.append(r)
    t.join(timeout=2)
    assert reasons, "watch should yield at least once"
    assert reasons[0] in {"inotify", "poll", "heartbeat"}


def test_work_once_watch_cycles_uses_existing_claim(tmp_path: Path, capsys):
    plans = tmp_path / ".plans"
    for lane in ("bugs", "features", "in-progress", "completed", "drafts",
                 "review-needed", "ambiguous", "blocked"):
        (plans / lane).mkdir(parents=True)
    (plans / "features" / "watch-me.md").write_text(
        "# Plan: watch-me\n\n"
        "- **Value:** medium\n"
        "- **Priority:** P2\n"
        "- **Slug:** watch-me\n"
        "- **Preferred models:** mid\n"
        "- **Assignee:** ai\n"
        "- **Depends on:** none\n\n"
        "## Goal\nG\n\n## Steps\n| 1 | x | | |\n\n## Done when\n- y\n"
    )
    code = work_once.main([
        "--root", str(tmp_path),
        "--tier", "mid",
        "--agent-id", "w1",
        "--print-only",
        "--watch",
        "--watch-debounce", "0.05",
        "--watch-heartbeat", "0.05",
        "--watch-cycles", "1",
        "--no-fit-check",
    ])
    out = capsys.readouterr()
    assert code == 0
    assert "watch-me" in out.out
    assert (plans / "in-progress" / "watch-me.md").is_file()
