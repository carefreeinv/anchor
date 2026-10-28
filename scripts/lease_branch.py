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
* **Payload**: ``slug, agent_id, host, claimed_at, expires_at, heartbeat_at``.
  No secrets, no plan bodies, and no branch names (a branch name can itself leak
  a private slug).
* **Ownership is (agent_id, host).** Default agent ids (``mcp-agent``,
  ``work-once-$USER``) repeat across machines, so an equal agent id alone never
  proves a lease is yours. Only the same agent on the same host may refresh,
  renew or release; the host is ``ANCHOR_LEASE_HOST`` or the machine hostname.
  ``force`` never lets a caller delete another host's live lease.
* **No checkout.** Writes use git plumbing (temporary index + ``commit-tree``) and
  push the new commit SHA to ``refs/heads/leases``. The user's HEAD, index and
  working tree are never touched, so every agent worktree of a clone can use it.
* **The remote push is the lock.** Claim = fetch, check for a live foreign
  lease, commit the lease file on top of the fetched tip, push fast-forward
  only. A non-fast-forward rejection means someone else moved the branch:
  re-fetch, re-evaluate, retry a bounded number of times with jitter. Never
  force-push (``--compact`` is the lone, operator-invoked exception and uses
  ``--force-with-lease``). Git runs with ``LC_ALL=C`` so rejection is recognised
  on any locale.
* **Expiry**: a lease is expired only after ``expires_at + skew`` (default 5
  min) to tolerate clock skew; assume NTP. A live foreign lease refuses a claim.
  An *expired* lease on an **in-progress** plan still needs ``recover=True``
  (explicit crashed-agent takeover). An expired lease on a **ready-lane** plan
  (``bugs/`` / ``features/``) is reclaimable without recover — a ready plan is
  not live in-progress anywhere. Same agent+host may always refresh a live
  lease; an expired own lease resets ``claimed_at``.
* **Heartbeat** (:func:`renew`) pushes only when ``min(heartbeat interval, ttl/3)``
  (interval default 2h) has passed since the lease's last push, so history does
  not flood and a short TTL is never outrun; the default TTL stays 24h.
* **History growth**: every claim/renew/release is a commit. Release deletes
  the file; heartbeats are throttled; ``--compact`` re-roots the orphan branch
  into a single commit.
* **Privacy**: slugs ending in ``.local`` (plans named ``*.local.md``) are
  private and are *not* published unless ``ANCHOR_LEASE_PUBLISH_LOCAL=1``.
* **Isolation guard**: before every push the new tip is verified to contain only
  ``leases/*.json`` (:func:`assert_isolated`); also runnable via
  ``--check-isolation``.
* **Foreign branch**: a remote ``leases`` branch that is not isolated and orphan is
  never adopted or overwritten; it counts as unavailable (degrade or strict-refuse).
  A pre-existing *local* ``leases`` branch that is not ours is left alone.
* **Degradation**: no repo / no remote / unreachable remote raises
  :class:`LeaseBranchUnavailable`; callers fall back to the local store with a
  one-line warning, or refuse when ``ANCHOR_LEASE_STRICT=1`` (strict).

Environment: ``ANCHOR_LEASE_REMOTE`` (default ``origin``), ``ANCHOR_LEASE_STRICT``,
``ANCHOR_LEASE_PUBLISH_LOCAL``, ``ANCHOR_LEASE_SKEW_SECONDS``,
``ANCHOR_LEASE_HEARTBEAT_SECONDS``, ``ANCHOR_LEASE_HOST``,
``ANCHOR_LEASE_NET_TIMEOUT`` (seconds per network git call, default 30).
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
DEFAULT_NET_TIMEOUT_SECONDS = 30
MAX_PUSH_ATTEMPTS = 6
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Retry only a lost CAS race. GitHub/GitLab non-ff says "non-fast-forward";
# a local bare remote racing two pushes says "cannot lock ref" /
# "failed to update ref". Hook / permission refusals
# ("[remote rejected] … pre-receive hook declined") must not look like
# contention — they are unavailability, with the remote's message.
_NON_FF_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "stale info",
    "cannot lock ref",
    "failed to update ref",
)
_HOOK_MARKERS = ("hook declined", "pre-receive hook", "protected branch")


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


def net_timeout_seconds() -> int:
    return max(1, _env_int("ANCHOR_LEASE_NET_TIMEOUT", DEFAULT_NET_TIMEOUT_SECONDS))


def host_id() -> str:
    return os.environ.get("ANCHOR_LEASE_HOST", "").strip() or socket.gethostname()


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
    claimed_at: float
    expires_at: float
    heartbeat_at: float

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at + skew_seconds()

    def owned_by(self, agent_id: str | None) -> bool:
        """Same host, and the same agent (any agent when ``agent_id`` is None)."""
        return self.host == host_id() and (agent_id is None or self.agent_id == agent_id)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "agent_id": self.agent_id,
            "host": self.host,
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
    network: bool = False,
) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    full_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    # Stable, English git messages: push rejection is recognised from stderr.
    full_env["LC_ALL"] = "C"
    full_env["LANGUAGE"] = "C"
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            input=stdin,
            capture_output=True,
            env=full_env,
            timeout=net_timeout_seconds() if network else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise LeaseBranchUnavailable(
            f"git {args[0]} timed out after {net_timeout_seconds()}s"
        ) from exc
    except FileNotFoundError as exc:
        raise LeaseBranchUnavailable("git is not installed") from exc
    except OSError as exc:
        raise LeaseBranchUnavailable(f"cannot run git: {exc}") from exc
    if check and proc.returncode != 0:
        raise LeaseBranchError(
            f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}"
        )
    return proc


def _out(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout.decode(errors="replace").strip()


def git_root(path: Path) -> Path:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise LeaseBranchUnavailable("git is not installed") from exc
    except OSError as exc:
        raise LeaseBranchUnavailable(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise LeaseBranchUnavailable(f"not a git repository: {path}")
    return Path(proc.stdout.decode().strip())


def _remote_ref() -> str:
    return f"refs/remotes/{remote_name()}/{BRANCH}"


def _require_remote(root: Path) -> None:
    remotes = _out(_git(root, "remote", check=False)).split()
    if remote_name() not in remotes:
        raise LeaseBranchUnavailable(f"no git remote {remote_name()!r}")


def _code_branch_refs(root: Path) -> list[str]:
    """Refs that must not share history with an orphan leases tip.

    Skip HEAD when it *is* the local ``leases`` branch (operator has it checked
    out): merge-base against that HEAD would always succeed.
    """
    refs = [
        "refs/heads/dev",
        "refs/heads/develop",
        "refs/heads/main",
        "refs/heads/master",
    ]
    head = _out(_git(root, "symbolic-ref", "-q", "HEAD", check=False))
    if head and not head.endswith(f"/{BRANCH}"):
        refs.append("HEAD")
    return refs


def _shares_code_history(root: Path, tip: str) -> bool:
    for ref in _code_branch_refs(root):
        if _git(root, "rev-parse", "-q", "--verify", ref, check=False).returncode != 0:
            continue
        if _git(root, "merge-base", tip, ref, check=False).returncode == 0:
            return True
    return False


def _validate_remote(root: Path, tip: str) -> None:
    """Refuse to treat a foreign ``leases`` branch as ours (never adopt, never overwrite)."""
    try:
        assert_isolated(root, tip)
    except IsolationError as exc:
        raise LeaseBranchUnavailable(
            f"remote {remote_name()!r} has a {BRANCH!r} branch that is not a lease branch ({exc})"
        ) from exc
    if _shares_code_history(root, tip):
        raise LeaseBranchUnavailable(
            f"remote {remote_name()!r} {BRANCH!r} branch shares history with a code branch; not an orphan lease branch"
        )


def fetch(root: Path, *, validate: bool = True) -> str | None:
    """Fetch the leases branch (one round trip); return the remote tip SHA, or None if absent."""
    _require_remote(root)
    got = _git(
        root, "fetch", "--quiet", remote_name(),
        f"+refs/heads/{BRANCH}:{_remote_ref()}", check=False, network=True,
    )
    if got.returncode != 0:
        err = got.stderr.decode(errors="replace").strip()
        if "couldn't find remote ref" in err.lower():
            return None
        raise LeaseBranchUnavailable(f"cannot fetch from remote {remote_name()!r}: {err}")
    tip = _out(_git(root, "rev-parse", _remote_ref()))
    if validate:
        _validate_remote(root, tip)
    return tip


def _sync_local_branch(root: Path, sha: str, *, replaces: str | None = None) -> None:
    """Keep a local ``leases`` branch for ``git log leases`` — but only ever move one that is ours.

    Follows a re-rooted tip (``--compact`` from another clone) when the local
    ref still looks like our isolated orphan. Leaves a user's unrelated
    ``leases`` branch (non-isolated or shares code history) untouched.
    """
    ref = f"refs/heads/{BRANCH}"
    cur = _out(_git(root, "rev-parse", "-q", "--verify", ref, check=False))
    if cur == sha:
        return
    if cur and cur != replaces:
        try:
            assert_isolated(root, cur)
        except IsolationError:
            return
        if _shares_code_history(root, cur):
            return
        ancestor = _git(
            root, "merge-base", "--is-ancestor", cur, sha, check=False
        ).returncode == 0
        if not ancestor:
            # Stale isolated orphan (compact / re-bootstrap) — still ours; follow.
            pass
    _git(root, "update-ref", ref, sha)


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
    proc = _git(root, *args, check=False, network=True)
    if proc.returncode == 0:
        _git(root, "update-ref", _remote_ref(), sha)
        _sync_local_branch(root, sha, replaces=force_with_lease)
        return True
    err = proc.stderr.decode(errors="replace")
    err_l = err.lower()
    if any(m in err_l for m in _HOOK_MARKERS):
        raise LeaseBranchUnavailable(f"push failed: {err.strip()}")
    if any(m in err_l for m in _NON_FF_MARKERS):
        return False
    raise LeaseBranchUnavailable(f"push failed: {err.strip()}")


def bootstrap(root: Path) -> str:
    """Ensure the orphan ``leases`` branch exists on the remote; return its tip. Idempotent."""
    root = git_root(root)
    for _ in range(MAX_PUSH_ATTEMPTS):
        tip = fetch(root)
        if tip:
            _sync_local_branch(root, tip)
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


def _mutate(root: Path, slug: str, decide) -> BranchLease | None:
    """CAS loop. ``decide(existing_or_None)`` -> (lease_or_None, message).

    A returned lease replaces the file, ``None`` deletes it, and returning
    ``existing`` unchanged means "nothing to push".
    """
    root = git_root(root)
    _check_slug(slug)
    for attempt in range(MAX_PUSH_ATTEMPTS):
        tip = fetch(root)
        existing = _read_all(root, tip).get(slug)
        new, message = decide(existing)
        if new is existing:
            return existing
        if tip is None:
            bootstrap(root)  # first writer creates the orphan branch, then retry on top of it
            continue
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
    def decide(existing: BranchLease | None):
        now = time.time()
        if existing and not existing.owned_by(agent_id):
            if not existing.expired(now):
                raise LeaseConflict(
                    f"{slug!r} is leased by {existing.agent_id!r}@{existing.host} "
                    f"until {existing.expires_at:.0f}"
                )
            if not recover:
                raise LeaseConflict(
                    f"{slug!r} has an expired lease from {existing.agent_id!r}@{existing.host}; "
                    "explicit recover required"
                )
        keep_claimed = (
            existing is not None
            and existing.owned_by(agent_id)
            and not existing.expired(now)
        )
        lease = BranchLease(
            slug=slug,
            agent_id=agent_id,
            host=host_id(),
            claimed_at=existing.claimed_at if keep_claimed else now,
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
    """Heartbeat. Pushes only when the throttle interval has elapsed (or ``force``).

    The interval is ``min(heartbeat interval, ttl/3)`` so a short TTL is never outrun.
    """

    def decide(existing: BranchLease | None):
        if existing is None:
            raise LeaseConflict(f"cannot renew {slug!r}: no lease on the branch")
        if not existing.owned_by(agent_id):
            raise LeaseConflict(
                f"cannot renew lease held by {existing.agent_id!r}@{existing.host}"
            )
        now = time.time()
        interval = min(heartbeat_seconds(), max(1, int(ttl_seconds)) / 3)
        if not force and now - existing.heartbeat_at < interval:
            return existing, ""
        lease = BranchLease(
            slug=slug, agent_id=agent_id, host=existing.host,
            claimed_at=existing.claimed_at,
            expires_at=now + max(1, int(ttl_seconds)), heartbeat_at=now,
        )
        return lease, f"lease: heartbeat {slug}"

    result = _mutate(root, slug, decide)
    assert result is not None
    return result


def release(root: Path, slug: str, agent_id: str | None = None, *, force: bool = False) -> bool:
    """Delete the lease file. True if one was removed.

    Needs ownership (same host, same agent when given) unless the lease expired.
    ``force`` is an operator override for the CLI only; library callers must not
    forward a *local* force here.
    """
    last_had = {"v": False}

    def decide(existing: BranchLease | None):
        last_had["v"] = existing is not None
        if existing is None:
            return None, ""
        if not force and not existing.owned_by(agent_id) and not existing.expired():
            raise LeaseConflict(
                f"cannot release lease held by {existing.agent_id!r}@{existing.host}"
            )
        return None, f"lease: release {slug}"

    _mutate(root, slug, decide)
    return last_had["v"]


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
    tip = fetch(root, validate=False)
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
