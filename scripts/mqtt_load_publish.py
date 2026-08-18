#!/usr/bin/env python3
"""Publish a site inference-load level to the broker.

The operator-side counterpart to ``inference_load.py``: one command that says
"grid peak — local inference off" or "solar surplus — full load" to every Anchor
project subscribed to the site topic. Any MQTT publisher works (Home Assistant,
a lab controller, ``mosquitto_pub``); this is the convenient one.

Usage:
  python scripts/mqtt_load_publish.py off  --reason grid-peak
  python scripts/mqtt_load_publish.py low  --ttl 300 --max-concurrent 1
  python scripts/mqtt_load_publish.py high --reason solar-surplus --retain
  python scripts/mqtt_load_publish.py mid  --dry-run          # print, don't send
  python scripts/mqtt_load_publish.py off  --project          # one project only

Broker and topic come from the same configuration ``inference_load`` reads
(``ANCHOR_MQTT_URL``, ``ANCHOR_MQTT_SITE``, ``ANCHOR_MQTT_TOPIC``, …), so a
publisher and a consumer on one host agree by construction.

Retained messages are recommended: a worker that starts after the message was
sent still sees the current level. Pair ``--retain`` with a ``--ttl`` so a
retained "high" cannot outlive the condition that justified it.

Exit codes: 0 published (or --dry-run) · 1 broker unreachable · 2 usage/config
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from inference_load import (
    LEVELS,
    LoadPolicy,
    LoadPolicyError,
    load_config,
    normalize_level,
    write_cache,
)


def resolve_topic(cfg, *, scope: str = "auto", explicit: str = "") -> tuple[str, str]:
    """``(topic, scope)`` to publish to.

    ``ANCHOR_MQTT_PROJECT`` is the same variable consumers set, so defaulting to
    the project topic silently narrowed a site-wide cap to one project. The
    default is now the **site** topic; ``--project`` opts into the override and
    ``--topic`` forces a literal one.
    """
    if explicit:
        return explicit, "explicit"
    if scope == "project":
        if not cfg.project_topic:
            raise LoadPolicyError(
                "--project needs ANCHOR_MQTT_SITE and ANCHOR_MQTT_PROJECT set"
            )
        return cfg.project_topic, "project"
    return cfg.topic, "site"


def build_policy(level: str, *, reason: str = "", ttl: int | None = None,
                 max_concurrent: int | None = None,
                 allowed_tiers: list[str] | None = None,
                 site_id: str = "") -> LoadPolicy:
    """The policy this run would publish (also used by --dry-run and --mirror)."""
    return LoadPolicy(
        level=normalize_level(level),
        reason=reason,
        ttl_s=ttl,
        max_concurrent_local=max_concurrent,
        allowed_tiers=tuple(t.strip().lower() for t in allowed_tiers) if allowed_tiers else None,
        site_id=site_id,
        ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source="publish",
        received_at=time.time(),
    )


def publish(cfg, policy: LoadPolicy, topic: str, *, retain: bool = False,
            timeout: float = 10.0) -> int:
    """Send one message. Returns an exit code."""
    try:
        import paho.mqtt.client as mqtt  # type: ignore
    except ImportError:
        print("[mqtt_load_publish] needs paho-mqtt (pip install paho-mqtt)",
              file=sys.stderr)
        return 2
    if not cfg.broker_url:
        print("[mqtt_load_publish] no broker: set ANCHOR_MQTT_URL", file=sys.stderr)
        return 2
    if not topic:
        print("[mqtt_load_publish] no topic: set ANCHOR_MQTT_SITE or ANCHOR_MQTT_TOPIC",
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
    try:
        client.connect(host, port, keepalive=30)
    except OSError as exc:
        print(f"[mqtt_load_publish] cannot reach broker {host}:{port}: {exc}",
              file=sys.stderr)
        return 1
    client.loop_start()
    try:
        info = client.publish(topic, json.dumps(policy.to_payload()), qos=1,
                              retain=retain)
        info.wait_for_publish(timeout)
        published = info.is_published()
    finally:
        client.loop_stop()
        client.disconnect()
    if not published:
        print("[mqtt_load_publish] publish not confirmed within timeout", file=sys.stderr)
        return 1
    print(f"published {policy.level} → {topic}" + (" (retained)" if retain else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("level", help=f"{'|'.join(LEVELS)} (aliases: 0-3, full, none)")
    ap.add_argument("--root", default=".", help="project root for config (default: cwd)")
    ap.add_argument("--reason", default="", help="why, e.g. grid-peak / solar-surplus")
    ap.add_argument("--ttl", type=int, default=None,
                    help="ttl_s — consumers fall back to their fail-safe after this")
    ap.add_argument("--max-concurrent", type=int, default=None,
                    help="max_concurrent_local — ADVISORY metadata only; no consumer "
                         "enforces a concurrency cap today")
    ap.add_argument("--allowed-tiers", default="",
                    help="comma-separated fit tiers, overriding the level default")
    ap.add_argument("--project", action="store_true",
                    help="publish the per-project override topic instead of the site topic")
    ap.add_argument("--topic", default="",
                    help="publish to this literal topic (overrides --project)")
    ap.add_argument("--retain", action="store_true",
                    help="retain the message so late-starting workers see it")
    ap.add_argument("--dry-run", action="store_true", help="print the payload; send nothing")
    ap.add_argument("--mirror", action="store_true",
                    help="also write the local cache mirror (no broker needed)")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.root).resolve())
    try:
        policy = build_policy(
            args.level,
            reason=args.reason,
            ttl=args.ttl,
            max_concurrent=args.max_concurrent,
            allowed_tiers=[t for t in args.allowed_tiers.split(",") if t.strip()] or None,
            site_id=cfg.site_id,
        )
    except LoadPolicyError as exc:
        print(f"[mqtt_load_publish] {exc}", file=sys.stderr)
        return 2

    if args.retain and args.ttl is None:
        print("[mqtt_load_publish] warning: --retain without --ttl leaves this level "
              "standing until it is replaced", file=sys.stderr)

    try:
        topic, scope = resolve_topic(
            cfg, scope="project" if args.project else "site", explicit=args.topic
        )
    except LoadPolicyError as exc:
        print(f"[mqtt_load_publish] {exc}", file=sys.stderr)
        return 2

    # Always say where this is going — narrowing a site cap to one project by
    # accident is the kind of mistake that only shows up as an unexplained
    # still-running fleet.
    print(f"topic: {topic or '(unset)'} [{scope}]", file=sys.stderr)

    if args.dry_run:
        print(json.dumps(policy.to_payload(), indent=2))
        return 0

    code = publish(cfg, policy, topic, retain=args.retain)
    if args.mirror and cfg.cache_path:
        if code != 0:
            print(
                "[mqtt_load_publish] publish failed — not mirroring locally "
                "(a local-only level would leave this project out of step with "
                "the rest of the site)",
                file=sys.stderr,
            )
        else:
            write_cache(cfg.cache_path, policy,
                        "project" if scope == "project" else "site")
            print(f"mirrored → {cfg.cache_path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
