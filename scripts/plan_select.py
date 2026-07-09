#!/usr/bin/env python3
"""Shared plan selection for `/work` and headless `work_once.py`.

Path is authoritative:

  - drafts/ — not ready (never execute)
  - bugs/, features/ — ready (pick by priority + fit)
  - in-progress/ — claimed; **only the agent that moved it there** may work it
  - ambiguous/ — half-baked (never auto-execute; agent may park here)
  - blocked/ — cannot proceed (never auto-execute; agent may park here)
  - completed/ — archive (never execute)

Priority for bare pick:

  1. Own in-progress plans first (resume)
  2. All bugs/*.md before any feature
  3. within a lane by Priority P1 → P2 → P3 (default P2), then Value high →
     medium → low (default medium), then oldest first (mtime), then filename
  4. Model-fit filter unless no_fit_check or explicit slug/path override
  5. Skip plans with **unmet Depends on** unless no_dep_check

Ignore every in-progress plan you did not claim (lease agent_id mismatch or no
matching lease for this agent).

**Depends on:** header slugs (or ``none``). A dependency is met if the slug is only
under completed/ (or git history shows it was removed from completed/), and is not
still open in another lane. Coordinators should scan existing plans when drafting
to propose Depends on; executors must not start work with unmet deps.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

READY_LANES = ("bugs", "features")
IN_PROGRESS_LANE = "in-progress"
PARK_LANES = frozenset({"ambiguous", "blocked"})
EXECUTABLE_LANES = (*READY_LANES, IN_PROGRESS_LANE)
# Never pick/execute these (parked + draft + archive)
NON_EXECUTABLE_LANES = frozenset({"drafts", "completed", "ambiguous", "blocked"})
# Back-compat alias used by assert helpers
BLOCKED_LANES = NON_EXECUTABLE_LANES
VALUE_RANK = {"high": 0, "medium": 1, "low": 2}
PRIORITY_RANK = {"P1": 0, "P2": 1, "P3": 2}
DEFAULT_PRIORITY = "P2"
FIT_TIERS = ("small", "mid", "reasoner", "frontier")
FIT_RANK = {t: i for i, t in enumerate(FIT_TIERS)}

# Map endpoints.yaml / fleet tiers → Preferred-models fit tiers.
REGISTRY_TIER_TO_FIT: dict[str, str] = {
    "swarm": "small",
    "executor": "mid",
    "executor-heavy": "mid",
    "reasoner": "reasoner",
    "frontier": "frontier",
    "detached": "mid",
}

VALUE_RE = re.compile(r"^\s*-\s*\*\*Value:\*\*\s*(\w+)", re.MULTILINE | re.IGNORECASE)
PRIORITY_RE = re.compile(
    r"^\s*-\s*\*\*Priority:\*\*\s*(\S+)", re.MULTILINE | re.IGNORECASE
)
PREFERRED_RE = re.compile(
    r"^\s*-\s*\*\*Preferred models:\*\*\s*(.+)$", re.MULTILINE | re.IGNORECASE
)
DEPENDS_RE = re.compile(
    r"^\s*-\s*\*\*Depends on:\*\*\s*(.+)$", re.MULTILINE | re.IGNORECASE
)
DEPENDS_SECTION_RE = re.compile(
    r"^##\s+Depends on(?:\s*\(detail\))?\s*$([\s\S]*?)(?=^##\s|\Z)",
    re.MULTILINE | re.IGNORECASE,
)
DEPENDS_BULLET_RE = re.compile(
    r"^\s*-\s*`?([a-zA-Z0-9][a-zA-Z0-9._/-]*)`?",
    re.MULTILINE,
)
TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
# Lanes where a dependency slug still counts as unfinished work
OPEN_LANES = (
    "drafts",
    "bugs",
    "features",
    "in-progress",
    "ambiguous",
    "blocked",
)


class Fit(str, Enum):
    GOOD = "good"
    OVERQUALIFIED = "overqualified"
    UNDERQUALIFIED = "underqualified"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Worker:
    """Identity used for Preferred-models matching."""

    name: str
    tier: str  # small | mid | reasoner | frontier

    def __post_init__(self) -> None:
        object.__setattr__(self, "tier", normalize_fit_tier(self.tier))


@dataclass(frozen=True)
class PlanRecord:
    path: Path  # absolute
    rel: str  # e.g. features/foo.md relative to .plans/
    lane: str
    slug: str
    value: str
    priority: str
    preferred: str | None
    title: str
    fit: Fit = Fit.UNKNOWN
    owner: str | None = None  # lease agent_id when known
    depends_on: tuple[str, ...] = ()
    deps_met: bool = True
    deps_unmet: tuple[str, ...] = ()
    deps_notes: tuple[str, ...] = ()  # human-readable check notes

    @property
    def ready(self) -> bool:
        return self.lane in READY_LANES


def normalize_fit_tier(tier: str) -> str:
    t = (tier or "mid").strip().lower()
    if t in FIT_RANK:
        return t
    mapped = REGISTRY_TIER_TO_FIT.get(t)
    if mapped:
        return mapped
    return "mid"


def plans_root_for(project_root: Path) -> Path:
    return project_root / ".plans"


def plan_slug(path: Path) -> str:
    name = path.name
    if name.endswith(".local.md"):
        return name[: -len(".local.md")]
    if name.endswith(".md"):
        return name[:-3]
    return path.stem


def parse_value(text: str) -> str:
    m = VALUE_RE.search(text)
    if not m:
        return "medium"
    v = m.group(1).lower()
    return v if v in VALUE_RANK else "medium"


def parse_priority(text: str) -> str:
    """Parse the ``Priority:`` header → ``P1|P2|P3``; tolerant, default ``P2``.

    Accepts ``P1``/``p1``/``1`` and trailing junk (``P1.``, ``P2 — note``).
    Anything unrecognized falls back to the default priority.
    """
    m = PRIORITY_RE.search(text)
    if not m:
        return DEFAULT_PRIORITY
    raw = m.group(1).strip().strip("`").upper()
    m2 = re.match(r"P?([123])", raw)
    if m2:
        return f"P{m2.group(1)}"
    return DEFAULT_PRIORITY


def parse_preferred(text: str) -> str | None:
    m = PREFERRED_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    return raw or None


def parse_title(text: str, fallback: str) -> str:
    m = TITLE_RE.search(text)
    return m.group(1).strip() if m else fallback


def parse_depends_on(text: str) -> list[str]:
    """Parse Depends on header and optional ## Depends on detail bullets → slugs."""
    slugs: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        s = raw.strip().strip("`").strip()
        if not s or s.lower() in {"none", "n/a", "-", "nil", "null"}:
            return
        # header may be "slug — note" or "slug (note)"
        s = re.split(r"\s+[—–-]\s+|\s+\(", s, maxsplit=1)[0].strip().strip("`")
        if not s or s.lower() in {"none", "n/a"}:
            return
        # drop path prefixes if someone wrote features/foo
        if "/" in s:
            s = s.rsplit("/", 1)[-1]
        if s.endswith(".md"):
            s = plan_slug(Path(s))
        key = s.lower()
        if key not in seen:
            seen.add(key)
            slugs.append(s)

    m = DEPENDS_RE.search(text)
    if m:
        for part in m.group(1).split(","):
            _add(part)

    sec = DEPENDS_SECTION_RE.search(text)
    if sec:
        for bm in DEPENDS_BULLET_RE.finditer(sec.group(1)):
            _add(bm.group(1))

    return slugs


def find_slug_paths(plans_root: Path, slug: str) -> list[tuple[str, Path]]:
    """Return (lane, path) for every plan file whose slug matches."""
    found: list[tuple[str, Path]] = []
    if not plans_root.is_dir():
        return found
    needle = slug.lower()
    for lane_dir in sorted(p for p in plans_root.iterdir() if p.is_dir()):
        if lane_dir.name.startswith("."):
            continue
        for path in lane_dir.glob("*.md"):
            if path.name == "README.md":
                continue
            if plan_slug(path).lower() == needle:
                found.append((lane_dir.name, path))
            # dated completion names: YYYY-MM-DD-slug.md
            stem = path.name
            if stem.endswith(".local.md"):
                body = stem[: -len(".local.md")]
            elif stem.endswith(".md"):
                body = stem[:-3]
            else:
                body = path.stem
            if re.match(r"^\d{4}-\d{2}-\d{2}-", body):
                body_slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", body)
                if body_slug.lower() == needle:
                    found.append((lane_dir.name, path))
    return found


def _git_completed_evidence(project_root: Path, slug: str) -> tuple[bool, str]:
    """True if git history shows the plan under .plans/completed/ (incl. deleted)."""
    if not project_root.is_dir():
        return False, "no project root for git check"
    patterns = [
        f".plans/completed/{slug}.md",
        f".plans/completed/{slug}.local.md",
        f".plans/completed/*-{slug}.md",
        f".plans/completed/*-{slug}.local.md",
    ]
    try:
        # Any commit that touched a completed path for this slug
        r = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "log",
                "--all",
                "--oneline",
                "--",
                *patterns,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"git check failed: {exc}"
    if r.returncode != 0:
        return False, "git log failed (not a repo?)"
    out = (r.stdout or "").strip()
    if out:
        first = out.splitlines()[0][:80]
        return True, f"git history under completed/ ({first})"
    return False, "no git history under .plans/completed/ for slug"


def dependency_status(
    plans_root: Path,
    dep_slug: str,
    *,
    git_check: bool = True,
) -> tuple[bool, str]:
    """Return (satisfied, note) for one dependency slug.

    Satisfied when the dependency is complete: present under completed/ and not
    still open elsewhere, OR git shows it lived under completed/ (e.g. later
    deleted) and it is not open now. Unsatisfied if still in any open lane or
    never evidenced complete.
    """
    paths = find_slug_paths(plans_root, dep_slug)
    open_hits = [(lane, p) for lane, p in paths if lane in OPEN_LANES]
    completed_hits = [(lane, p) for lane, p in paths if lane == "completed"]

    if open_hits:
        locs = ", ".join(f"{lane}/{p.name}" for lane, p in open_hits)
        return False, f"still open: {locs}"

    if completed_hits:
        locs = ", ".join(p.name for _, p in completed_hits)
        return True, f"in completed/: {locs}"

    if git_check:
        ok, note = _git_completed_evidence(plans_root.parent, dep_slug)
        if ok:
            return True, note

    return False, "not found complete (no completed/ file; no git evidence)"


def evaluate_dependencies(
    plans_root: Path,
    depends_on: list[str] | tuple[str, ...],
    *,
    git_check: bool = True,
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Return (all_met, unmet_slugs, notes)."""
    if not depends_on:
        return True, (), ()
    unmet: list[str] = []
    notes: list[str] = []
    for slug in depends_on:
        ok, note = dependency_status(plans_root, slug, git_check=git_check)
        notes.append(f"{slug}: {note}")
        if not ok:
            unmet.append(slug)
    return (not unmet), tuple(unmet), tuple(notes)


def inventory_all_plan_summaries(plans_root: Path) -> list[dict[str, str]]:
    """Lightweight inventory for coordinators: slug, lane, title, goal snippet.

    Used when evaluating whether a plan under discussion should Depend on others.
    """
    if not plans_root.is_dir():
        return []
    goal_re = re.compile(
        r"^##\s+Goal\s*$([\s\S]*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE
    )
    out: list[dict[str, str]] = []
    for lane_dir in sorted(p for p in plans_root.iterdir() if p.is_dir()):
        if lane_dir.name.startswith("."):
            continue
        for path in sorted(lane_dir.glob("*.md")):
            if path.name == "README.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            gm = goal_re.search(text)
            goal = " ".join((gm.group(1) if gm else "").split())[:240]
            out.append(
                {
                    "slug": plan_slug(path),
                    "lane": lane_dir.name,
                    "rel": f"{lane_dir.name}/{path.name}",
                    "title": parse_title(text, path.name),
                    "goal": goal,
                    "depends_on": ", ".join(parse_depends_on(text)) or "none",
                }
            )
    return out


def _parse_preferred_tokens(preferred: str | None) -> tuple[list[str], list[str]]:
    if not preferred:
        return [], []
    tiers: list[str] = []
    names: list[str] = []
    for part in preferred.split(","):
        tok = part.strip()
        if not tok:
            continue
        low = tok.lower()
        if low in FIT_RANK:
            tiers.append(low)
        else:
            names.append(low)
    return tiers, names


def classify_fit(worker: Worker, preferred: str | None) -> Fit:
    """Classify worker vs plan Preferred models (same rules as /work)."""
    tiers, names = _parse_preferred_tokens(preferred)
    if not tiers and not names:
        return Fit.UNKNOWN

    wname = worker.name.lower().replace("_", " ").replace("-", " ")
    for n in names:
        n_norm = n.replace("_", " ").replace("-", " ")
        if n_norm in wname or wname in n_norm:
            return Fit.GOOD
        n_parts = set(n_norm.split())
        w_parts = set(wname.split())
        if n_parts and n_parts <= w_parts:
            return Fit.GOOD
        if any(len(p) >= 4 and p in wname for p in n_parts):
            return Fit.GOOD

    if tiers and worker.tier in tiers:
        return Fit.GOOD

    if tiers:
        wr = FIT_RANK.get(worker.tier, FIT_RANK["mid"])
        max_pref = max(FIT_RANK[t] for t in tiers)
        min_pref = min(FIT_RANK[t] for t in tiers)
        if wr > max_pref:
            return Fit.OVERQUALIFIED
        if wr < min_pref:
            return Fit.UNDERQUALIFIED
        if wr not in {FIT_RANK[t] for t in tiers}:
            return Fit.UNKNOWN
        return Fit.GOOD

    return Fit.UNKNOWN


def _record_from_path(
    path: Path,
    lane: str,
    worker: Worker,
    *,
    owner: str | None = None,
    plans_root: Path | None = None,
    git_check: bool = True,
) -> PlanRecord:
    text = path.read_text(encoding="utf-8")
    preferred = parse_preferred(text)
    deps = tuple(parse_depends_on(text))
    root = plans_root if plans_root is not None else path.parent.parent
    met, unmet, notes = evaluate_dependencies(root, deps, git_check=git_check)
    return PlanRecord(
        path=path.resolve(),
        rel=f"{lane}/{path.name}",
        lane=lane,
        slug=plan_slug(path),
        value=parse_value(text),
        priority=parse_priority(text),
        preferred=preferred,
        title=parse_title(text, path.name),
        fit=classify_fit(worker, preferred),
        owner=owner,
        depends_on=deps,
        deps_met=met,
        deps_unmet=unmet,
        deps_notes=notes,
    )


def plan_sort_key(r: PlanRecord) -> tuple:
    """Ready-lane ordering key: lane → priority → value → oldest → filename.

    Bugs (lane 0) always precede features (lane 1) — priority never lets a
    feature jump a ready bug. Within a lane: ``P1`` before ``P2`` before ``P3``
    (default ``P2``), then ``high`` before ``medium`` before ``low`` (default
    ``medium``), then oldest first (file mtime), with filename as final tiebreak.
    """
    lane_i = 0 if r.lane == "bugs" else 1
    pri_i = PRIORITY_RANK.get(r.priority, PRIORITY_RANK[DEFAULT_PRIORITY])
    val_i = VALUE_RANK.get(r.value, VALUE_RANK["medium"])
    try:
        mtime = r.path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (lane_i, pri_i, val_i, mtime, r.path.name.lower())


def inventory_ready(plans_root: Path, worker: Worker | None = None) -> list[PlanRecord]:
    """List ready-lane plans (bugs + features only), sorted by /work priority."""
    if not plans_root.is_dir():
        return []

    w = worker or Worker(name="unknown", tier="mid")
    records: list[PlanRecord] = []
    for lane in READY_LANES:
        lane_dir = plans_root / lane
        if not lane_dir.is_dir():
            continue
        for path in sorted(lane_dir.glob("*.md")):
            if path.name == "README.md":
                continue
            records.append(_record_from_path(path, lane, w, plans_root=plans_root))

    records.sort(key=plan_sort_key)
    return records


def inventory_in_progress(
    plans_root: Path,
    worker: Worker | None = None,
    *,
    agent_id: str | None = None,
    only_mine: bool = False,
) -> list[PlanRecord]:
    """List plans under in-progress/.

    When only_mine=True and agent_id is set, return only plans this agent owns
    (active lease). Other agents' work is omitted — callers must ignore it.
    """
    # Local import avoids circular import at module load for pure select tests
    from plan_lease import active_lease

    ip = plans_root / IN_PROGRESS_LANE
    if not ip.is_dir():
        return []
    w = worker or Worker(name="unknown", tier="mid")
    records: list[PlanRecord] = []
    for path in sorted(ip.glob("*.md")):
        if path.name == "README.md":
            continue
        rel = f"{IN_PROGRESS_LANE}/{path.name}"
        lease = active_lease(plans_root, rel)
        owner = lease.agent_id if lease else None
        if only_mine:
            if not agent_id or owner != agent_id:
                continue
        records.append(
            _record_from_path(
                path, IN_PROGRESS_LANE, w, owner=owner, plans_root=plans_root
            )
        )
    return records


def inventory(
    plans_root: Path,
    worker: Worker | None = None,
    *,
    agent_id: str | None = None,
    include_others_in_progress: bool = False,
) -> list[PlanRecord]:
    """Ready plans plus optional in-progress visibility.

    Default: ready only. Pass agent_id to also list **your** in-progress plans
    first (for resume). Other agents' in-progress files stay hidden unless
    include_others_in_progress=True (list/debug only — never pick them).
    """
    mine: list[PlanRecord] = []
    if agent_id:
        mine = inventory_in_progress(
            plans_root, worker, agent_id=agent_id, only_mine=True
        )
    others: list[PlanRecord] = []
    if include_others_in_progress:
        all_ip = inventory_in_progress(plans_root, worker, only_mine=False)
        mine_rels = {r.rel for r in mine}
        others = [r for r in all_ip if r.rel not in mine_rels]
    ready = inventory_ready(plans_root, worker)
    return mine + ready + others


# Back-compat alias used by older tests
def inventory_ready_alias(plans_root: Path, worker: Worker | None = None) -> list[PlanRecord]:
    return inventory_ready(plans_root, worker)


def assert_executable_path(
    path: Path,
    plans_root: Path | None = None,
    *,
    allow_in_progress: bool = True,
) -> Path:
    """Resolve path; raise ValueError if under drafts/ or completed/."""
    resolved = path.expanduser().resolve()
    parts = resolved.parts
    if ".plans" in parts:
        i = parts.index(".plans")
        if i + 1 < len(parts) and parts[i + 1] in BLOCKED_LANES:
            raise ValueError(
                f"refuses .plans/{parts[i + 1]}/ (not an executable lane): {path}"
            )
        if (
            i + 1 < len(parts)
            and parts[i + 1] == IN_PROGRESS_LANE
            and not allow_in_progress
        ):
            raise ValueError(
                f"refuses .plans/{IN_PROGRESS_LANE}/ without ownership check: {path}"
            )
    if plans_root is not None:
        try:
            rel = resolved.relative_to(plans_root.resolve())
        except ValueError:
            pass
        else:
            if rel.parts and rel.parts[0] in BLOCKED_LANES:
                raise ValueError(
                    f"refuses .plans/{rel.parts[0]}/ (not an executable lane): {path}"
                )
    return resolved


# Back-compat name
def assert_ready_path(path: Path, plans_root: Path | None = None) -> Path:
    return assert_executable_path(path, plans_root, allow_in_progress=True)


def resolve_target(
    plans_root: Path,
    *,
    slug: str | None = None,
    path: str | Path | None = None,
    agent_id: str | None = None,
) -> PlanRecord | None:
    """Resolve a named slug or path under ready lanes or own in-progress."""
    from plan_lease import active_lease

    w = Worker(name="unknown", tier="mid")

    if path is not None:
        p = Path(path)
        if not p.is_absolute():
            candidates = [
                Path.cwd() / p,
                plans_root.parent / p,
                plans_root / p,
            ]
            for c in candidates:
                if c.is_file():
                    p = c
                    break
        resolved = assert_executable_path(p, plans_root)
        if not resolved.is_file():
            raise FileNotFoundError(f"plan not found: {path}")
        try:
            rel = resolved.relative_to(plans_root.resolve())
            lane = rel.parts[0] if rel.parts else ""
        except ValueError:
            assert_executable_path(resolved)
            text = resolved.read_text(encoding="utf-8")
            return PlanRecord(
                path=resolved,
                rel=str(resolved),
                lane="features",
                slug=plan_slug(resolved),
                value=parse_value(text),
                priority=parse_priority(text),
                preferred=parse_preferred(text),
                title=parse_title(text, resolved.name),
            )
        rel_s = str(rel).replace("\\", "/")
        if lane == IN_PROGRESS_LANE:
            lease = active_lease(plans_root, rel_s)
            owner = lease.agent_id if lease else None
            if agent_id and owner and owner != agent_id:
                raise ValueError(
                    f"in-progress plan owned by {owner!r}; ignore unless you are that agent"
                )
            if agent_id and not owner:
                # orphan — allow named path for reclaim
                pass
            elif not agent_id and owner:
                raise ValueError(
                    f"in-progress plan owned by {owner!r}; pass agent_id to resume your own work"
                )
            return _record_from_path(
                resolved, lane, w, owner=owner, plans_root=plans_root
            )
        if lane not in READY_LANES:
            raise ValueError(
                f"plan not under ready lane bugs|features (or own in-progress/): {rel}"
            )
        return _record_from_path(resolved, lane, w, plans_root=plans_root)

    if slug is not None:
        matches: list[Path] = []
        # Prefer own in-progress match for resume
        if agent_id:
            for name in (f"{slug}.md", f"{slug}.local.md"):
                cand = plans_root / IN_PROGRESS_LANE / name
                if cand.is_file():
                    lease = active_lease(plans_root, f"{IN_PROGRESS_LANE}/{name}")
                    if lease and lease.agent_id == agent_id:
                        matches.append(cand)
        for lane in READY_LANES:
            for name in (f"{slug}.md", f"{slug}.local.md"):
                cand = plans_root / lane / name
                if cand.is_file():
                    matches.append(cand)
        if not matches:
            return None
        if len(matches) > 1:
            # Prefer in-progress own over ready if both somehow listed
            ip = [m for m in matches if m.parent.name == IN_PROGRESS_LANE]
            if len(ip) == 1 and agent_id:
                return resolve_target(plans_root, path=ip[0], agent_id=agent_id)
            raise ValueError(
                "ambiguous slug "
                f"{slug!r}: "
                + ", ".join(str(m.relative_to(plans_root)) for m in matches)
            )
        return resolve_target(plans_root, path=matches[0], agent_id=agent_id)

    return None


def select_one(
    plans_root: Path,
    worker: Worker,
    *,
    no_fit_check: bool = False,
    no_dep_check: bool = False,
    slug: str | None = None,
    path: str | Path | None = None,
    skip_rels: set[str] | None = None,
    agent_id: str | None = None,
) -> PlanRecord | None:
    """Pick one plan: resume own in-progress first, then ready by /work rules.

    Never returns another agent's in-progress plan.
    Skips plans with unmet Depends on unless no_dep_check (named targets still
    return the record so callers can surface unmet deps).
    """
    skip = skip_rels or set()

    if slug or path:
        rec = resolve_target(plans_root, slug=slug, path=path, agent_id=agent_id)
        if rec is None:
            return None
        fit = classify_fit(worker, rec.preferred)
        rec = PlanRecord(
            path=rec.path,
            rel=rec.rel,
            lane=rec.lane,
            slug=rec.slug,
            value=rec.value,
            priority=rec.priority,
            preferred=rec.preferred,
            title=rec.title,
            fit=fit,
            owner=rec.owner,
            depends_on=rec.depends_on,
            deps_met=rec.deps_met,
            deps_unmet=rec.deps_unmet,
            deps_notes=rec.deps_notes,
        )
        if rec.rel in skip:
            return None
        return rec

    # 1) Resume own in-progress (still respect unmet deps unless no_dep_check)
    if agent_id:
        for rec in inventory_in_progress(
            plans_root, worker, agent_id=agent_id, only_mine=True
        ):
            if not no_dep_check and not rec.deps_met:
                continue
            return rec

    # 2) Ready lanes
    for rec in inventory_ready(plans_root, worker):
        if rec.rel in skip:
            continue
        if not no_dep_check and not rec.deps_met:
            continue
        if no_fit_check:
            return rec
        if rec.fit in (Fit.GOOD, Fit.UNKNOWN):
            return rec
    return None


def format_list_table(records: list[PlanRecord]) -> str:
    if not records:
        return "(no ready plans under bugs/ or features/; no owned in-progress)"
    lines = ["path\tlane\tpriority\tvalue\tpreferred\tfit\tdeps\towner"]
    for r in records:
        pref = r.preferred or "(default mid)"
        owner = r.owner or "-"
        if not r.depends_on:
            deps = "none"
        elif r.deps_met:
            deps = "met:" + ",".join(r.depends_on)
        else:
            deps = "UNMET:" + ",".join(r.deps_unmet)
        lines.append(
            f"{r.rel}\t{r.lane}\t{r.priority}\t{r.value}\t{pref}"
            f"\t{r.fit.value}\t{deps}\t{owner}"
        )
    return "\n".join(lines)
