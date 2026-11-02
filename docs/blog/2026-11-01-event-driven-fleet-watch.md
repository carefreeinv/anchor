---
title: "Fleet workers wake on `.plans/` events, and `anchor fleet-watch` installs them"
authors: [carefree]
tags: [feature, tooling]
---

Background pullers no longer wait a full timer interval to see a newly
ready plan. `work_once.py --watch` stays up, coalesces filesystem bursts, and
still heartbeats when inotify is missing. From a terminal,
`anchor fleet-watch` inspects, prints, or installs those units.

<!-- truncate -->

## Event, then the same pull

A wake only triggers the existing `work_once` claim path. Fit, triage, leases,
and `Depends on` stay in the modules that already own them. Debounce collapses
a `git mv` into one pull. When inotify cannot attach, the watcher logs once
and polls. MQTT poke is optional: unconfigured, it is a no-op; configured, a
local filesystem wake can poke other hosts on
`anchor/v1/sites/{site}/plans/poke`.

Emitted systemd units are `Type=simple` with `--watch` by default, plus a
oneshot poll timer as the heartbeat. `watch=0` on a `--worker` spec restores
interval-only oneshots.

## `anchor fleet-watch`

Status, list, once, and emit wrap `fleet_watch.py`. `--install-user` is
operator-only: a non-TTY run, even with `--yes`, exits 3 and writes nothing.
Coding-agent `/fleet-watch` is the same flow; MCP may inspect or print units
and must not install daemons.
