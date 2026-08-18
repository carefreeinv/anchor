"""Publisher → subscriber round trip, without a broker.

``apply_message`` is exactly what the paho callback runs on a received message,
so feeding it the publisher's own payload proves the two halves agree on the
wire format.
"""
from __future__ import annotations

import json

import inference_load as il
import mqtt_load_publish as pub


def test_published_payload_is_accepted_by_the_subscriber(tmp_path):
    cfg = il.LoadConfig(enabled=True, cache_path=tmp_path / "cache.json")
    policy = pub.build_policy("low", reason="grid-peak", ttl=300, max_concurrent=1,
                              site_id="garage")
    wire = json.dumps(policy.to_payload())

    applied = il.apply_message(cfg, "anchor/v1/sites/garage/inference/load", wire)
    assert applied is not None
    assert applied.level == "low"
    assert applied.reason == "grid-peak"
    assert applied.ttl_s == 300
    assert applied.max_concurrent_local == 1

    # …and the consumer path now reports it
    resolved = il.get_load_policy(tmp_path, cfg)
    assert resolved.level == "low"
    assert resolved.allows_tier("small")
    assert not resolved.allows_tier("mid")


def test_subscriber_drops_a_malformed_message_without_widening_the_cap(tmp_path):
    cfg = il.LoadConfig(enabled=True, cache_path=tmp_path / "cache.json")
    il.write_cache(cfg.cache_path, pub.build_policy("off", reason="grid-peak"))

    assert il.apply_message(cfg, "site/topic", "{ not json") is None
    assert il.apply_message(cfg, "site/topic", '{"level": "wide-open"}') is None
    # The standing cap survives the bad messages.
    assert il.get_load_policy(tmp_path, cfg).level == "off"


def test_allowed_tiers_survive_the_round_trip(tmp_path):
    cfg = il.LoadConfig(enabled=True, cache_path=tmp_path / "cache.json")
    policy = pub.build_policy("low", allowed_tiers=["small", "MID"])
    applied = il.apply_message(cfg, "t", json.dumps(policy.to_payload()))
    assert applied.allowed_tiers == ("small", "mid")
    assert il.get_load_policy(tmp_path, cfg).allows_tier("mid")


def test_build_policy_stamps_an_iso_timestamp():
    policy = pub.build_policy("high")
    assert policy.ts.endswith("Z")
    assert policy.level == "high"


def test_build_policy_rejects_an_unknown_level():
    import pytest

    with pytest.raises(il.LoadPolicyError):
        pub.build_policy("medium")


def test_cli_dry_run_prints_payload_and_sends_nothing(tmp_path, capsys):
    code = pub.main(["off", "--root", str(tmp_path), "--reason", "grid-peak", "--dry-run"])
    assert code == 0
    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert doc["level"] == "off"
    assert doc["reason"] == "grid-peak"


def test_cli_rejects_an_unknown_level(tmp_path, capsys):
    assert pub.main(["medium", "--root", str(tmp_path), "--dry-run"]) == 2
    assert "unknown load level" in capsys.readouterr().err


def test_cli_warns_when_retaining_without_a_ttl(tmp_path, capsys):
    pub.main(["high", "--root", str(tmp_path), "--retain", "--dry-run"])
    assert "without --ttl" in capsys.readouterr().err


def test_cli_refuses_without_a_broker(tmp_path, capsys):
    assert pub.main(["off", "--root", str(tmp_path)]) == 2
    assert "no broker" in capsys.readouterr().err


# -- M4: the publisher must not silently narrow to one project -------------

def _cfg_with_project(tmp_path):
    return il.load_config(tmp_path, env={
        "ANCHOR_MQTT_URL": "mqtt://broker:1883",
        "ANCHOR_MQTT_SITE": "garage",
        "ANCHOR_MQTT_PROJECT": "anchor",
    })


def test_default_scope_is_the_site_even_when_a_project_is_configured(tmp_path):
    cfg = _cfg_with_project(tmp_path)
    topic, scope = pub.resolve_topic(cfg)
    assert scope == "site"
    assert topic == "anchor/v1/sites/garage/inference/load"


def test_project_flag_opts_into_the_override_topic(tmp_path):
    cfg = _cfg_with_project(tmp_path)
    topic, scope = pub.resolve_topic(cfg, scope="project")
    assert scope == "project"
    assert topic == "anchor/v1/sites/garage/projects/anchor/load"


def test_project_flag_without_config_is_refused(tmp_path):
    import pytest

    cfg = il.load_config(tmp_path, env={"ANCHOR_MQTT_SITE": "garage"})
    with pytest.raises(il.LoadPolicyError):
        pub.resolve_topic(cfg, scope="project")


def test_explicit_topic_wins(tmp_path):
    cfg = _cfg_with_project(tmp_path)
    assert pub.resolve_topic(cfg, scope="project", explicit="x/y") == ("x/y", "explicit")


def test_cli_always_reports_the_resolved_topic(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANCHOR_MQTT_SITE", "garage")
    monkeypatch.setenv("ANCHOR_MQTT_PROJECT", "anchor")
    pub.main(["off", "--root", str(tmp_path), "--dry-run"])
    err = capsys.readouterr().err
    assert "anchor/v1/sites/garage/inference/load [site]" in err


# -- M5: a failed publish must not leave a local-only level ----------------

def test_mirror_is_not_written_when_the_publish_fails(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANCHOR_MQTT_SITE", "garage")
    monkeypatch.setattr(pub, "publish", lambda *a, **k: 1)   # broker unreachable
    code = pub.main(["off", "--root", str(tmp_path), "--mirror"])
    assert code == 1
    assert not (tmp_path / il.DEFAULT_CACHE_REL).exists()
    assert "not mirroring locally" in capsys.readouterr().err


def test_mirror_is_written_on_a_successful_publish(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_MQTT_SITE", "garage")
    monkeypatch.setattr(pub, "publish", lambda *a, **k: 0)
    assert pub.main(["low", "--root", str(tmp_path), "--mirror"]) == 0
    entries = il.read_cache_entries(tmp_path / il.DEFAULT_CACHE_REL)
    assert entries[il.SCOPE_SITE].level == "low"
