#!/usr/bin/env python3
"""Filesystem claim/lease + plan lane moves under ``.plans/``.

Leases live under ``.plans/.leases/`` as JSON files. Claiming a ready plan
(``bugs/`` or ``features/``) **moves** it into ``.plans/in-progress/`` and
records the agent that owns it. Other agents must ignore plans under
``in-progress/`` unless their ``agent_id`` matches the lease.

Agents may also **park** plans in ``ambiguous/`` (half-baked) or ``blocked/``
(cannot fix now), or **return** an in-progress plan to ``bugs/``|``features/``
for another worker. Those park lanes are never auto-executed by pickers.

Leases are **minimal but required**: claiming a ready plan writes one atomically
with the move, so ownership is never skipped. The TTL is long (24h) and a live
agent refreshes it via :func:`renew` (heartbeat); only a lease left untouched
past the TTL is reclaimable, and only via an **explicit** recover (``recover=True``)
— never a silent side effect. An unleased in-progress plan is *not* auto-claimed.

**Shared leases.** When the project has a git remote, claims are also published
to the orphan ``leases`` branch (see ``lease_branch.py``) *before* the local file
is written, so another machine sees the claim before it claims. :func:`renew`,
:func:`release`, :func:`claimed_rels` and :func:`owner_of` mirror/consult that
branch. With no remote or an unreachable one the local store still works, with a
one-line warning; ``ANCHOR_LEASE_STRICT=1`` refuses instead. ``*.local.md`` plans
are never published unless ``ANCHOR_LEASE_PUBLISH_LOCAL=1``;
``ANCHOR_LEASE_BRANCH=0`` disables the branch layer entirely.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import lease_branch

DEFAULT_TTL_SECONDS = 86400  # 24h: long enough that a live agent never looks
# orphaned; refreshed by renew() heartbeat. Only leases untouched past this are
# reclaimable, and only via explicit recover.
IN_PROGRESS = "in-progress"
READY_LANES = ("bugs", "features")
READY_PREFIXES = ("bugs/", "features/")
PARK_LANES = frozenset({"ambiguous", "blocked"})


@dataclass(frozen=True)
class Lease:
    plan_rel: str
    agent_id: str
    claimed_at: float
    expires_at: float
    origin_rel: str | None = None  # e.g. features/foo.md before move

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def to_dict(self) -> dict:
        d = {
            "plan": self.plan_rel,
            "agent_id": self.agent_id,
            "claimed_at": self.claimed_at,
            "expires_at": self.expires_at,
        }
        if self.origin_rel:
            d["origin"] = self.origin_rel
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Lease:
        return cls(
            plan_rel=str(data["plan"]),
            agent_id=str(data["agent_id"]),
            claimed_at=float(data["claimed_at"]),
            expires_at=float(data["expires_at"]),
            origin_rel=(str(data["origin"]) if data.get("origin") else None),
        )


# --- shared (git-branch) layer --------------------------------------------

_warned: set[str] = set()


def _warn_once(key: str, msg: str) -> None:
    """Warn once per process per *reason* (``key``), not per distinct message text."""
    if key not in _warned:
        _warned.add(key)
        print(f"plan_lease: warning: {msg}", file=sys.stderr)


def _branch_enabled() -> bool:
    return os.environ.get("ANCHOR_LEASE_BRANCH", "1").strip().lower() not in ("0", "off", "false", "no")


def _branch_call(plans_root: Path, plan_rel: str | None, fn, *, blocking: bool = True):
    """Run ``fn(project_root, slug)`` against the leases branch.

    Returns ``(ran, result)``. Skips private (``*.local``) plans and a disabled
    layer. When ``blocking`` (claims), a conflict or error becomes
    :class:`ClaimError` and unavailability degrades to the local store with a
    warning (strict mode raises instead). When not ``blocking`` (renew, release,
    reads) nothing ever raises: every failure is a one-line warning and the local
    result stands.
    """
    if not _branch_enabled():
        return False, None
    slug = lease_branch.slug_of(plan_rel) if plan_rel else ""
    if plan_rel and not lease_branch.publishable(slug):
        return False, None
    root = plans_root.parent
    try:
        return True, fn(root, slug)
    except lease_branch.LeaseConflict as exc:
        if blocking:
            raise ClaimError(str(exc)) from exc
        _warn_once("conflict", f"shared lease not changed ({exc})")
    except lease_branch.LeaseBranchUnavailable as exc:
        if lease_branch.strict_mode() and blocking:
            raise ClaimError(f"strict mode: shared lease unavailable ({exc})") from exc
        if "not a git repository" not in str(exc):
            _warn_once("unavailable", f"shared leases unavailable, using local lease only ({exc})")
    except lease_branch.LeaseBranchError as exc:
        if blocking:
            raise ClaimError(f"shared lease error: {exc}") from exc
        _warn_once("error", f"shared lease error, ignored ({exc})")
    except OSError as exc:
        if blocking:
            raise ClaimError(f"shared lease error: {exc}") from exc
        _warn_once("error", f"shared lease error, ignored ({exc})")
    return False, None


def _remote_claim(plans_root: Path, plan_rel: str, agent_id: str, ttl: int, recover: bool = False) -> bool:
    ran, _ = _branch_call(
        plans_root, plan_rel,
        lambda root, slug: lease_branch.claim(root, slug, agent_id, ttl_seconds=ttl, recover=recover),
    )
    return ran


def _remote_live_slugs(plans_root: Path) -> dict[str, str]:
    """slug -> agent_id for unexpired shared leases (empty when unavailable)."""
    ran, leases = _branch_call(
        plans_root, None, lambda root, _slug: lease_branch.list_leases(root), blocking=False
    )
    return {lz.slug: lz.agent_id for lz in leases or [] if not lz.expired()} if ran else {}


def leases_dir(plans_root: Path) -> Path:
    return plans_root / ".leases"


def lease_key(plan_rel: str) -> str:
    """Stable filename for a plan relative path under .plans/."""
    return plan_rel.replace("\\", "/").replace("/", "__") + ".json"


def lease_path(plans_root: Path, plan_rel: str) -> Path:
    return leases_dir(plans_root) / lease_key(plan_rel)


def read_lease(plans_root: Path, plan_rel: str) -> Lease | None:
    path = lease_path(plans_root, plan_rel)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Lease.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def active_lease(plans_root: Path, plan_rel: str) -> Lease | None:
    lease = read_lease(plans_root, plan_rel)
    if lease is None or lease.expired:
        return None
    return lease


def _write_lease_atomic(path: Path, lease: Lease) -> bool:
    """Create lease file exclusively. Returns False if another holder exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(lease.to_dict(), indent=2) + "\n"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _write_lease_force(path: Path, lease: Lease) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lease.to_dict(), indent=2) + "\n", encoding="utf-8")


def claim(
    plans_root: Path,
    plan_rel: str,
    agent_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    origin_rel: str | None = None,
) -> Lease:
    """Claim a plan path in place (no move). Prefer :func:`claim_and_move` for ready work.

    Raises ClaimError if an unexpired lease is held by another agent.
    Stale (expired) leases are removed and reclaimed.
    """
    path = lease_path(plans_root, plan_rel)
    now = time.time()
    existing = read_lease(plans_root, plan_rel)
    if existing is not None and not existing.expired:
        if existing.agent_id == agent_id:
            _release_local(plans_root, plan_rel, agent_id=agent_id, force=True)
        else:
            raise ClaimError(
                f"plan already claimed by {existing.agent_id!r} until "
                f"{existing.expires_at} ({plan_rel})"
            )
    elif existing is not None and existing.expired:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise ClaimError(f"could not clear stale lease for {plan_rel}: {exc}") from exc

    lease = Lease(
        plan_rel=plan_rel,
        agent_id=agent_id,
        claimed_at=now,
        expires_at=now + max(1, int(ttl_seconds)),
        origin_rel=origin_rel or (existing.origin_rel if existing else None),
    )
    if not _write_lease_atomic(path, lease):
        other = read_lease(plans_root, plan_rel)
        if other and not other.expired and other.agent_id != agent_id:
            raise ClaimError(
                f"plan already claimed by {other.agent_id!r} ({plan_rel})"
            )
        if other and other.expired:
            path.unlink(missing_ok=True)
            if _write_lease_atomic(path, lease):
                return lease
        raise ClaimError(f"could not claim {plan_rel} (race)")
    return lease


def claim_and_move(
    plans_root: Path,
    plan_rel: str,
    agent_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    recover: bool = False,
) -> tuple[Lease, Path]:
    """Claim a ready plan and move it to ``in-progress/``.

    ``plan_rel`` must be ``bugs/…`` or ``features/…``. If the plan is already under
    ``in-progress/`` and this agent holds the (active) lease, refreshes TTL and
    returns it. An in-progress plan with **no active lease** (never claimed, or a
    lease expired past the long TTL) is refused unless ``recover=True`` — there is
    no silent reclaim of possibly-live work.

    Returns ``(lease, absolute_path_after_move)``.
    """
    plan_rel = plan_rel.replace("\\", "/")
    plans_root = plans_root.resolve()

    # Resume own in-progress work
    if plan_rel.startswith(f"{IN_PROGRESS}/"):
        existing = active_lease(plans_root, plan_rel)
        if existing and existing.agent_id == agent_id:
            _remote_claim(plans_root, plan_rel, agent_id, ttl_seconds)
            _release_local(plans_root, plan_rel, agent_id=agent_id, force=True)
            lease = claim(
                plans_root,
                plan_rel,
                agent_id,
                ttl_seconds=ttl_seconds,
                origin_rel=existing.origin_rel,
            )
            return lease, (plans_root / plan_rel).resolve()
        if existing:
            raise ClaimError(
                f"in-progress plan owned by {existing.agent_id!r} — ignore unless you are that agent"
            )
        # No active lease: never claimed, or expired past the long TTL. Never
        # silently reclaim — it may be another agent's live work with a missed
        # heartbeat. Recovery is explicit (crashed-agent takeover).
        if not recover:
            stale = read_lease(plans_root, plan_rel)
            who = f" (expired lease last held by {stale.agent_id!r})" if stale else ""
            raise ClaimError(
                f"in-progress plan {plan_rel} has no active lease{who}; pass "
                "recover=True to take over abandoned/expired work, or leave it"
            )
        _remote_claim(plans_root, plan_rel, agent_id, ttl_seconds, recover=True)
        lease = claim(
            plans_root,
            plan_rel,
            agent_id,
            ttl_seconds=ttl_seconds,
            origin_rel=None,
        )
        return lease, (plans_root / plan_rel).resolve()

    if not plan_rel.startswith(READY_PREFIXES):
        raise ClaimError(
            f"claim_and_move only accepts bugs/|features/ (or own in-progress/); got {plan_rel}"
        )

    src = plans_root / plan_rel
    if not src.is_file():
        raise ClaimError(f"plan file missing: {plan_rel}")

    dest_name = src.name
    dest_rel = f"{IN_PROGRESS}/{dest_name}"
    dest = plans_root / dest_rel
    if dest.exists() and dest.resolve() != src.resolve():
        other = active_lease(plans_root, dest_rel)
        if other and other.agent_id != agent_id and not other.expired:
            raise ClaimError(
                f"{dest_rel} already held by {other.agent_id!r}"
            )
        raise ClaimError(f"destination already exists: {dest_rel}")

    # Shared lease first: refuses before the plan leaves bugs|features/ when
    # another machine already holds a *live* lease. An *expired* shared lease
    # on a ready-lane plan is reclaimable (the plan is not in-progress anywhere
    # live) — recover=True only unlocks expired foreign leases, never live ones.
    published = _remote_claim(
        plans_root, plan_rel, agent_id, ttl_seconds, recover=True
    )
    try:
        # Exclusive lease on the ready path (coordination)
        claim(plans_root, plan_rel, agent_id, ttl_seconds=ttl_seconds)
    except ClaimError:
        if published:
            _branch_call(plans_root, plan_rel,
                         lambda root, slug: lease_branch.release(root, slug, agent_id),
                         blocking=False)
        raise

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest)
    except OSError as exc:
        _release_local(plans_root, plan_rel, force=True)
        if published:
            _branch_call(plans_root, plan_rel,
                         lambda root, slug: lease_branch.release(root, slug, agent_id),
                         blocking=False)
        raise ClaimError(f"could not move {plan_rel} → {dest_rel}: {exc}") from exc

    # Move lease key from ready path → in-progress path
    _release_local(plans_root, plan_rel, force=True)
    now = time.time()
    lease = Lease(
        plan_rel=dest_rel,
        agent_id=agent_id,
        claimed_at=now,
        expires_at=now + max(1, int(ttl_seconds)),
        origin_rel=plan_rel,
    )
    lp = lease_path(plans_root, dest_rel)
    if lp.exists():
        # Same agent refresh or stale
        old = read_lease(plans_root, dest_rel)
        if old and not old.expired and old.agent_id != agent_id:
            # Should not happen after successful rename into empty dest
            raise ClaimError(f"lease race on {dest_rel}")
        lp.unlink(missing_ok=True)
    _write_lease_force(lp, lease)
    return lease, dest.resolve()


def renew(
    plans_root: Path,
    plan_rel: str,
    agent_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> Lease:
    """Heartbeat: extend a lease you own, pushing ``expires_at`` to now + TTL.

    A live agent calls this periodically so its in-progress plan never looks
    orphaned. Also lets an agent refresh its *own* just-expired lease (resume
    after a pause). Refuses when there is no lease file at all, or when the
    lease — active or expired — belongs to a **different** agent. Heartbeat
    never takes over abandoned work; that is exclusively
    ``claim_and_move(..., recover=True)``.
    """
    plan_rel = plan_rel.replace("\\", "/")
    existing = read_lease(plans_root, plan_rel)
    if existing is None:
        raise ClaimError(f"cannot renew {plan_rel}: no lease on file")
    if existing.agent_id != agent_id:
        raise ClaimError(
            f"cannot renew lease held by {existing.agent_id!r} as {agent_id!r} ({plan_rel})"
        )
    now = time.time()
    lease = Lease(
        plan_rel=plan_rel,
        agent_id=agent_id,
        claimed_at=existing.claimed_at,
        expires_at=now + max(1, int(ttl_seconds)),
        origin_rel=existing.origin_rel,
    )
    _write_lease_force(lease_path(plans_root, plan_rel), lease)
    _remote_renew(plans_root, plan_rel, agent_id, ttl_seconds)
    return lease


def _remote_renew(plans_root: Path, plan_rel: str, agent_id: str, ttl: int) -> None:
    def go(root: Path, slug: str):
        try:
            return lease_branch.renew(root, slug, agent_id, ttl_seconds=ttl)
        except lease_branch.LeaseConflict as exc:
            if "no lease" not in str(exc):
                raise
            return lease_branch.claim(root, slug, agent_id, ttl_seconds=ttl)

    _branch_call(plans_root, plan_rel, go, blocking=False)


def _release_local(
    plans_root: Path,
    plan_rel: str,
    *,
    agent_id: str | None = None,
    force: bool = False,
) -> bool:
    """Drop the machine-local lease file. Returns True if a file was removed."""
    plan_rel = plan_rel.replace("\\", "/")
    path = lease_path(plans_root, plan_rel)
    if not path.is_file():
        return False
    if not force and agent_id is not None:
        existing = read_lease(plans_root, plan_rel)
        if existing and existing.agent_id != agent_id and not existing.expired:
            raise ClaimError(
                f"cannot release lease held by {existing.agent_id!r} as {agent_id!r}"
            )
    try:
        path.unlink()
        return True
    except OSError:
        return False


def release(
    plans_root: Path,
    plan_rel: str,
    *,
    agent_id: str | None = None,
    force: bool = False,
) -> bool:
    """Drop a lease locally and on the shared branch. True if a local file was removed.

    Does not move plan files. ``force`` applies to the local store only: the
    shared lease is released only when this host (and agent, if given) owns it,
    so a forced local release can never delete another machine's live lease. A
    shared-branch failure never blocks or raises.
    """
    plan_rel = plan_rel.replace("\\", "/")
    removed = _release_local(plans_root, plan_rel, agent_id=agent_id, force=force)
    _branch_call(
        plans_root, plan_rel,
        lambda root, slug: lease_branch.release(root, slug, agent_id),
        blocking=False,
    )
    return removed


def owner_of(plans_root: Path, plan_rel: str) -> str | None:
    """Return who holds an active lease, or None.

    Local leases return ``agent_id``. A shared lease on **this** host returns
    ``agent_id`` too. A live shared lease on another host returns
    ``agent_id@host`` so a same-named agent here does not look like the owner.
    """
    plan_rel = plan_rel.replace("\\", "/")
    lease = active_lease(plans_root, plan_rel)
    if lease:
        return lease.agent_id
    ran, leases = _branch_call(
        plans_root, None, lambda root, _slug: lease_branch.list_leases(root), blocking=False
    )
    slug = lease_branch.slug_of(plan_rel)
    for lz in leases or []:
        if lz.slug == slug and not lz.expired():
            if lz.owned_by(None):
                return lz.agent_id
            return f"{lz.agent_id}@{lz.host}"
    return None


def claimed_rels(plans_root: Path) -> set[str]:
    """Set of plan_rel strings with unexpired leases (local, plus ready plans leased on the shared branch)."""
    out: set[str] = set()
    remote = _remote_live_slugs(plans_root)
    if remote:
        for lane in READY_LANES:
            for plan in (plans_root / lane).glob("*.md"):
                if lease_branch.slug_of(plan.name) in remote:
                    out.add(f"{lane}/{plan.name}")
    d = leases_dir(plans_root)
    if not d.is_dir():
        return out
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            lease = Lease.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if not lease.expired:
            out.add(lease.plan_rel)
    return out


def in_progress_owned_by(plans_root: Path, agent_id: str) -> list[str]:
    """Relative paths under in-progress/ owned by agent_id (active lease)."""
    ip = plans_root / IN_PROGRESS
    if not ip.is_dir():
        return []
    owned: list[str] = []
    for path in sorted(ip.glob("*.md")):
        if path.name == "README.md":
            continue
        rel = f"{IN_PROGRESS}/{path.name}"
        lease = active_lease(plans_root, rel)
        if lease and lease.agent_id == agent_id:
            owned.append(rel)
    return owned


def _assert_owner_if_in_progress(
    plans_root: Path, plan_rel: str, agent_id: str | None
) -> Lease | None:
    """If plan is in-progress, require agent_id matches active lease (or orphan)."""
    if not plan_rel.startswith(f"{IN_PROGRESS}/"):
        return read_lease(plans_root, plan_rel)
    existing = active_lease(plans_root, plan_rel)
    if existing is None:
        return None
    if agent_id is None:
        raise ClaimError(
            f"in-progress plan owned by {existing.agent_id!r}; pass agent_id"
        )
    if existing.agent_id != agent_id:
        raise ClaimError(
            f"in-progress plan owned by {existing.agent_id!r} — cannot move as {agent_id!r}"
        )
    return existing


def _move_file(plans_root: Path, plan_rel: str, dest_lane: str) -> tuple[str, Path]:
    """Rename plan into dest_lane; return (new_rel, absolute path)."""
    plan_rel = plan_rel.replace("\\", "/")
    src = plans_root / plan_rel
    if not src.is_file():
        raise ClaimError(f"plan file missing: {plan_rel}")
    dest_rel = f"{dest_lane}/{src.name}"
    dest = plans_root / dest_rel
    if dest.exists() and dest.resolve() != src.resolve():
        raise ClaimError(f"destination already exists: {dest_rel}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest)
    except OSError as exc:
        raise ClaimError(f"could not move {plan_rel} → {dest_rel}: {exc}") from exc
    return dest_rel, dest.resolve()


def park(
    plans_root: Path,
    plan_rel: str,
    dest: str,
    *,
    agent_id: str | None = None,
) -> Path:
    """Move a plan to ``ambiguous/`` or ``blocked/`` and drop any lease.

    Allowed sources: ``bugs/``, ``features/``, ``in-progress/`` (owner only).
    Not executable after park — human (or later agent with clear intent) moves
    back to bugs|features when unblocked / clarified.
    """
    dest = dest.strip().lower()
    if dest not in PARK_LANES:
        raise ClaimError(f"park dest must be ambiguous|blocked, got {dest!r}")
    plans_root = plans_root.resolve()
    plan_rel = plan_rel.replace("\\", "/")
    lane = plan_rel.split("/", 1)[0] if "/" in plan_rel else ""
    if lane not in (*READY_LANES, IN_PROGRESS):
        raise ClaimError(
            f"park only from bugs|features|in-progress, got {plan_rel}"
        )
    _assert_owner_if_in_progress(plans_root, plan_rel, agent_id)
    # Drop lease on current path (and any stale keys)
    release(plans_root, plan_rel, force=True)
    _dest_rel, dest_path = _move_file(plans_root, plan_rel, dest)
    return dest_path


def return_to_ready(
    plans_root: Path,
    plan_rel: str,
    *,
    agent_id: str | None = None,
    target_lane: str | None = None,
) -> Path:
    """Move plan back to ``bugs/`` or ``features/`` and drop lease.

    Typical use: in-progress work you cannot finish — release for another agent
    (as opposed to ``park(..., blocked)`` which removes it from the ready queue).

    Also allowed from ``ambiguous/`` or ``blocked/`` when returning clarified work
    (any agent or human; ownership not required for park lanes).

    ``target_lane`` defaults to origin from lease, else ``features``.
    """
    plans_root = plans_root.resolve()
    plan_rel = plan_rel.replace("\\", "/")
    lane = plan_rel.split("/", 1)[0] if "/" in plan_rel else ""
    lease = read_lease(plans_root, plan_rel)

    if lane == IN_PROGRESS:
        lease = _assert_owner_if_in_progress(plans_root, plan_rel, agent_id) or lease
    elif lane in PARK_LANES:
        pass  # anyone may return parked work to ready
    elif lane in READY_LANES:
        raise ClaimError(f"already ready: {plan_rel}")
    else:
        raise ClaimError(
            f"return_to_ready from in-progress|ambiguous|blocked only, got {plan_rel}"
        )

    if target_lane:
        dest_lane = target_lane.strip().lower()
    elif lease and lease.origin_rel and lease.origin_rel.startswith(READY_PREFIXES):
        dest_lane = lease.origin_rel.split("/", 1)[0]
    else:
        dest_lane = "features"
    if dest_lane not in READY_LANES:
        raise ClaimError(f"target_lane must be bugs|features, got {dest_lane!r}")

    release(plans_root, plan_rel, force=True)
    _dest_rel, dest_path = _move_file(plans_root, plan_rel, dest_lane)
    return dest_path


class ClaimError(Exception):
    """Raised when a plan cannot be claimed, parked, or released."""
