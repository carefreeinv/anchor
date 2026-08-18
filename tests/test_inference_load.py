import json
import time

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


def test_no_ttl_never_expires():
    assert not il.LoadPolicy(level="high", received_at=0.0).is_expired(time.time())


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
