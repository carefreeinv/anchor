#!/usr/bin/env python3
"""Shared plan leases on an orphan ``leases`` branch.

Why: ``.plans/.leases/`` is gitignored and machine-local, so two developers on
one remote cannot see each other's claims. This module publishes leases to a
dedicated orphan branch that is the **only** place lease files are ever
committed, so a second clone can see a live claim before it claims.

Protocol
--------
* **Branch** ``leases`` (orphan: no shared history with code branches). Its tree
  holds only ``leases/<slug>.json``. It is never merged; ``/work``, ``/review``
  and ``/release`` never touch it.
* **Key** is the plan *slug* (file basename without ``.md``), not its lane path,
  because a plan moves ``bugs/`` -> ``in-progress/`` -> ``review-needed/``.
* **Payload**: ``slug, agent_id, host, branch, claimed_at, expires_at,
  heartbeat_at``. No secrets, no plan bodies.
* **No checkout.** Writes use git plumbing (temporary index + ``commit-tree``) and
  push the new commit SHA to ``refs/heads/leases``. The user's HEAD, index and
  working tree are never touched, so every agent worktree of a clone can use it.
* **The remote push is the lock.** Claim = fetch, check for a live foreign
  lease, commit the lease file on top of the fetched tip, push fast-forward
  only. A non-fast-forward rejection means someone else moved the branch:
  re-fetch, re-evaluate, retry a bounded number of times with jitter. Never
  force-push (``--compact`` is the lone, operator-invoked exception and uses
  ``--force-with-lease``).
* **Expiry**: a lease is expired only after ``expires_at + skew`` (default 5
  min) to tolerate clock skew; assume NTP. A live foreign lease refuses a claim.
  An *expired* foreign lease is **not** silently reclaimed: it needs
  ``recover=True`` (explicit crashed-agent takeover), same doctrine as the local
  store.
* **Heartbeat** (:func:`renew`) pushes only when ``heartbeat_interval`` (default
  2h) has passed since the lease's last push, so history does not flood; the TTL
  stays 24h.
* **History growth**: every claim/renew/release is a commit. Release deletes
  the file; heartbeats are throttled; ``--compact`` re-roots the orphan branch
  into a single commit.
* **Privacy**: slugs ending in ``.local`` (plans named ``*.local.md``) are
  private and are *not* published unless ``ANCHOR_LEASE_PUBLISH_LOCAL=1``.
* **Isolation guard**: before every push the new tip is verified to contain only
  ``leases/*.json`` (:func:`assert_isolated`); also runnable via
  ``--check-isolation``.
* **Degradation**: no repo / no remote / unreachable remote raises
  :class:`LeaseBranchUnavailable`; callers fall back to the local store with a
  one-line warning, or refuse when ``ANCHOR_LEASE_STRICT=1`` (strict).

Environment: ``ANCHOR_LEASE_REMOTE`` (default ``origin``), ``ANCHOR_LEASE_STRICT``,
``ANCHOR_LEASE_PUBLISH_LOCAL``, ``ANCHOR_LEASE_SKEW_SECONDS``,
``ANCHOR_LEASE_HEARTBEAT_SECONDS``.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

BRANCH = "leases"
LEASE_DIR = "leases"
DEFAULT_TTL_SECONDS = 86400
DEFAULT_SKEW_SECONDS = 300
DEFAULT_HEARTBEAT_SECONDS = 7200
MAX_PUSH_ATTEMPTS = 6
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REJECTED_MARKERS = ("rejected", "non-fast-forward", "fetch first", "stale info")


class LeaseBranchError(Exception):
    """Base class."""


class LeaseBranchUnavailable(LeaseBranchError):
    """No git repo, no remote, or the remote is unreachable — callers may fall back."""


class LeaseConflict(LeaseBranchError):
    """A lease for this slug is held by someone else (or needs explicit recover)."""


class IsolationError(LeaseBranchError):
    """The leases branch would contain something other than ``leases/*.json``."""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def remote_name() -> str:
    return os.environ.get("ANCHOR_LEASE_REMOTE", "origin")


def strict_mode() -> bool:
    return os.environ.get("ANCHOR_LEASE_STRICT", "").strip().lower() in ("1", "true", "yes")


def publish_local_enabled() -> bool:
    return os.environ.get("ANCHOR_LEASE_PUBLISH_LOCAL", "").strip().lower() in ("1", "true", "yes")


def skew_seconds() -> int:
    return _env_int("ANCHOR_LEASE_SKEW_SECONDS", DEFAULT_SKEW_SECONDS)


def heartbeat_seconds() -> int:
    return _env_int("ANCHOR_LEASE_HEARTBEAT_SECONDS", DEFAULT_HEARTBEAT_SECONDS)


def slug_of(plan_rel: str) -> str:
    """``features/foo.local.md`` -> ``foo.local``."""
    name = plan_rel.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-3] if name.endswith(".md") else name


def is_private(slug: str) -> bool:
    return slug.endswith(".local")


def publishable(slug: str) -> bool:
    return publish_local_enabled() or not is_private(slug)


@dataclass(frozen=True)
class BranchLease:
    slug: str
    agent_id: str
    host: str
    branch: str
    claimed_at: float
    expires_at: float
    heartbeat_at: float

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at + skew_seconds()

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "agent_id": self.agent_id,
            "host": self.host,
            "branch": self.branch,
            "claimed_at": self.claimed_at,
            "expires_at": self.expires_at,
            "heartbeat_at": self.heartbeat_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BranchLease:
        return cls(
            slug=str(data["slug"]),
            agent_id=str(data["agent_id"]),
            host=str(data.get("host", "")),
            branch=str(data.get("branch", "")),
            claimed_at=float(data["claimed_at"]),
            expires_at=float(data["expires_at"]),
            heartbeat_at=float(data.get("heartbeat_at", data["claimed_at"])),
        )


# --- git plumbing ---------------------------------------------------------

def _git(
    root: Path,
    *args: str,
    env: dict | None = None,
    stdin: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    full_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin,
        capture_output=True,
        env=full_env,
    )
    if check and proc.returncode != 0:
        raise LeaseBranchError(
            f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}"
        )
    return proc


def _out(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout.decode(errors="replace").strip()


def git_root(path: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise LeaseBranchUnavailable(f"not a git repository: {path}")
    return Path(proc.stdout.decode().strip())


def _remote_ref() -> str:
    return f"refs/remotes/{remote_name()}/{BRANCH}"


def _require_remote(root: Path) -> None:
    remotes = _out(_git(root, "remote", check=False)).split()
    if remote_name() not in remotes:
        raise LeaseBranchUnavailable(f"no git remote {remote_name()!r}")


def fetch(root: Path) -> str | None:
    """Fetch the leases branch; return the remote tip SHA, or None if absent."""
    _require_remote(root)
    probe = _git(root, "ls-remote", "--heads", remote_name(), BRANCH, check=False)
    if probe.returncode != 0:
        raise LeaseBranchUnavailable(
            f"cannot reach remote {remote_name()!r}: "
            f"{probe.stderr.decode(errors='replace').strip()}"
        )
    if not _out(probe):
        return None
    got = _git(
        root, "fetch", "--quiet", remote_name(),
        f"+refs/heads/{BRANCH}:{_remote_ref()}", check=False,
    )
    if got.returncode != 0:
        raise LeaseBranchUnavailable(
            f"fetch failed: {got.stderr.decode(errors='replace').strip()}"
        )
    return _out(_git(root, "rev-parse", _remote_ref()))


def _empty_tree(root: Path) -> str:
    return _out(_git(root, "mktree", stdin=b""))


def _commit(root: Path, tree: str, parent: str | None, message: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME", "anchor-leases"),
        "GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL", "anchor-leases@localhost"),
        "GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME", "anchor-leases"),
        "GIT_COMMITTER_EMAIL": os.environ.get("GIT_COMMITTER_EMAIL", "anchor-leases@localhost"),
    }
    args = ["commit-tree", tree, "-m", message]
    if parent:
        args += ["-p", parent]
    return _out(_git(root, *args, env=env))


def _build_tree(root: Path, parent: str | None, changes: dict[str, bytes | None]) -> str:
    """Tree = parent's tree with ``changes`` applied (None deletes). Uses a private index."""
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": str(Path(td) / "index")}
        if parent:
            _git(root, "read-tree", parent, env=env)
        for path, data in changes.items():
            if data is None:
                _git(root, "update-index", "--force-remove", path, env=env)
            else:
                blob = _out(_git(root, "hash-object", "-w", "--stdin", stdin=data))
                _git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        return _out(_git(root, "write-tree", env=env))


def assert_isolated(root: Path, sha: str) -> None:
    """Refuse a leases tip that contains anything but ``leases/*.json``."""
    names = _out(_git(root, "ls-tree", "-r", "--name-only", sha)).splitlines()
    bad = [n for n in names if not (n.startswith(f"{LEASE_DIR}/") and n.endswith(".json")
                                    and "/" not in n[len(LEASE_DIR) + 1:])]
    if bad:
        raise IsolationError(f"{BRANCH} branch may only hold {LEASE_DIR}/*.json; found {bad}")


def _push(root: Path, sha: str, *, force_with_lease: str | None = None) -> bool:
    """Push ``sha`` to the remote leases branch. False = lost the race (non-ff)."""
    assert_isolated(root, sha)
    args = ["push", "--quiet"]
    if force_with_lease:
        args.append(f"--force-with-lease=refs/heads/{BRANCH}:{force_with_lease}")
    args += [remote_name(), f"{sha}:refs/heads/{BRANCH}"]
    proc = _git(root, *args, check=False)
    if proc.returncode == 0:
        _git(root, "update-ref", f"refs/heads/{BRANCH}", sha)
        _git(root, "update-ref", _remote_ref(), sha)
        return True
    err = proc.stderr.decode(errors="replace").lower()
    if any(m in err for m in _REJECTED_MARKERS):
        return False
    raise LeaseBranchUnavailable(f"push failed: {err.strip()}")


def bootstrap(root: Path) -> str:
    """Ensure the orphan ``leases`` branch exists on the remote; return its tip. Idempotent."""
    root = git_root(root)
    for _ in range(MAX_PUSH_ATTEMPTS):
        tip = fetch(root)
        if tip:
            _git(root, "update-ref", f"refs/heads/{BRANCH}", tip)
            return tip
        root_commit = _commit(root, _empty_tree(root), None, "leases: init orphan branch")
        if _push(root, root_commit):
            return root_commit
        time.sleep(random.uniform(0, 0.2))
    raise LeaseBranchError("could not bootstrap leases branch (race)")


# --- read side ------------------------------------------------------------

def _read_all(root: Path, tip: str | None) -> dict[str, BranchLease]:
    if not tip:
        return {}
    out: dict[str, BranchLease] = {}
    listing = _out(_git(root, "ls-tree", "-r", tip, "--", f"{LEASE_DIR}/", check=False))
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        blob = meta.split()[-1] if meta else ""
        if not path.endswith(".json"):
            continue
        try:
            data = json.loads(_git(root, "cat-file", "blob", blob).stdout.decode())
            lease = BranchLease.from_dict(data)
        except (LeaseBranchError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue  # tolerate malformed files
        out[lease.slug] = lease
    return out


def list_leases(root: Path) -> list[BranchLease]:
    """Fetch, then return every lease on the branch (expired ones included)."""
    root = git_root(root)
    return sorted(_read_all(root, fetch(root)).values(), key=lambda lz: lz.slug)


def holder_of(root: Path, slug: str) -> BranchLease | None:
    """The unexpired lease for ``slug``, or None."""
    for lease in list_leases(root):
        if lease.slug == slug and not lease.expired():
            return lease
    return None


def live_slugs(root: Path) -> set[str]:
    return {lz.slug for lz in list_leases(root) if not lz.expired()}


# --- write side -----------------------------------------------------------

def _check_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug) or slug.endswith(".json"):
        raise LeaseBranchError(f"invalid lease slug: {slug!r}")


def _path(slug: str) -> str:
    return f"{LEASE_DIR}/{slug}.json"


def _blob(lease: BranchLease) -> bytes:
    return (json.dumps(lease.to_dict(), indent=2) + "\n").encode()


def _local_branch(root: Path) -> str:
    return _out(_git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False))


def _mutate(root: Path, slug: str, decide) -> BranchLease | None:
    """CAS loop. ``decide(existing_or_None)`` -> (lease_or_None, message); None deletes."""
    root = git_root(root)
    _check_slug(slug)
    bootstrap(root)
    for attempt in range(MAX_PUSH_ATTEMPTS):
        tip = fetch(root)
        existing = _read_all(root, tip).get(slug)
        new, message = decide(existing)
        if new is None and existing is None:
            return None
        changes = {_path(slug): None if new is None else _blob(new)}
        sha = _commit(root, _build_tree(root, tip, changes), tip, message)
        if _push(root, sha):
            return new
        time.sleep(random.uniform(0, 0.1 * (attempt + 1)))
    raise LeaseBranchUnavailable(f"leases branch too contended for {slug!r}; try again")


def claim(
    root: Path,
    slug: str,
    agent_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    recover: bool = False,
) -> BranchLease:
    """Publish a lease. Raises :class:`LeaseConflict` on a live foreign lease."""
    branch = _local_branch(git_root(root))

    def decide(existing: BranchLease | None):
        now = time.time()
        if existing and existing.agent_id != agent_id:
            if not existing.expired(now):
                raise LeaseConflict(
                    f"{slug!r} is leased by {existing.agent_id!r}@{existing.host} "
                    f"until {existing.expires_at:.0f}"
                )
            if not recover:
                raise LeaseConflict(
                    f"{slug!r} has an expired lease from {existing.agent_id!r}; "
                    "explicit recover required"
                )
        lease = BranchLease(
            slug=slug,
            agent_id=agent_id,
            host=socket.gethostname(),
            branch=branch,
            claimed_at=existing.claimed_at if existing and existing.agent_id == agent_id else now,
            expires_at=now + max(1, int(ttl_seconds)),
            heartbeat_at=now,
        )
        return lease, f"lease: claim {slug} by {agent_id}"

    result = _mutate(root, slug, decide)
    assert result is not None
    return result


def renew(
    root: Path,
    slug: str,
    agent_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    force: bool = False,
) -> BranchLease:
    """Heartbeat. Pushes only when the heartbeat interval has elapsed (or ``force``)."""
    outcome: dict[str, BranchLease] = {}

    def decide(existing: BranchLease | None):
        if existing is None:
            raise LeaseConflict(f"cannot renew {slug!r}: no lease on the branch")
        if existing.agent_id != agent_id:
            raise LeaseConflict(f"cannot renew lease held by {existing.agent_id!r}")
        now = time.time()
        if not force and now - existing.heartbeat_at < heartbeat_seconds():
            outcome["lease"] = existing
            return existing, ""
        lease = BranchLease(
            slug=slug, agent_id=agent_id, host=existing.host, branch=existing.branch,
            claimed_at=existing.claimed_at,
            expires_at=now + max(1, int(ttl_seconds)), heartbeat_at=now,
        )
        outcome["lease"] = lease
        return lease, f"lease: heartbeat {slug}"

    root = git_root(root)
    _check_slug(slug)
    tip = fetch(root)
    current = _read_all(root, tip).get(slug)
    probe_new, _ = decide(current)
    if probe_new is current:  # throttled: nothing to push
        return current  # type: ignore[return-value]
    return _mutate(root, slug, decide) or outcome["lease"]


def release(root: Path, slug: str, agent_id: str | None = None, *, force: bool = False) -> bool:
    """Delete the lease file. True if one was removed."""
    removed = {"hit": False}

    def decide(existing: BranchLease | None):
        if existing is None:
            return None, ""
        if (not force and agent_id is not None and existing.agent_id != agent_id
                and not existing.expired()):
            raise LeaseConflict(f"cannot release lease held by {existing.agent_id!r}")
        removed["hit"] = True
        return None, f"lease: release {slug}"

    _mutate(root, slug, decide)
    return removed["hit"]


def compact(root: Path) -> str:
    """Operator-invoked: re-root the orphan branch into one commit (force-with-lease)."""
    root = git_root(root)
    tip = bootstrap(root)
    tree = _out(_git(root, "rev-parse", f"{tip}^{{tree}}"))
    sha = _commit(root, tree, None, "leases: compact history")
    if not _push(root, sha, force_with_lease=tip):
        raise LeaseBranchError("compact lost a race; branch moved — re-run")
    return sha


def check_isolation(root: Path) -> None:
    """Standalone guard: the tip is isolated, no lease file is tracked elsewhere,
    and ``.plans/.leases/`` is still gitignored."""
    root = git_root(root)
    tip = fetch(root)
    if tip:
        assert_isolated(root, tip)
    tracked = _out(_git(root, "ls-files", "--", ".plans/.leases", f"{LEASE_DIR}/")).splitlines()
    if tracked:
        raise IsolationError(f"lease files tracked on the current branch: {tracked}")
    ignored = _git(root, "check-ignore", "-q", ".plans/.leases/x.json", check=False)
    if ignored.returncode != 0:
        raise IsolationError(".plans/.leases/ is not gitignored")


# --- CLI ------------------------------------------------------------------

def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(ts))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Shared plan leases on the orphan `leases` branch")
    ap.add_argument("--root", default=".", help="path inside the git repo")
    ap.add_argument("--status", action="store_true", help="list leases after a fetch")
    ap.add_argument("--json", action="store_true", help="machine-readable --status")
    ap.add_argument("--check-isolation", action="store_true")
    ap.add_argument("--compact", action="store_true", help="re-root the branch (operator only)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.check_isolation:
            check_isolation(root)
            print("ok: leases branch isolated")
        elif args.compact:
            print(f"compacted -> {compact(root)}")
        elif args.status:
            leases = list_leases(root)
            if args.json:
                print(json.dumps([{**lz.to_dict(), "expired": lz.expired()} for lz in leases], indent=2))
            elif not leases:
                print("no leases")
            else:
                for lz in leases:
                    state = "expired" if lz.expired() else "live"
                    print(f"{lz.slug} · {lz.agent_id} · {lz.host} · {_fmt_ts(lz.expires_at)} · {state}")
        else:
            ap.print_help()
    except LeaseBranchUnavailable as exc:
        print(f"leases branch unavailable: {exc}", file=sys.stderr)
        return 3
    except LeaseBranchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
