#!/usr/bin/env python3
"""Site inference-load policy — honor a centrally published cap on LOCAL inference.

An operator (home-energy automation, lab controller, UPS monitor) publishes one
**load level** for a site; every Anchor project subscribes and throttles its local
fleet work accordingly. Nothing here talks to cloud API tiers: this governs
**local / self-hosted** endpoints and the workers that drive them.

Opt-in. With no configuration the policy is ``high`` from source ``disabled`` and
behavior is exactly what it was before this module existed.

=============================================================================
Normative spec (v1)
=============================================================================

Topic
-----
::

    anchor/v1/sites/{site_id}/inference/load          # site policy (required)
    anchor/v1/sites/{site_id}/projects/{slug}/load    # optional per-project override

A project override, when configured and fresh, wins over the site topic.

Payload (JSON, retained recommended)
------------------------------------
::

    {
      "level": "low",                       # required
      "max_concurrent_local": 1,            # optional
      "allowed_tiers": ["small", "mid"],    # optional; overrides the level default
      "reason": "grid-peak",                # optional, free text
      "site_id": "garage",                  # optional, informational
      "ts": "2026-07-09T12:00:00Z",         # optional publisher timestamp
      "ttl_s": 120                          # optional freshness window
    }

Levels
------
``off | low | mid | high``. Accepted aliases: ``0|1|2|3``, ``full``→``high``,
``none``→``off``, ``unrestricted``→``high``. Unknown values are a parse error —
never a silent downgrade to "allow everything".

Level → allowed fit tiers (the default action matrix):

===== ============================== ==========================================
Level Allowed local fit tiers        Meaning
===== ============================== ==========================================
off   (none)                         No local inference at all
low   small                          Minimal: tiny/swarm executors only
mid   small, mid                     Normal local work; no heavy tiers
high  small, mid, reasoner, frontier Full local load within endpoint capacity
===== ============================== ==========================================

An explicit ``allowed_tiers`` in the payload replaces that row; ``level: off``
always denies regardless of ``allowed_tiers``.

Freshness and fail-safe
-----------------------
``ttl_s`` is measured against **local receipt time**, not the publisher's ``ts``
— a publisher with a skewed clock must not be able to hand out an immortal
"full load" message. When no fresh policy is available (never received, broker
down, TTL elapsed) the configured fail-safe applies:

======================= ==================================================
``hold`` (default)      Treat as ``off`` — safe for shared power/thermal
``last_known``          Keep the stale policy (labs, air-gapped runs)
``unrestricted``        Treat as ``high`` — opt out of the safety property
======================= ==================================================

Transport
---------
The subscriber (:func:`watch`, ``inference_load.py --watch``) is the only thing
that needs ``paho-mqtt``. It mirrors each accepted message to a JSON cache file
(default ``<root>/.anchor/inference-load.json``). Every consumer — ``work_once``,
``fleet_watch`` units, the model-fleet MCP — reads that mirror with the stdlib
only, so an inference-load check never adds a dependency, a socket, or a stall
to the claim path. Writing the mirror by hand (or from any other bus) is a
supported way to run this without MQTT at all.

Configuration
-------------
Environment (wins over file config):

===========================  =================================================
``ANCHOR_MQTT_URL``          ``mqtt://host:1883`` (``mqtts://`` for TLS)
``ANCHOR_MQTT_SITE``         site id — required to build the default topic
``ANCHOR_MQTT_TOPIC``        explicit topic, overrides the derived one
``ANCHOR_MQTT_PROJECT``      project slug for the per-project override topic
``ANCHOR_MQTT_USERNAME``     broker username
``ANCHOR_MQTT_PASSWORD``     broker password (never commit; env only)
``ANCHOR_LOAD_FAILSAFE``     ``hold`` | ``last_known`` | ``unrestricted``
``ANCHOR_LOAD_CACHE``        mirror path (default ``<root>/.anchor/inference-load.json``)
``ANCHOR_LOAD_DISABLE``      ``1`` to force the governor off
===========================  =================================================

Optional YAML at ``<root>/.anchor/mqtt-load.yaml`` or
``~/.config/anchor/mqtt-load.yaml`` with the same keys, lowercased and without
the prefix (``url``, ``site``, ``topic``, ``project``, ``failsafe``, ``cache``).

CLI
---
::

    python scripts/inference_load.py --status              # resolved policy + why
    python scripts/inference_load.py --watch               # subscribe, mirror to cache
    python scripts/inference_load.py --set low --reason x  # write mirror directly
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

LEVEL_OFF = "off"
LEVEL_LOW = "low"
LEVEL_MID = "mid"
LEVEL_HIGH = "high"
LEVELS = (LEVEL_OFF, LEVEL_LOW, LEVEL_MID, LEVEL_HIGH)

LEVEL_ALIASES = {
    "0": LEVEL_OFF, "1": LEVEL_LOW, "2": LEVEL_MID, "3": LEVEL_HIGH,
    "none": LEVEL_OFF, "stop": LEVEL_OFF, "paused": LEVEL_OFF,
    "full": LEVEL_HIGH, "unrestricted": LEVEL_HIGH,
}

# Level → allowed fit tiers. Fit tiers are the /work vocabulary (small|mid|
# reasoner|frontier); registry tiers are mapped to them by the caller.
TIERS_BY_LEVEL: dict[str, tuple[str, ...]] = {
    LEVEL_OFF: (),
    LEVEL_LOW: ("small",),
    LEVEL_MID: ("small", "mid"),
    LEVEL_HIGH: ("small", "mid", "reasoner", "frontier"),
}

FAILSAFE_HOLD = "hold"
FAILSAFE_LAST_KNOWN = "last_known"
FAILSAFE_UNRESTRICTED = "unrestricted"
FAILSAFES = (FAILSAFE_HOLD, FAILSAFE_LAST_KNOWN, FAILSAFE_UNRESTRICTED)

DEFAULT_CACHE_REL = ".anchor/inference-load.json"
DEFAULT_TOPIC_TMPL = "anchor/v1/sites/{site_id}/inference/load"
PROJECT_TOPIC_TMPL = "anchor/v1/sites/{site_id}/projects/{project}/load"


class LoadPolicyError(ValueError):
    """Malformed load payload. Never resolved by guessing a level."""


def normalize_level(value: object) -> str:
    """Map a published level (or alias) to one of :data:`LEVELS`."""
    raw = str(value).strip().lower()
    level = LEVEL_ALIASES.get(raw, raw)
    if level not in LEVELS:
        raise LoadPolicyError(
            f"unknown load level {value!r} (expected {'|'.join(LEVELS)} or an alias)"
        )
    return level


def normalize_failsafe(value: object | None) -> str:
    if value is None:
        return FAILSAFE_HOLD
    raw = str(value).strip().lower().replace("-", "_")
    if raw not in FAILSAFES:
        raise LoadPolicyError(
            f"unknown failsafe {value!r} (expected {'|'.join(FAILSAFES)})"
        )
    return raw


@dataclass(frozen=True)
class LoadPolicy:
    """A resolved site policy for local inference."""

    level: str = LEVEL_HIGH
    max_concurrent_local: int | None = None
    allowed_tiers: tuple[str, ...] | None = None
    reason: str = ""
    site_id: str = ""
    ts: str = ""
    ttl_s: int | None = None
    source: str = "default"
    received_at: float = 0.0

    # -- queries ---------------------------------------------------------
    def tiers(self) -> tuple[str, ...]:
        """Allowed fit tiers. ``off`` denies everything, whatever the payload said."""
        if self.level == LEVEL_OFF:
            return ()
        if self.allowed_tiers is not None:
            return self.allowed_tiers
        return TIERS_BY_LEVEL[self.level]

    def allows_local(self) -> bool:
        return self.level != LEVEL_OFF

    def allows_tier(self, tier: str | None) -> bool:
        """Is *tier* (a fit tier) allowed to run locally right now?"""
        if not self.allows_local():
            return False
        if tier is None:
            return True  # unknown tier: level gate only
        return str(tier).strip().lower() in self.tiers()

    def is_expired(self, now: float | None = None) -> bool:
        """TTL measured against local receipt, not the publisher's clock."""
        if not self.ttl_s:
            return False
        return (now if now is not None else time.time()) > self.received_at + self.ttl_s

    def describe(self) -> str:
        bits = [f"LOAD level={self.level}", f"source={self.source}"]
        if self.reason:
            bits.append(f"reason={self.reason}")
        if self.max_concurrent_local is not None:
            bits.append(f"max_concurrent_local={self.max_concurrent_local}")
        if self.allowed_tiers is not None:
            bits.append("allowed_tiers=" + ",".join(self.allowed_tiers))
        return " ".join(bits)

    def deny_reason(self, tier: str | None = None) -> str:
        """One-line explanation for a refusal (empty when nothing is denied)."""
        if not self.allows_local():
            why = f" ({self.reason})" if self.reason else ""
            return f"local inference is capped: level={self.level}{why} [source={self.source}]"
        if not self.allows_tier(tier):
            return (
                f"local tier {tier!r} not allowed at level={self.level} "
                f"(allowed: {', '.join(self.tiers()) or 'none'}) [source={self.source}]"
            )
        return ""

    # -- serialization ---------------------------------------------------
    @classmethod
    def from_payload(cls, payload: str | bytes | dict, *, source: str = "mqtt",
                     received_at: float | None = None) -> LoadPolicy:
        if isinstance(payload, (str, bytes)):
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise LoadPolicyError(f"payload is not JSON: {exc}") from exc
        else:
            data = payload
        if not isinstance(data, dict):
            raise LoadPolicyError(f"payload must be a JSON object, got {type(data).__name__}")
        if "level" not in data:
            raise LoadPolicyError("payload has no 'level'")

        tiers = data.get("allowed_tiers")
        if tiers is not None:
            if not isinstance(tiers, (list, tuple)) or not all(isinstance(t, str) for t in tiers):
                raise LoadPolicyError("'allowed_tiers' must be a list of strings")
            tiers = tuple(t.strip().lower() for t in tiers)

        concurrent = data.get("max_concurrent_local")
        if concurrent is not None:
            try:
                concurrent = int(concurrent)
            except (TypeError, ValueError) as exc:
                raise LoadPolicyError("'max_concurrent_local' must be an integer") from exc

        ttl = data.get("ttl_s")
        if ttl is not None:
            try:
                ttl = int(ttl)
            except (TypeError, ValueError) as exc:
                raise LoadPolicyError("'ttl_s' must be an integer") from exc

        return cls(
            level=normalize_level(data["level"]),
            max_concurrent_local=concurrent,
            allowed_tiers=tiers,
            reason=str(data.get("reason") or ""),
            site_id=str(data.get("site_id") or ""),
            ts=str(data.get("ts") or ""),
            ttl_s=ttl,
            source=source,
            received_at=received_at if received_at is not None else time.time(),
        )

    def to_payload(self) -> dict:
        out: dict = {"level": self.level}
        if self.max_concurrent_local is not None:
            out["max_concurrent_local"] = self.max_concurrent_local
        if self.allowed_tiers is not None:
            out["allowed_tiers"] = list(self.allowed_tiers)
        if self.reason:
            out["reason"] = self.reason
        if self.site_id:
            out["site_id"] = self.site_id
        if self.ts:
            out["ts"] = self.ts
        if self.ttl_s is not None:
            out["ttl_s"] = self.ttl_s
        return out


UNRESTRICTED = LoadPolicy(level=LEVEL_HIGH, source="disabled")


def _failsafe_policy(failsafe: str, stale: LoadPolicy | None) -> LoadPolicy:
    """Policy to use when no fresh message is available."""
    if failsafe == FAILSAFE_UNRESTRICTED:
        return LoadPolicy(level=LEVEL_HIGH, source="failsafe:unrestricted",
                          reason="no fresh load policy", received_at=time.time())
    if failsafe == FAILSAFE_LAST_KNOWN and stale is not None:
        return replace(stale, source=f"failsafe:last_known({stale.source})", ttl_s=None)
    return LoadPolicy(level=LEVEL_OFF, source="failsafe:hold",
                      reason="no fresh load policy", received_at=time.time())


# ---------------------------------------------------------------------------
# Endpoint locality
# ---------------------------------------------------------------------------

_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def is_local_base_url(base_url: str | None) -> bool:
    """Heuristic: does *base_url* point at self-hosted hardware?

    Loopback, RFC1918 / CGNAT / link-local addresses, and ``.local``/``.lan``
    hostnames count as local. Everything else — every public hostname — is
    treated as **not** local, so a mis-set policy can never silently block a
    cloud tier. An explicit ``local:`` on the endpoint always wins over this.
    """
    if not base_url:
        return False
    from urllib.parse import urlsplit

    host = (urlsplit(str(base_url)).hostname or "").strip().lower()
    if not host:
        return False
    if host in _LOCAL_HOSTNAMES:
        return True
    if host.endswith((".local", ".lan", ".internal", ".home", ".localdomain")):
        return True
    import ipaddress

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified
    )


def endpoint_is_local(endpoint: dict) -> bool:
    """Locality for a registry entry: explicit ``local:`` wins, else the heuristic."""
    explicit = endpoint.get("local")
    if explicit is not None:
        if isinstance(explicit, str):
            return explicit.strip().lower() in {"1", "true", "yes", "on"}
        return bool(explicit)
    return is_local_base_url(endpoint.get("base_url"))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class LoadConfig:
    enabled: bool = False
    broker_url: str = ""
    site_id: str = ""
    topic: str = ""
    project: str = ""
    project_topic: str = ""
    username: str = ""
    password: str = ""
    failsafe: str = FAILSAFE_HOLD
    cache_path: Path | None = None

    def topics(self) -> list[str]:
        """Subscribed topics, project override last (it wins when fresh)."""
        return [t for t in (self.topic, self.project_topic) if t]


def _read_yaml_config(root: Path) -> dict:
    """Optional YAML config; missing file or missing PyYAML is not an error."""
    candidates = [
        root / ".anchor" / "mqtt-load.yaml",
        Path.home() / ".config" / "anchor" / "mqtt-load.yaml",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            import yaml  # type: ignore
        except ImportError:
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            # accept either a flat mapping or a top-level "inference_load:" section
            section = data.get("inference_load")
            return section if isinstance(section, dict) else data
    return {}


def load_config(root: Path | str = ".", env: dict | None = None) -> LoadConfig:
    """Resolve configuration from env (wins) over optional YAML."""
    root = Path(root)
    env = os.environ if env is None else env
    filecfg = _read_yaml_config(root)

    def pick(env_key: str, file_key: str, default: str = "") -> str:
        val = env.get(env_key)
        if val is None or val == "":
            val = filecfg.get(file_key, default)
        return str(val or "").strip()

    site_id = pick("ANCHOR_MQTT_SITE", "site")
    project = pick("ANCHOR_MQTT_PROJECT", "project")
    topic = pick("ANCHOR_MQTT_TOPIC", "topic")
    if not topic and site_id:
        topic = DEFAULT_TOPIC_TMPL.format(site_id=site_id)
    project_topic = ""
    if site_id and project:
        project_topic = PROJECT_TOPIC_TMPL.format(site_id=site_id, project=project)

    cache = pick("ANCHOR_LOAD_CACHE", "cache")
    cache_path = Path(cache) if cache else root / DEFAULT_CACHE_REL

    cfg = LoadConfig(
        broker_url=pick("ANCHOR_MQTT_URL", "url"),
        site_id=site_id,
        topic=topic,
        project=project,
        project_topic=project_topic,
        username=pick("ANCHOR_MQTT_USERNAME", "username"),
        password=env.get("ANCHOR_MQTT_PASSWORD", "") or str(filecfg.get("password", "") or ""),
        failsafe=normalize_failsafe(pick("ANCHOR_LOAD_FAILSAFE", "failsafe") or None),
        cache_path=cache_path,
    )
    # Opt-in: a broker, an explicit topic, or an existing mirror turns it on.
    disabled = str(env.get("ANCHOR_LOAD_DISABLE", "")).strip().lower() in {"1", "true", "yes"}
    cfg.enabled = not disabled and bool(
        cfg.broker_url or cfg.topic or (cfg.cache_path and cfg.cache_path.is_file())
    )
    return cfg


# ---------------------------------------------------------------------------
# Cache mirror (the read path every consumer uses)
# ---------------------------------------------------------------------------

def read_cache(path: Path) -> LoadPolicy | None:
    """Read the mirrored policy, or None when absent/unreadable/malformed."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    payload = raw.get("policy") if isinstance(raw.get("policy"), dict) else raw
    try:
        policy = LoadPolicy.from_payload(
            payload,
            source=str(raw.get("source") or "file"),
            received_at=float(raw.get("received_at") or 0.0),
        )
    except (LoadPolicyError, TypeError, ValueError):
        return None
    return policy


def write_cache(path: Path, policy: LoadPolicy) -> Path:
    """Mirror *policy* to *path* atomically. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "policy": policy.to_payload(),
        "source": policy.source,
        "received_at": policy.received_at or time.time(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def get_load_policy(root: Path | str = ".", config: LoadConfig | None = None,
                    *, now: float | None = None) -> LoadPolicy:
    """The effective policy for this project. Never raises, never blocks.

    Disabled (the default) → ``high`` from source ``disabled``. Enabled → the
    mirrored policy when fresh, else the configured fail-safe.
    """
    cfg = config if config is not None else load_config(root)
    if not cfg.enabled:
        return UNRESTRICTED
    policy = read_cache(cfg.cache_path) if cfg.cache_path else None
    if policy is None:
        return _failsafe_policy(cfg.failsafe, None)
    if policy.is_expired(now):
        return _failsafe_policy(cfg.failsafe, policy)
    return policy


def check_local_work(tier: str | None, root: Path | str = ".",
                     config: LoadConfig | None = None) -> tuple[bool, str, LoadPolicy]:
    """``(allowed, reason, policy)`` for local work at fit tier *tier*."""
    policy = get_load_policy(root, config)
    if policy.allows_tier(tier):
        return True, "", policy
    return False, policy.deny_reason(tier), policy


def registry_tier_to_fit(tier: str | None) -> str | None:
    """Map a registry tier (``swarm``, ``executor-heavy``, …) to a fit tier.

    The mapping lives in ``plan_select`` and is not duplicated here: without it
    the tier is unknown and only the level gate applies.
    """
    if not tier:
        return None
    try:
        from plan_select import REGISTRY_TIER_TO_FIT
    except ImportError:
        return None
    return REGISTRY_TIER_TO_FIT.get(str(tier).strip().lower())


LOAD_LIMITED = "LOAD-LIMITED"


def endpoint_refusal(endpoint, root: Path | str = ".",
                     config: LoadConfig | None = None) -> str | None:
    """Structured refusal when the site policy bars *endpoint*, else None.

    Duck-typed on ``.is_local`` / ``.tier`` / ``.name`` so it works for an
    ``anchor_client.Endpoint`` without importing it (that module imports this
    one). Cloud endpoints are never refused, and the check only reads a local
    file — it can never block or hang a delegate path.
    """
    if not getattr(endpoint, "is_local", False):
        return None
    cfg = config if config is not None else load_config(root)
    if not cfg.enabled:
        return None
    tier = getattr(endpoint, "tier", None)
    allowed, reason, policy = check_local_work(registry_tier_to_fit(tier), root, cfg)
    if allowed:
        return None
    name = getattr(endpoint, "name", "endpoint")
    return (
        f"{LOAD_LIMITED}: {name} [{tier}] is local and {reason}\n"
        f"{policy.describe()}\n"
        "No work was sent. Route to a cloud tier, wait for the cap to lift, or "
        "run the step yourself."
    )


# ---------------------------------------------------------------------------
# MQTT subscriber (the only thing that needs paho-mqtt)
# ---------------------------------------------------------------------------

def apply_message(cfg: LoadConfig, topic: str, payload: str | bytes) -> LoadPolicy | None:
    """Validate one received message and mirror it. Returns None if rejected.

    Split out from the paho callback so the accept/reject contract is testable
    without a broker: a malformed payload is dropped, never applied, and can
    never widen the cap.
    """
    try:
        policy = LoadPolicy.from_payload(payload, source=f"mqtt:{topic}")
    except LoadPolicyError as exc:
        print(f"[inference_load] ignored bad payload on {topic}: {exc}", file=sys.stderr)
        return None
    write_cache(cfg.cache_path, policy)
    return policy


def watch(cfg: LoadConfig, *, once: bool = False, timeout: float | None = None,
          on_update=None) -> int:
    """Subscribe and mirror accepted messages to the cache. Returns an exit code."""
    try:
        import paho.mqtt.client as mqtt  # type: ignore
    except ImportError:
        print(
            "[inference_load] --watch needs paho-mqtt (pip install paho-mqtt); "
            "the read path does not",
            file=sys.stderr,
        )
        return 2
    if not cfg.broker_url:
        print("[inference_load] no broker: set ANCHOR_MQTT_URL", file=sys.stderr)
        return 2
    if not cfg.topics():
        print("[inference_load] no topic: set ANCHOR_MQTT_SITE or ANCHOR_MQTT_TOPIC",
              file=sys.stderr)
        return 2

    from urllib.parse import urlsplit

    parts = urlsplit(cfg.broker_url)
    host = parts.hostname or "localhost"
    tls = parts.scheme in {"mqtts", "ssl", "mqtt+ssl"}
    port = parts.port or (8883 if tls else 1883)

    client = mqtt.Client()
    if cfg.username:
        client.username_pw_set(cfg.username, cfg.password or None)
    if tls:
        client.tls_set()

    state = {"received": 0}

    def _on_connect(cli, _userdata, _flags, rc):  # noqa: ANN001 — paho callback shape
        if rc != 0:
            print(f"[inference_load] connect failed rc={rc}", file=sys.stderr)
            return
        for topic in cfg.topics():
            cli.subscribe(topic)
            print(f"[inference_load] subscribed {topic}", file=sys.stderr)

    def _on_message(_cli, _userdata, msg):  # noqa: ANN001 — paho callback shape
        # Project topic wins over site topic; both are mirrored to the same file
        # and the last fresh message decides.
        policy = apply_message(cfg, msg.topic, msg.payload)
        if policy is None:
            return
        state["received"] += 1
        print(f"[inference_load] {policy.describe()}", file=sys.stderr)
        if on_update is not None:
            on_update(policy)

    client.on_connect = _on_connect
    client.on_message = _on_message
    try:
        client.connect(host, port, keepalive=60)
    except OSError as exc:
        print(f"[inference_load] cannot reach broker {host}:{port}: {exc}", file=sys.stderr)
        return 1

    deadline = None if timeout is None else time.time() + timeout
    client.loop_start()
    try:
        while True:
            time.sleep(0.2)
            if once and state["received"]:
                break
            if deadline is not None and time.time() > deadline:
                break
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
    return 0 if state["received"] or not once else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("=====")[0].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", default=".", help="project root (default: cwd)")
    ap.add_argument("--status", action="store_true",
                    help="print the resolved policy and where it came from")
    ap.add_argument("--json", action="store_true", help="machine-readable --status")
    ap.add_argument("--watch", action="store_true",
                    help="subscribe to the broker and mirror updates to the cache")
    ap.add_argument("--timeout", type=float, default=None,
                    help="with --watch, stop after N seconds")
    ap.add_argument("--set", metavar="LEVEL",
                    help=f"write the cache mirror directly ({'|'.join(LEVELS)})")
    ap.add_argument("--reason", default="", help="with --set, the published reason")
    ap.add_argument("--ttl", type=int, default=None, help="with --set, ttl_s")
    ap.add_argument("--tier", help="with --status, also answer allow/deny for this fit tier")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    cfg = load_config(root)

    if args.set:
        try:
            level = normalize_level(args.set)
        except LoadPolicyError as exc:
            print(f"[inference_load] {exc}", file=sys.stderr)
            return 2
        policy = LoadPolicy(level=level, reason=args.reason, ttl_s=args.ttl,
                            site_id=cfg.site_id, source="file:set",
                            received_at=time.time())
        path = write_cache(cfg.cache_path, policy)
        print(f"{policy.describe()} → {path}")
        return 0

    if args.watch:
        return watch(cfg, timeout=args.timeout)

    policy = get_load_policy(root, cfg)
    if args.json:
        doc = {
            **policy.to_payload(),
            "source": policy.source,
            "enabled": cfg.enabled,
            "allowed_tiers": list(policy.tiers()),
            "cache": str(cfg.cache_path),
        }
        if args.tier:
            doc["allows_tier"] = policy.allows_tier(args.tier)
        print(json.dumps(doc, indent=2))
        return 0

    print(policy.describe())
    print(f"allowed local tiers: {', '.join(policy.tiers()) or 'none'}")
    print(f"enabled={cfg.enabled} failsafe={cfg.failsafe} cache={cfg.cache_path}")
    if args.tier:
        allowed, reason, _ = check_local_work(args.tier, root, cfg)
        print(f"tier {args.tier}: {'ALLOW' if allowed else 'DENY — ' + reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
