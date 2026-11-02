import json
import time
from pathlib import Path

import inference_load as il
import pytest

# -- level vocabulary -------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("off", "off"), ("LOW", "low"), (" mid ", "mid"), ("high", "high"),
        ("0", "off"), (0, "off"), (1, "low"), (2, "mid"), (3, "high"),
        ("full", "high"), ("unrestricted", "high"), ("none", "off"),
    ],
)
def test_normalize_level_accepts_aliases(raw, expected):
    assert il.normalize_level(raw) == expected


def test_unknown_level_raises_rather_than_defaulting_open():
    with pytest.raises(il.LoadPolicyError):
        il.normalize_level("medium")


def test_unknown_failsafe_raises():
    with pytest.raises(il.LoadPolicyError):
        il.normalize_failsafe("whatever")
    assert il.normalize_failsafe(None) == il.FAILSAFE_HOLD
    assert il.normalize_failsafe("last-known") == il.FAILSAFE_LAST_KNOWN


# -- level → action matrix --------------------------------------------------

@pytest.mark.parametrize(
    "level,allowed,denied",
    [
        ("off", [], ["small", "mid", "reasoner", "frontier"]),
        ("low", ["small"], ["mid", "reasoner", "frontier"]),
        ("mid", ["small", "mid"], ["reasoner", "frontier"]),
        ("high", ["small", "mid", "reasoner", "frontier"], []),
    ],
)
def test_level_tier_matrix(level, allowed, denied):
    policy = il.LoadPolicy(level=level)
    for tier in allowed:
        assert policy.allows_tier(tier), f"{level} should allow {tier}"
    for tier in denied:
        assert not policy.allows_tier(tier), f"{level} should deny {tier}"


def test_off_denies_even_with_explicit_allowed_tiers():
    policy = il.LoadPolicy(level="off", allowed_tiers=("small", "mid"))
    assert policy.tiers() == ()
    assert not policy.allows_tier("small")
    assert not policy.allows_local()


def test_explicit_allowed_tiers_override_the_level_default():
    policy = il.LoadPolicy(level="low", allowed_tiers=("small", "mid"))
    assert policy.allows_tier("mid")
    assert not policy.allows_tier("reasoner")


def test_unknown_tier_is_gated_by_level_only():
    assert il.LoadPolicy(level="low").allows_tier(None)
    assert not il.LoadPolicy(level="off").allows_tier(None)


# -- payload parsing --------------------------------------------------------

def test_from_payload_full_document():
    payload = json.dumps({
        "level": "low", "max_concurrent_local": 1,
        "allowed_tiers": ["small", "MID"], "reason": "grid-peak",
        "site_id": "garage", "ts": "2026-07-09T12:00:00Z", "ttl_s": 120,
    })
    policy = il.LoadPolicy.from_payload(payload)
    assert policy.level == "low"
    assert policy.max_concurrent_local == 1
    assert policy.allowed_tiers == ("small", "mid")
    assert policy.reason == "grid-peak"
    assert policy.ttl_s == 120
    assert policy.source == "mqtt"


@pytest.mark.parametrize(
    "payload",
    [
        "not json", "[]", "{}", '{"level": "medium"}',
        '{"level": "low", "allowed_tiers": "small"}',
        '{"level": "low", "ttl_s": "soon"}',
        '{"level": "low", "max_concurrent_local": "many"}',
    ],
)
def test_malformed_payloads_raise(payload):
    with pytest.raises(il.LoadPolicyError):
        il.LoadPolicy.from_payload(payload)


def test_payload_roundtrip():
    original = il.LoadPolicy(level="mid", reason="solar", ttl_s=60, site_id="lab")
    again = il.LoadPolicy.from_payload(original.to_payload())
    assert again.level == original.level
    assert again.reason == original.reason
    assert again.ttl_s == original.ttl_s


# -- freshness --------------------------------------------------------------

def test_ttl_measured_against_local_receipt_not_publisher_clock():
    now = time.time()
    # A publisher claiming a far-future ts cannot extend its own TTL: receipt wins.
    policy = il.LoadPolicy(level="high", ttl_s=60, ts="2099-01-01T00:00:00Z",
                           received_at=now - 120)
    assert policy.is_expired(now)
    fresh = il.LoadPolicy(level="high", ttl_s=60, received_at=now - 10)
    assert not fresh.is_expired(now)


def test_no_ttl_falls_back_to_the_consumer_ceiling():
    # Freshness is the consumer's guarantee: a publisher cannot opt out of expiry
    # by leaving ttl_s blank, which would strand a retained "high" forever.
    old = il.LoadPolicy(level="high", received_at=time.time() - 1000)
    assert old.is_expired(default_ttl_s=il.DEFAULT_MAX_AGE_SECONDS)
    assert not old.is_expired(default_ttl_s=0)        # ceiling explicitly disabled
    assert not old.is_expired()                       # no ceiling supplied by caller
    fresh = il.LoadPolicy(level="high", received_at=time.time())
    assert not fresh.is_expired(default_ttl_s=il.DEFAULT_MAX_AGE_SECONDS)


def test_publisher_ttl_wins_over_the_ceiling():
    policy = il.LoadPolicy(level="high", ttl_s=5, received_at=time.time() - 30)
    assert policy.effective_ttl(3600) == 5
    assert policy.is_expired(default_ttl_s=3600)


# -- fail-safe --------------------------------------------------------------

def _cfg(tmp_path, **kw):
    cfg = il.LoadConfig(enabled=True, cache_path=tmp_path / "cache.json")
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_failsafe_hold_denies_when_no_policy_present(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_HOLD)
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "off"
    assert policy.source == "failsafe:hold"
    assert not policy.allows_tier("small")


def test_failsafe_hold_applies_when_message_is_stale(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_HOLD)
    stale = il.LoadPolicy(level="high", ttl_s=30, received_at=time.time() - 300)
    il.write_cache(cfg.cache_path, stale)
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "off"
    assert policy.source == "failsafe:hold"


def test_failsafe_last_known_keeps_the_stale_level(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_LAST_KNOWN)
    stale = il.LoadPolicy(level="mid", reason="solar", ttl_s=30,
                          received_at=time.time() - 300)
    il.write_cache(cfg.cache_path, stale)
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "mid"
    assert policy.source.startswith("failsafe:last_known")
    assert not policy.is_expired()  # the fallback is not itself stale-checked


def test_failsafe_unrestricted_opens_up(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_UNRESTRICTED)
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "high"
    assert policy.allows_tier("frontier")


def test_fresh_policy_wins_over_failsafe(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_HOLD)
    il.write_cache(cfg.cache_path, il.LoadPolicy(level="low", ttl_s=600,
                                                 received_at=time.time()))
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "low"
    assert policy.allows_tier("small")
    assert not policy.allows_tier("mid")


# -- cache mirror -----------------------------------------------------------

def test_cache_roundtrip_preserves_receipt_time(tmp_path):
    path = tmp_path / "nested" / "inference-load.json"
    received = time.time() - 5
    il.write_cache(path, il.LoadPolicy(level="low", reason="peak", ttl_s=90,
                                       source="mqtt:test", received_at=received))
    back = il.read_cache(path)
    assert back is not None
    assert back.level == "low"
    assert back.reason == "peak"
    assert back.source == "mqtt:test"
    assert abs(back.received_at - received) < 0.01


@pytest.mark.parametrize("body", ["", "not json", "[]", '{"policy": {"level": "bogus"}}'])
def test_unreadable_cache_reads_as_none(tmp_path, body):
    path = tmp_path / "cache.json"
    path.write_text(body, encoding="utf-8")
    assert il.read_cache(path) is None


def test_missing_cache_reads_as_none(tmp_path):
    assert il.read_cache(tmp_path / "nope.json") is None


def test_corrupt_cache_falls_back_to_failsafe_not_to_open(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_HOLD)
    cfg.cache_path.write_text("{ truncated", encoding="utf-8")
    assert il.get_load_policy(tmp_path, cfg).level == "off"


# -- locality ---------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1", "http://127.0.0.1:8000/v1",
        "http://10.0.1.10:8000/v1", "http://192.168.1.5:8000/v1",
        "http://172.26.0.1:11434/v1", "http://box.local:8000/v1",
        "http://rack.lan:8000/v1", "http://[::1]:8000/v1",
    ],
)
def test_private_and_loopback_urls_are_local(url):
    assert il.is_local_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1", "https://api.x.ai/v1",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "https://api.anthropic.com/v1", "", None,
    ],
)
def test_public_urls_are_not_local(url):
    assert not il.is_local_base_url(url)


def test_explicit_local_flag_wins_over_heuristic():
    assert il.endpoint_is_local({"base_url": "https://api.example.com/v1", "local": True})
    assert not il.endpoint_is_local({"base_url": "http://10.0.1.10:8000/v1", "local": False})
    assert il.endpoint_is_local({"base_url": "https://api.example.com/v1", "local": "yes"})
    assert il.endpoint_is_local({"base_url": "http://10.0.1.10:8000/v1"})


# -- config -----------------------------------------------------------------

def test_governor_is_off_by_default(tmp_path):
    cfg = il.load_config(tmp_path, env={})
    assert not cfg.enabled
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "high"
    assert policy.source == "disabled"
    assert policy.allows_tier("frontier")


def test_broker_url_enables_and_derives_the_site_topic(tmp_path):
    cfg = il.load_config(tmp_path, env={
        "ANCHOR_MQTT_URL": "mqtt://broker:1883", "ANCHOR_MQTT_SITE": "garage",
    })
    assert cfg.enabled
    assert cfg.topic == "anchor/v1/sites/garage/inference/load"
    assert cfg.topics() == [cfg.topic]
    assert cfg.failsafe == il.FAILSAFE_HOLD


def test_project_topic_is_added_when_a_project_is_named(tmp_path):
    cfg = il.load_config(tmp_path, env={
        "ANCHOR_MQTT_URL": "mqtt://broker", "ANCHOR_MQTT_SITE": "garage",
        "ANCHOR_MQTT_PROJECT": "anchor",
    })
    assert cfg.project_topic == "anchor/v1/sites/garage/projects/anchor/load"
    assert cfg.topics()[-1] == cfg.project_topic


def test_explicit_topic_overrides_the_derived_one(tmp_path):
    cfg = il.load_config(tmp_path, env={"ANCHOR_MQTT_TOPIC": "custom/topic"})
    assert cfg.enabled
    assert cfg.topic == "custom/topic"


def test_existing_mirror_enables_the_governor_without_a_broker(tmp_path):
    (tmp_path / ".anchor").mkdir()
    il.write_cache(tmp_path / il.DEFAULT_CACHE_REL,
                   il.LoadPolicy(level="off", reason="sidecar"))
    cfg = il.load_config(tmp_path, env={})
    assert cfg.enabled
    assert il.get_load_policy(tmp_path, cfg).level == "off"


def test_disable_env_forces_the_governor_off(tmp_path):
    cfg = il.load_config(tmp_path, env={
        "ANCHOR_MQTT_URL": "mqtt://broker", "ANCHOR_MQTT_SITE": "s",
        "ANCHOR_LOAD_DISABLE": "1",
    })
    assert not cfg.enabled
    assert il.get_load_policy(tmp_path, cfg).source == "disabled"


def test_failsafe_read_from_env(tmp_path):
    cfg = il.load_config(tmp_path, env={
        "ANCHOR_MQTT_TOPIC": "t", "ANCHOR_LOAD_FAILSAFE": "last_known",
    })
    assert cfg.failsafe == il.FAILSAFE_LAST_KNOWN


def test_yaml_config_is_read_when_env_is_empty(tmp_path):
    pytest.importorskip("yaml")
    (tmp_path / ".anchor").mkdir()
    (tmp_path / ".anchor" / "mqtt-load.yaml").write_text(
        "url: mqtt://broker:1883\nsite: lab\nfailsafe: unrestricted\n", encoding="utf-8"
    )
    cfg = il.load_config(tmp_path, env={})
    assert cfg.enabled
    assert cfg.site_id == "lab"
    assert cfg.topic == "anchor/v1/sites/lab/inference/load"
    assert cfg.failsafe == il.FAILSAFE_UNRESTRICTED


def test_env_wins_over_yaml(tmp_path):
    pytest.importorskip("yaml")
    (tmp_path / ".anchor").mkdir()
    (tmp_path / ".anchor" / "mqtt-load.yaml").write_text(
        "site: lab\nfailsafe: unrestricted\n", encoding="utf-8"
    )
    cfg = il.load_config(tmp_path, env={"ANCHOR_MQTT_SITE": "garage",
                                        "ANCHOR_LOAD_FAILSAFE": "hold"})
    assert cfg.site_id == "garage"
    assert cfg.failsafe == il.FAILSAFE_HOLD


# -- consumer helper --------------------------------------------------------

def test_check_local_work_reports_reason_on_deny(tmp_path):
    cfg = _cfg(tmp_path)
    il.write_cache(cfg.cache_path, il.LoadPolicy(level="low", reason="grid-peak",
                                                 received_at=time.time()))
    allowed, reason, policy = il.check_local_work("reasoner", tmp_path, cfg)
    assert not allowed
    assert "not allowed at level=low" in reason
    assert policy.level == "low"

    allowed, reason, _ = il.check_local_work("small", tmp_path, cfg)
    assert allowed
    assert reason == ""


def test_deny_reason_mentions_the_publisher_reason_when_off(tmp_path):
    policy = il.LoadPolicy(level="off", reason="grid-peak", source="mqtt:site")
    assert "grid-peak" in policy.deny_reason("small")
    assert "capped" in policy.deny_reason("small")


# -- CLI --------------------------------------------------------------------

def test_cli_status_json_reports_disabled_by_default(tmp_path, capsys):
    assert il.main(["--root", str(tmp_path), "--status", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["enabled"] is False
    assert doc["level"] == "high"


def test_cli_set_writes_the_mirror_and_status_reads_it(tmp_path, capsys):
    assert il.main(["--root", str(tmp_path), "--set", "low", "--reason", "grid-peak"]) == 0
    capsys.readouterr()
    assert il.main(["--root", str(tmp_path), "--status", "--json", "--tier", "mid"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["level"] == "low"
    assert doc["allows_tier"] is False
    assert doc["allowed_tiers"] == ["small"]


def test_cli_set_rejects_an_unknown_level(tmp_path, capsys):
    assert il.main(["--root", str(tmp_path), "--set", "medium"]) == 2
    assert "unknown load level" in capsys.readouterr().err


# -- F2: an unparseable `local:` must not read as "not local" ---------------

def test_unrecognized_local_string_defers_to_the_url_heuristic():
    # Reading a mangled annotation as False would make marking an endpoint
    # WORSE than never annotating it — the governor would silently switch off.
    private = {"local": "tru e  # oops", "base_url": "http://10.0.1.10:8000/v1"}
    cloud = {"local": "??", "base_url": "https://api.example.com/v1"}
    assert il.endpoint_is_local(private)
    assert not il.endpoint_is_local(cloud)


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("TRUE", True), ("yes", True), ("on", True), ("1", True),
    ("false", False), ("no", False), ("off", False), ("0", False),
])
def test_explicit_local_tokens_are_honored_in_both_directions(raw, expected):
    ep = {"local": raw, "base_url": "http://10.0.1.10:8000/v1"}
    assert il.endpoint_is_local(ep) is expected


# -- F3: the broker URL must never carry credentials into emitted files -----

@pytest.mark.parametrize("url,expected", [
    ("mqtt://opuser:s3cret@broker.example:8883", "mqtt://broker.example:8883"),
    ("mqtts://user@host", "mqtts://host"),
    ("mqtt://u:p@[fe80::1]:1883", "mqtt://[fe80::1]:1883"),
    ("mqtt://broker:1883", "mqtt://broker:1883"),
    ("", ""),
    (None, ""),
])
def test_sanitize_broker_url_strips_userinfo_only(url, expected):
    assert il.sanitize_broker_url(url) == expected


def test_status_output_never_prints_broker_credentials(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANCHOR_MQTT_URL", "mqtt://opuser:s3cret@broker.example:8883")
    monkeypatch.setenv("ANCHOR_MQTT_SITE", "garage")
    assert il.main(["--root", str(tmp_path), "--status"]) == 0
    out = capsys.readouterr().out
    assert "s3cret" not in out
    assert "opuser" not in out
    assert "broker.example:8883" in out


# -- F1: a publisher cannot disable the fail-safe by omitting ttl_s ---------

def test_policy_without_ttl_expires_under_the_default_ceiling(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_HOLD)
    il.write_cache(cfg.cache_path,
                   il.LoadPolicy(level="high", reason="solar",
                                 received_at=time.time() - il.DEFAULT_MAX_AGE_SECONDS - 5))
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "off"
    assert policy.source == "failsafe:hold"


def test_ceiling_can_be_disabled_explicitly(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_HOLD, max_age_s=0)
    il.write_cache(cfg.cache_path,
                   il.LoadPolicy(level="high", received_at=time.time() - 999_999))
    assert il.get_load_policy(tmp_path, cfg).level == "high"


@pytest.mark.parametrize("raw,expected", [
    ("", il.DEFAULT_MAX_AGE_SECONDS), ("0", 0), ("none", 0), ("off", 0),
    ("60", 60), ("  120 ", 120),
])
def test_max_age_parsing(raw, expected):
    assert il._max_age(raw) == expected


@pytest.mark.parametrize("raw", ["soon", "-5", "1.5"])
def test_bad_max_age_is_refused(raw):
    with pytest.raises(il.LoadPolicyError):
        il._max_age(raw)


def test_max_age_read_from_env(tmp_path):
    cfg = il.load_config(tmp_path, env={"ANCHOR_MQTT_TOPIC": "t",
                                        "ANCHOR_LOAD_MAX_AGE": "60"})
    assert cfg.max_age_s == 60


def test_status_warns_when_the_publisher_set_no_ttl(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANCHOR_MQTT_TOPIC", "t")
    il.main(["--root", str(tmp_path), "--set", "high"])
    capsys.readouterr()
    il.main(["--root", str(tmp_path), "--status"])
    out = capsys.readouterr().out
    assert "no ttl_s" in out
    assert "max_age" in out


# -- F4: a project override outranks the site policy -----------------------

def _scoped_cfg(tmp_path):
    return il.LoadConfig(enabled=True, cache_path=tmp_path / "cache.json",
                         topic="anchor/v1/sites/g/inference/load",
                         project_topic="anchor/v1/sites/g/projects/p/load")


def test_project_override_survives_repeated_site_heartbeats(tmp_path):
    cfg = _scoped_cfg(tmp_path)
    il.apply_message(cfg, cfg.project_topic, '{"level": "off", "reason": "thermal"}')
    for _ in range(3):
        il.apply_message(cfg, cfg.topic, '{"level": "high"}')
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "off"
    assert policy.reason == "thermal"


def test_site_policy_applies_when_no_override_exists(tmp_path):
    cfg = _scoped_cfg(tmp_path)
    il.apply_message(cfg, cfg.topic, '{"level": "mid"}')
    assert il.get_load_policy(tmp_path, cfg).level == "mid"


def test_stale_override_falls_through_to_the_site_not_the_failsafe(tmp_path):
    cfg = _scoped_cfg(tmp_path)
    il.write_cache(cfg.cache_path,
                   il.LoadPolicy(level="off", ttl_s=30, received_at=time.time() - 600),
                   il.SCOPE_PROJECT)
    il.write_cache(cfg.cache_path,
                   il.LoadPolicy(level="mid", ttl_s=600, received_at=time.time()),
                   il.SCOPE_SITE)
    policy = il.get_load_policy(tmp_path, cfg)
    assert policy.level == "mid"          # abandoned override must not strand us
    assert policy.source != "failsafe:hold"


def test_both_scopes_stale_falls_back_to_the_failsafe(tmp_path):
    cfg = _scoped_cfg(tmp_path)
    for scope in (il.SCOPE_PROJECT, il.SCOPE_SITE):
        il.write_cache(cfg.cache_path,
                       il.LoadPolicy(level="high", ttl_s=30,
                                     received_at=time.time() - 600), scope)
    assert il.get_load_policy(tmp_path, cfg).level == "off"


def test_scope_for_topic():
    cfg = _scoped_cfg(Path("/tmp"))
    assert il.scope_for_topic(cfg, cfg.project_topic) == il.SCOPE_PROJECT
    assert il.scope_for_topic(cfg, cfg.topic) == il.SCOPE_SITE
    assert il.scope_for_topic(cfg, "some/other/topic") == il.SCOPE_SITE


def test_single_policy_mirror_still_reads_as_the_site_scope(tmp_path):
    # A hand-written sidecar mirror knows nothing about scopes.
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"level": "low"}), encoding="utf-8")
    entries = il.read_cache_entries(path)
    assert set(entries) == {il.SCOPE_SITE}
    assert entries[il.SCOPE_SITE].level == "low"


def test_write_cache_refuses_an_unknown_scope(tmp_path):
    with pytest.raises(il.LoadPolicyError):
        il.write_cache(tmp_path / "c.json", il.LoadPolicy(level="off"), "galaxy")


# -- M3 / N4: freshness edge cases -----------------------------------------

def test_retained_redelivery_without_ts_keeps_received_at(tmp_path):
    """Broker reconnect must not revive a ts-less retained high (review F1)."""
    from dataclasses import replace as dc_replace

    cfg = _cfg(tmp_path, topic="anchor/v1/sites/t/inference/load", max_age_s=900)
    payload = json.dumps({"level": "high"})
    first = il.apply_message(cfg, cfg.topic, payload, retain=True)
    assert first is not None
    aged_at = first.received_at - 10_000
    il.write_cache(cfg.cache_path, dc_replace(first, received_at=aged_at), il.SCOPE_SITE)

    again = il.apply_message(cfg, cfg.topic, payload, retain=True)
    assert again is not None
    assert again.received_at == aged_at
    assert again.is_expired(default_ttl_s=cfg.max_age_s)


def test_publisher_timestamp_can_only_make_a_message_look_older():
    now = time.time()
    # A retained message redelivered after a broker reconnect gets a fresh
    # received_at; the publisher's own (older) ts must still age it out.
    from datetime import datetime, timezone
    old_ts = datetime.fromtimestamp(now - 600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    redelivered = il.LoadPolicy(level="high", ttl_s=60, ts=old_ts, received_at=now)
    assert redelivered.is_expired(now)
    # …while a future ts cannot extend anything.
    future = il.LoadPolicy(level="high", ttl_s=60, ts="2099-01-01T00:00:00Z",
                           received_at=now - 120)
    assert future.is_expired(now)


def test_unparseable_timestamp_is_ignored_not_fatal():
    now = time.time()
    policy = il.LoadPolicy(level="high", ttl_s=60, ts="whenever", received_at=now)
    assert not policy.is_expired(now)
    assert il._parse_ts("whenever") is None
    assert il._parse_ts("") is None


def test_ttl_zero_means_stale_on_arrival_not_never():
    now = time.time()
    policy = il.LoadPolicy(level="high", ttl_s=0, received_at=now)
    assert policy.effective_ttl(900) == 0
    assert policy.is_expired(now + 1)


def test_ttl_zero_falls_back_to_the_failsafe(tmp_path):
    cfg = _cfg(tmp_path, failsafe=il.FAILSAFE_HOLD)
    il.write_cache(cfg.cache_path,
                   il.LoadPolicy(level="high", ttl_s=0, received_at=time.time() - 1))
    assert il.get_load_policy(tmp_path, cfg).level == "off"


# -- N5: the dead parameter is gone ----------------------------------------

def test_watch_has_no_unused_once_parameter():
    import inspect

    assert "once" not in inspect.signature(il.watch).parameters
