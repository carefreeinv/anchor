#!/usr/bin/env python3
"""Wake a work_once pull when ``.plans/`` ready lanes change.

Event-driven companion to interval polling: a filesystem watch (inotify on
Linux, long-poll fallback elsewhere) plus an optional MQTT poke. The event
only *triggers* the existing claim path — this module never claims, fits, or
leases.

Usage (library):
  watch = open_watch(plans_root)
  for reason in run_loop(watch, debounce_s=0.4, heartbeat_s=300):
      work_once.pick_claim_one(...)
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import select
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

WATCH_LANES = ("bugs", "features", "in-progress")
DEFAULT_DEBOUNCE_S = 0.4
DEFAULT_HEARTBEAT_S = 300.0
MQTT_PLANS_SUFFIX = "plans/poke"

_IN_CLOEXEC = 0x80000
_IN_NONBLOCK = 0x800
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CLOSE_WRITE = 0x00000008
_IN_MASK = _IN_CREATE | _IN_DELETE | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_CLOSE_WRITE

_logged_fallback = False


class Watch(Protocol):
    """One source of pokes. ``wait`` returns a reason string or None on timeout."""

    def wait(self, timeout_s: float) -> str | None: ...

    def close(self) -> None: ...


class PollWatch:
    """Long-poll fallback: sleep until timeout, then report ``poll``."""

    def wait(self, timeout_s: float) -> str | None:
        time.sleep(max(0.0, timeout_s))
        return "poll"

    def close(self) -> None:
        return None


class InotifyWatch:
    """Watch ``bugs/``, ``features/``, ``in-progress/`` via libc inotify."""

    def __init__(self, fds: list[int], libc: ctypes.CDLL):
        self._fds = fds
        self._libc = libc
        self._closed = False

    def wait(self, timeout_s: float) -> str | None:
        if self._closed:
            return None
        ready, _, _ = select.select(self._fds, [], [], max(0.0, timeout_s))
        if not ready:
            return None
        for fd in ready:
            try:
                os.read(fd, 4096)
            except BlockingIOError:
                continue
        return "inotify"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds = []


class CompositeWatch:
    """First poke from any child wins; remaining children keep running."""

    def __init__(self, children: list[Watch]):
        self._children = children

    def wait(self, timeout_s: float) -> str | None:
        if not self._children:
            time.sleep(max(0.0, timeout_s))
            return "poll"
        deadline = time.monotonic() + max(0.0, timeout_s)
        slice_s = max(0.05, min(0.25, timeout_s if timeout_s > 0 else 0.25))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            for child in self._children:
                reason = child.wait(min(slice_s, remaining))
                if reason:
                    return reason

    def close(self) -> None:
        for child in self._children:
            child.close()


class QueueWatch:
    """Test double: reasons pushed from another thread or the test itself."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._q: list[str] = []
        self._closed = False

    def poke(self, reason: str = "test") -> None:
        with self._cv:
            self._q.append(reason)
            self._cv.notify_all()

    def wait(self, timeout_s: float) -> str | None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._cv:
            while not self._q and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cv.wait(remaining)
            if self._q:
                return self._q.pop(0)
            return None

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()


def _try_inotify(plans_root: Path) -> InotifyWatch | None:
    libc_name = ctypes.util.find_library("c")
    if not libc_name:
        return None
    try:
        libc = ctypes.CDLL(libc_name, use_errno=True)
    except OSError:
        return None
    if not hasattr(libc, "inotify_init1") or not hasattr(libc, "inotify_add_watch"):
        return None
    libc.inotify_init1.restype = ctypes.c_int
    libc.inotify_add_watch.restype = ctypes.c_int
    fds: list[int] = []
    try:
        for lane in WATCH_LANES:
            path = plans_root / lane
            path.mkdir(parents=True, exist_ok=True)
            fd = libc.inotify_init1(_IN_CLOEXEC | _IN_NONBLOCK)
            if fd < 0:
                raise OSError(ctypes.get_errno(), "inotify_init1")
            wd = libc.inotify_add_watch(
                ctypes.c_int(fd),
                os.fsencode(str(path)),
                ctypes.c_uint32(_IN_MASK),
            )
            if wd < 0:
                os.close(fd)
                raise OSError(ctypes.get_errno(), f"inotify_add_watch {path}")
            fds.append(fd)
    except OSError:
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        return None
    return InotifyWatch(fds, libc)


def _log_fallback_once() -> None:
    global _logged_fallback
    if _logged_fallback:
        return
    _logged_fallback = True
    print(
        "[plan_watch] inotify unavailable; falling back to poll heartbeat",
        file=sys.stderr,
    )


def mqtt_poke_topic(env: dict[str, str] | None = None) -> str | None:
    """Topic subscribers treat as a poke. None when MQTT plans-watch is off."""
    src = os.environ if env is None else env
    explicit = (src.get("ANCHOR_MQTT_PLANS_TOPIC") or "").strip()
    if explicit:
        return explicit
    site = (src.get("ANCHOR_MQTT_SITE") or "").strip()
    if not site:
        return None
    return f"anchor/v1/sites/{site}/{MQTT_PLANS_SUFFIX}"


def mqtt_configured(env: dict[str, str] | None = None) -> bool:
    src = os.environ if env is None else env
    url = (src.get("ANCHOR_MQTT_URL") or "").strip()
    return bool(url) and mqtt_poke_topic(src) is not None


class MqttPokeWatch:
    """Subscribe to the plans poke topic. No-op when broker/paho missing."""

    def __init__(self, inner: QueueWatch, client: object | None):
        self._inner = inner
        self._client = client

    def wait(self, timeout_s: float) -> str | None:
        return self._inner.wait(timeout_s)

    def close(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                loop_stop = getattr(client, "loop_stop", None)
                if callable(loop_stop):
                    loop_stop()
                disconnect = getattr(client, "disconnect", None)
                if callable(disconnect):
                    disconnect()
            except Exception:
                pass
        self._inner.close()


def open_mqtt_watch(env: dict[str, str] | None = None) -> Watch | None:
    """Return a subscriber, or None when unconfigured / paho missing."""
    src = os.environ if env is None else env
    if not mqtt_configured(src):
        return None
    try:
        import paho.mqtt.client as mqtt  # type: ignore
    except ImportError:
        return None
    topic = mqtt_poke_topic(src)
    url = (src.get("ANCHOR_MQTT_URL") or "").strip()
    if not topic or not url:
        return None
    inner = QueueWatch()

    def on_message(_client, _userdata, _msg) -> None:
        inner.poke("mqtt")

    try:
        from urllib.parse import urlparse

        parts = urlparse(url)
        host = parts.hostname or "localhost"
        port = parts.port or (8883 if parts.scheme in {"mqtts", "ssl"} else 1883)
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except Exception:
            client = mqtt.Client()
        user = (src.get("ANCHOR_MQTT_USERNAME") or parts.username or "").strip()
        password = (src.get("ANCHOR_MQTT_PASSWORD") or parts.password or "")
        if user:
            client.username_pw_set(user, password or None)
        client.on_message = on_message
        client.connect(host, port, keepalive=30)
        client.subscribe(topic)
        client.loop_start()
    except Exception:
        inner.close()
        return None
    return MqttPokeWatch(inner, client)


def publish_mqtt_poke(env: dict[str, str] | None = None) -> bool:
    """Fire-and-forget poke for other hosts. False when unconfigured."""
    src = os.environ if env is None else env
    if not mqtt_configured(src):
        return False
    try:
        import paho.mqtt.client as mqtt  # type: ignore
    except ImportError:
        return False
    topic = mqtt_poke_topic(src)
    url = (src.get("ANCHOR_MQTT_URL") or "").strip()
    if not topic or not url:
        return False
    try:
        from urllib.parse import urlparse

        parts = urlparse(url)
        host = parts.hostname or "localhost"
        port = parts.port or 1883
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except Exception:
            client = mqtt.Client()
        user = (src.get("ANCHOR_MQTT_USERNAME") or parts.username or "").strip()
        password = (src.get("ANCHOR_MQTT_PASSWORD") or parts.password or "")
        if user:
            client.username_pw_set(user, password or None)
        client.connect(host, port, keepalive=10)
        client.publish(topic, b"poke", qos=0, retain=False)
        client.disconnect()
        return True
    except Exception:
        return False


def open_watch(plans_root: Path, *, env: dict[str, str] | None = None) -> Watch:
    """Inotify when it works, else poll. MQTT subscriber stacked when configured."""
    children: list[Watch] = []
    inotify = _try_inotify(plans_root)
    if inotify is not None:
        children.append(inotify)
    else:
        _log_fallback_once()
        children.append(PollWatch())
    mqtt = open_mqtt_watch(env)
    if mqtt is not None:
        children.append(mqtt)
    if len(children) == 1:
        return children[0]
    return CompositeWatch(children)


def run_loop(
    watch: Watch,
    *,
    debounce_s: float = DEFAULT_DEBOUNCE_S,
    heartbeat_s: float = DEFAULT_HEARTBEAT_S,
    cycles: int | None = None,
    on_event: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] | None = None,
) -> Iterator[str]:
    """Yield a coalesced reason whenever a pull should run.

    Filesystem bursts (``git mv``) collapse into one yield after ``debounce_s``.
    ``heartbeat`` fires when nothing has poked for ``heartbeat_s``.
    """
    sleep = sleeper or time.sleep
    n = 0
    last_pull = clock()
    pending: str | None = None
    pending_at: float | None = None
    try:
        while cycles is None or n < cycles:
            now = clock()
            if pending is not None and pending_at is not None:
                wait = max(0.0, debounce_s - (now - pending_at))
            else:
                wait = max(0.0, heartbeat_s - (now - last_pull))
            reason = watch.wait(wait)
            now = clock()
            if reason:
                if on_event:
                    on_event(reason)
                if pending is None:
                    pending = reason
                    pending_at = now
                    if debounce_s <= 0:
                        last_pull = now
                        n += 1
                        yield pending
                        pending = None
                        pending_at = None
                    continue
                pending = reason
                continue
            if pending is not None and pending_at is not None:
                if now - pending_at >= debounce_s:
                    last_pull = now
                    n += 1
                    out = pending
                    pending = None
                    pending_at = None
                    yield out
                    continue
            if now - last_pull >= heartbeat_s:
                last_pull = now
                n += 1
                yield "heartbeat"
                continue
            sleep(min(0.05, wait if wait > 0 else 0.05))
    finally:
        watch.close()


def lane_dirs(plans_root: Path) -> list[Path]:
    return [plans_root / lane for lane in WATCH_LANES]
