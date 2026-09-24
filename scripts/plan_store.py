#!/usr/bin/env python3
"""The one access point for plans on disk under ``.plans/``.

Every script that lists a lane, finds a plan by slug, reads a plan, or moves one
between lanes goes through this module. Callers see **lanes, slugs and ``rel``
strings** (``"<lane>/<name>"``, the key leases and ``PlanRecord.rel`` use) — never
a file extension, a glob pattern, or whether a plan is a file or a directory.
That is the contract: when the on-disk layout changes, only a :class:`Layout`
here changes, and no caller does.

Today there is one layout, :class:`FlatLayout` — a plan is a single
``<slug>.md`` (or private ``<slug>.local.md``) file directly inside its lane
directory. Tests prove the contract by swapping in a second layout with
:func:`using_layout` and running unchanged callers against it.

Lane directories are the non-dot children of ``.plans/``; dot directories
(``.leases/``, ``.releases/``) are sidecars, not lanes. ``README.md`` inside a
lane is documentation, never a plan.

Claim / heartbeat / release live in ``plan_lease.py`` (they own the lease
files); it performs its lane moves through :func:`move` here, and the thin
wrappers at the bottom of this module expose them under one roof so a caller
such as the ``anchor`` CLI needs a single import.
"""
from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from plan_parse import safe_read_text

PLANS_DIRNAME = ".plans"
RELEASES_DIRNAME = ".releases"
RELEASE_SUFFIX = ".md"

# Completed plans may carry a date prefix: ``YYYY-MM-DD-<slug>``.
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def strip_date_prefix(slug: str) -> str:
    """``2026-08-01-foo`` → ``foo``; anything else unchanged."""
    return _DATE_PREFIX_RE.sub("", slug)


class Layout(Protocol):
    """How plans are laid out inside one lane directory.

    ``name`` is the entry's identity inside its lane (what ``rel`` carries and
    what a lane move preserves); ``doc`` is the readable plan document.
    """

    def entries(self, lane_dir: Path) -> Iterator[tuple[str, Path]]:
        """Yield ``(name, doc_path)`` for every plan in ``lane_dir``, any order."""
        ...

    def entry_path(self, lane_dir: Path, name: str) -> Path:
        """Filesystem object a lane move renames (a file, or a directory)."""
        ...

    def doc_path(self, lane_dir: Path, name: str) -> Path:
        """The plan document for ``name`` (may not exist)."""
        ...

    def slug_of(self, name: str) -> str:
        """Plan slug for an entry name (date prefix, if any, kept)."""
        ...

    def names_for(self, slug: str) -> tuple[str, ...]:
        """Candidate entry names a slug may live under, preferred first."""
        ...

    def is_entry_name(self, text: str) -> bool:
        """True when ``text`` is spelled like an entry name rather than a slug."""
        ...

    def is_local(self, name: str) -> bool:
        """True for a private (untracked) plan."""
        ...

    def name_from_path(self, lane_dir: Path, path: Path) -> str | None:
        """Entry name for any path inside ``lane_dir`` belonging to a plan."""
        ...

    def git_pathspecs(self, lane: str, slug: str) -> tuple[str, ...]:
        """Pathspecs, relative to ``.plans/``, matching ``slug`` in ``lane``
        (dated completion names included) — for history lookups."""
        ...


class FlatLayout:
    """One markdown file per plan: ``<lane>/<slug>.md`` or ``<slug>.local.md``."""

    SUFFIX = ".md"
    LOCAL_SUFFIX = ".local.md"
    README = "README.md"

    def entries(self, lane_dir: Path) -> Iterator[tuple[str, Path]]:
        for path in lane_dir.glob(f"*{self.SUFFIX}"):
            if path.name == self.README:
                continue
            yield path.name, path

    def entry_path(self, lane_dir: Path, name: str) -> Path:
        return lane_dir / name

    def doc_path(self, lane_dir: Path, name: str) -> Path:
        return lane_dir / name

    def slug_of(self, name: str) -> str:
        if name.endswith(self.LOCAL_SUFFIX):
            return name[: -len(self.LOCAL_SUFFIX)]
        if name.endswith(self.SUFFIX):
            return name[: -len(self.SUFFIX)]
        return Path(name).stem

    def names_for(self, slug: str) -> tuple[str, ...]:
        return (f"{slug}{self.SUFFIX}", f"{slug}{self.LOCAL_SUFFIX}")

    def is_entry_name(self, text: str) -> bool:
        return text.endswith(self.SUFFIX)

    def is_local(self, name: str) -> bool:
        return name.endswith(self.LOCAL_SUFFIX)

    def name_from_path(self, lane_dir: Path, path: Path) -> str | None:
        try:
            rel = path.relative_to(lane_dir)
        except ValueError:
            return None
        if len(rel.parts) != 1 or not self.is_entry_name(rel.parts[0]):
            return None
        return rel.parts[0]

    def git_pathspecs(self, lane: str, slug: str) -> tuple[str, ...]:
        return (
            f"{lane}/{slug}{self.SUFFIX}",
            f"{lane}/{slug}{self.LOCAL_SUFFIX}",
            f"{lane}/*-{slug}{self.SUFFIX}",
            f"{lane}/*-{slug}{self.LOCAL_SUFFIX}",
        )


_layout: Layout = FlatLayout()


def layout() -> Layout:
    """The active layout."""
    return _layout


@contextlib.contextmanager
def using_layout(new: Layout) -> Iterator[Layout]:
    """Temporarily swap the active layout (tests prove callers are layout-blind)."""
    global _layout
    prev = _layout
    _layout = new
    try:
        yield new
    finally:
        _layout = prev


@dataclass(frozen=True)
class PlanRef:
    """A plan's address. ``path`` is the readable plan document."""

    lane: str
    name: str
    path: Path

    @property
    def rel(self) -> str:
        """``<lane>/<name>`` — the lease key and ``PlanRecord.rel``."""
        return f"{self.lane}/{self.name}"

    @property
    def slug(self) -> str:
        return _layout.slug_of(self.name)

    @property
    def base_slug(self) -> str:
        """Slug with any ``YYYY-MM-DD-`` completion prefix removed."""
        return strip_date_prefix(self.slug)

    @property
    def local(self) -> bool:
        return _layout.is_local(self.name)

    def mtime(self) -> float:
        """Document mtime, ``0.0`` when unreadable."""
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0


# --- naming helpers (for callers holding a bare name or an outside path) -----


def slug_of_name(name: str) -> str:
    return _layout.slug_of(name)


def slug_of_path(path: Path) -> str:
    """Slug for a plan document path, including one outside ``.plans/``."""
    lane_dir = path.parent
    name = _layout.name_from_path(lane_dir, path)
    if name is None:
        # Nested layouts: the entry is a directory holding the document.
        name = _layout.name_from_path(lane_dir.parent, path)
    return _layout.slug_of(name if name is not None else path.name)


def is_entry_name(text: str) -> bool:
    return _layout.is_entry_name(text)


def is_local_path(path: Path) -> bool:
    lane_dir = path.parent
    name = _layout.name_from_path(lane_dir, path) or _layout.name_from_path(
        lane_dir.parent, path
    )
    return _layout.is_local(name if name is not None else path.name)


# --- roots and lanes ---------------------------------------------------------


def plans_root_for(project_root: Path) -> Path:
    return project_root / PLANS_DIRNAME


def lane_names(plans_root: Path) -> list[str]:
    """Sorted lane directory names (dot-dirs are sidecars, not lanes)."""
    if not plans_root.is_dir():
        return []
    return sorted(
        p.name for p in plans_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def stray_entries(plans_root: Path) -> list[str]:
    """Plan-shaped names sitting directly in ``.plans/``, outside every lane."""
    if not plans_root.is_dir():
        return []
    return [
        name
        for name, _doc in sorted(_layout.entries(plans_root), key=lambda e: e[0])
    ]


def lane_exists(plans_root: Path, lane: str) -> bool:
    return (plans_root / lane).is_dir()


def _ref(plans_root: Path, lane: str, name: str) -> PlanRef:
    return PlanRef(lane=lane, name=name, path=_layout.doc_path(plans_root / lane, name))


def list_lane(plans_root: Path, lane: str) -> list[PlanRef]:
    """Plans in one lane, sorted by entry name. Missing lane → ``[]``."""
    lane_dir = plans_root / lane
    if not lane_dir.is_dir():
        return []
    return [
        PlanRef(lane=lane, name=name, path=doc)
        for name, doc in sorted(_layout.entries(lane_dir), key=lambda e: e[0])
    ]


def list_lanes(plans_root: Path, lanes: Iterable[str]) -> list[PlanRef]:
    out: list[PlanRef] = []
    for lane in lanes:
        out.extend(list_lane(plans_root, lane))
    return out


def list_all(plans_root: Path) -> list[PlanRef]:
    """Every plan in every lane, lanes sorted, then names sorted."""
    return list_lanes(plans_root, lane_names(plans_root))


def count(plans_root: Path, lane: str) -> int:
    lane_dir = plans_root / lane
    if not lane_dir.is_dir():
        return 0
    return sum(1 for _ in _layout.entries(lane_dir))


# --- lookup ------------------------------------------------------------------


def get(plans_root: Path, rel: str) -> PlanRef | None:
    """The plan at ``<lane>/<name>``, or ``None`` if it is not there."""
    rel = rel.replace("\\", "/").strip("/")
    if "/" not in rel:
        return None
    lane, name = rel.split("/", 1)
    if "/" in name or not name:
        return None
    ref = _ref(plans_root, lane, name)
    return ref if ref.path.is_file() else None


def lookup(plans_root: Path, lane: str, slug: str) -> list[PlanRef]:
    """Existing plans named ``slug`` in ``lane`` (every spelling the layout allows)."""
    out: list[PlanRef] = []
    for name in _layout.names_for(slug):
        ref = _ref(plans_root, lane, name)
        if ref.path.is_file():
            out.append(ref)
    return out


def find_slug(
    plans_root: Path,
    slug: str,
    *,
    lanes: Iterable[str] | None = None,
    dated: bool = True,
) -> list[PlanRef]:
    """Every plan whose slug matches (case-insensitive), across ``lanes`` or all.

    ``dated=True`` also matches ``YYYY-MM-DD-<slug>`` completion names.
    """
    needle = slug.lower()
    pool = list_all(plans_root) if lanes is None else list_lanes(plans_root, lanes)
    out: list[PlanRef] = []
    for ref in pool:
        s = ref.slug.lower()
        if s == needle or (dated and _DATE_PREFIX_RE.match(s) and strip_date_prefix(s) == needle):
            out.append(ref)
    return out


def ref_for_path(plans_root: Path, path: Path) -> PlanRef | None:
    """The plan a filesystem path belongs to, when it lies inside a lane."""
    try:
        rel = path.resolve().relative_to(plans_root.resolve())
    except ValueError:
        return None
    if not rel.parts or rel.parts[0].startswith("."):
        return None
    lane = rel.parts[0]
    lane_dir = plans_root.resolve() / lane
    name = _layout.name_from_path(lane_dir, path.resolve())
    if name is None:
        return None
    return PlanRef(lane=lane, name=name, path=_layout.doc_path(plans_root / lane, name))


def git_pathspecs(lane: str, slug: str) -> tuple[str, ...]:
    """Project-relative pathspecs for ``slug`` in ``lane`` (history lookups)."""
    return tuple(f"{PLANS_DIRNAME}/{p}" for p in _layout.git_pathspecs(lane, slug))


# --- content -----------------------------------------------------------------


def read_text(ref: PlanRef) -> tuple[str | None, str | None]:
    """``(text, None)`` or ``(None, reason)`` — never raises."""
    return safe_read_text(ref.path)


def scan(plans_root: Path, lanes: Iterable[str] | None = None) -> Iterator[tuple[PlanRef, str]]:
    """Yield ``(ref, text)`` for every readable plan; unreadable ones are skipped."""
    pool = list_all(plans_root) if lanes is None else list_lanes(plans_root, lanes)
    for ref in pool:
        text, err = read_text(ref)
        if err is None and text is not None:
            yield ref, text


def list_release_files(plans_root: Path) -> list[tuple[str, Path]]:
    """``(release slug, path)`` for each ``.releases/`` definition, sorted.

    Release definitions are always single markdown files — they are sidecars,
    not plans, so the plan layout does not apply to them.
    """
    d = plans_root / RELEASES_DIRNAME
    if not d.is_dir():
        return []
    return [
        (p.name[: -len(RELEASE_SUFFIX)], p)
        for p in sorted(d.iterdir())
        if p.is_file() and p.suffix == RELEASE_SUFFIX and p.name != FlatLayout.README
    ]


def release_file(plans_root: Path, slug: str) -> Path:
    return plans_root / RELEASES_DIRNAME / f"{slug}{RELEASE_SUFFIX}"


def create(plans_root: Path, lane: str, slug: str, text: str, *, local: bool = False) -> PlanRef:
    """Write a new plan. Refuses when that slug already has a plan in ``lane``."""
    if lookup(plans_root, lane, slug):
        raise FileExistsError(f"a plan named {slug!r} already exists in {lane}/")
    names = _layout.names_for(slug)
    ref = _ref(plans_root, lane, names[1] if local else names[0])
    ref.path.parent.mkdir(parents=True, exist_ok=True)
    ref.path.write_text(text, encoding="utf-8")
    return ref


# --- moves -------------------------------------------------------------------


class PlanMoveError(Exception):
    """A lane move could not happen (missing source, occupied destination, OS error)."""


def move(plans_root: Path, rel: str, dest_lane: str) -> PlanRef:
    """Move a plan to ``dest_lane`` keeping its name. Returns the new ref."""
    src = get(plans_root, rel)
    if src is None:
        raise PlanMoveError(f"plan file missing: {rel}")
    src_entry = _layout.entry_path(plans_root / src.lane, src.name)
    dest_entry = _layout.entry_path(plans_root / dest_lane, src.name)
    dest_rel = f"{dest_lane}/{src.name}"
    if dest_entry.exists() and dest_entry.resolve() != src_entry.resolve():
        raise PlanMoveError(f"destination already exists: {dest_rel}")
    dest_entry.parent.mkdir(parents=True, exist_ok=True)
    try:
        src_entry.rename(dest_entry)
    except OSError as exc:
        raise PlanMoveError(f"could not move {rel} → {dest_rel}: {exc}") from exc
    return _ref(plans_root, dest_lane, src.name)


def destination_taken(plans_root: Path, rel: str, dest_lane: str) -> bool:
    """True when moving ``rel`` into ``dest_lane`` would collide with another plan."""
    src = get(plans_root, rel)
    if src is None:
        return False
    src_entry = _layout.entry_path(plans_root / src.lane, src.name)
    dest_entry = _layout.entry_path(plans_root / dest_lane, src.name)
    return dest_entry.exists() and dest_entry.resolve() != src_entry.resolve()


# --- lease operations, under one roof ----------------------------------------
# plan_lease imports this module, so these import it lazily.


def claim(plans_root: Path, rel: str, agent_id: str, *, recover: bool = False):
    """Claim a ready plan (move to in-progress + lease). See ``plan_lease.claim_and_move``."""
    import plan_lease

    return plan_lease.claim_and_move(plans_root, rel, agent_id, recover=recover)


def heartbeat(plans_root: Path, rel: str, agent_id: str):
    import plan_lease

    return plan_lease.renew(plans_root, rel, agent_id)


def release(plans_root: Path, rel: str, agent_id: str | None = None) -> bool:
    import plan_lease

    return plan_lease.release(plans_root, rel, agent_id=agent_id)


def owner(plans_root: Path, rel: str) -> str | None:
    import plan_lease

    return plan_lease.owner_of(plans_root, rel)
