---
title: Cap your local fleet from one MQTT message
authors: [carefree]
tags: [feature, tooling, fleet]
---

Grid peak at 4pm shouldn't mean walking around the house stopping workers.

<!-- truncate -->

Anchor's local fleet has always pulled `.plans/` and driven local endpoints until
something gave out — the box, the API, or your patience. There was no shared way
to say *stop using my hardware for the next two hours*. Now there is: publish one
**load level** to an MQTT topic and every Anchor project on the site honors it.

```bash
python scripts/mqtt_load_publish.py off  --reason grid-peak
python scripts/mqtt_load_publish.py high --reason solar-surplus --ttl 900 --retain
```

Levels are `off | low | mid | high`, and they map to the fit tiers you already
route by: `low` allows `small` workers only, `mid` allows `small` and `mid`,
`high` allows everything your endpoints can serve. A worker whose tier isn't
allowed refuses **before it claims a plan** and exits idle — the backlog is left
untouched rather than parked under a lease nobody is running.

This governs **local** inference only. Cloud API tiers are never blocked by a
site power policy, and an endpoint counts as local either because you said so
(`local: true` in `endpoints.yaml`) or because its base URL is loopback, a
private range, or a `.local`-style hostname. Every public hostname is treated as
not-local, so a mis-set policy can't quietly strand your frontier routing.

## The part worth stealing

MQTT lives in exactly one place: the subscriber.

```bash
python scripts/inference_load.py --watch     # the only paho-mqtt user
```

It validates each message and mirrors it to `.anchor/inference-load.json`. Every
consumer — `work_once`, the timers `fleet_watch` emits, the model-fleet MCP —
reads that file with the standard library. So a load check adds no dependency,
no socket, and no stall to the claim path; a broker outage can't hang a worker;
and CI needs no broker to test any of it.

It also means you can run the whole feature without MQTT:

```bash
python scripts/inference_load.py --set low --reason grid-peak
python scripts/inference_load.py --status --tier mid
```

Any sidecar that can write a JSON file is a valid publisher.

## Failing toward off

Two details decide whether a governor like this is actually safe.

First, `ttl_s` is measured against **local receipt time**, not the publisher's
`ts` field. A publisher with a skewed clock — or a stale retained message —
cannot hand out an immortal "full load".

Second, when no fresh policy is available, the default fail-safe is `hold`:
treat it as `off`. A broker that dies at 2am doesn't silently un-cap your rack.
Labs that would rather keep working can set `ANCHOR_LOAD_FAILSAFE=last_known`,
and `unrestricted` is there for anyone who wants to opt out of the safety
property explicitly. A malformed message is dropped rather than applied, so a
bad payload can never widen the cap either.

## Where it shows up

`work_once` refuses with a reason you can read in a journal line. The model-fleet
MCP returns a structured `LOAD-LIMITED` refusal from `delegate` instead of
sending work, and refuses `delegate_parallel_review` outright rather than quietly
running one of its two independent critic passes. `fleet_health` still pings —
you need to see a box come back before the cap lifts — but labels capped
endpoints, and `list_fleet` shows the current level.

Timer-driven workers get a clean environment, so `fleet_watch` copies the load
settings into the units it emits. It deliberately does **not** write the broker
password into a unit file; those are world-readable. Use a credential file or a
drop-in.

It's opt-in throughout. With nothing configured, the resolved level is `high`
from source `disabled` and nothing about your fleet changes. Full contract:
[Site load via MQTT](/tooling/site-load).
