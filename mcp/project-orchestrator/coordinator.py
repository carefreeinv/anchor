#!/usr/bin/env python3
"""Project-bound plan coordinator (L0+L1 logic).

Imported by ``server.py`` and unit tests. Reuses ``plan_select`` / ``plan_lease``
via PYTHONPATH / Anchor ``scripts/`` — never copies selection algorithms.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

import plan_lease
import plan_select
from plan_lease import ClaimError
from plan_select import Worker, normalize_fit_tier, plan_slug

DEFAULT_STALE_HOURS = 48.0
CAP_L0 = "L0"
CAP_L1 = "L1"
DEFAULT_CAPS = (CAP_L0, CAP_L1)
LANES_READ = (
    "bugs",
    "features",
    "in-progress",
    "drafts",
    "completed",
    "ambiguous",
    "blocked",
)


class CoordinatorError(Exception):
    """User-facing tool failure (refused action, bad path, missing plan)."""


@dataclass
class CoordinatorConfig:
    project_root: Path
    agent_id: str = "mcp-agent"
    default_tier: str = "mid"
    worker_tiers: list[str] = field(default_factory=lambda: ["mid"])
    capabilities: list[str] = field(default_factory=lambda: list(DEFAULT_CAPS))
    stale_after_hours: float = DEFAULT_STALE_HOURS
    parked_stale_hours: float = DEFAULT_STALE_HOURS * 2

    @property
    def plans_root(self) -> Path:
        return self.project_root / ".plans"


def _parse_duration_hours(raw: Any, default: float) -> float:
    if raw is None:
        return default
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().lower()
    if not s:
        return default
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|d|day|days)?$", s)
    if not m:
        try:
            return float(s)
        except ValueError:
            return default
    n = float(m.group(1))
    unit = m.group(2) or "h"
    if unit.startswith("d"):
        return n * 24.0
    return n


def load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CoordinatorError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CoordinatorError(f"config root must be a mapping: {path}")
    return data


def find_config_file(start: Path) -> Path | None:
    """Walk upward for ``.anchor/mcp.yaml``."""
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for _ in range(32):
        candidate = cur / ".anchor" / "mcp.yaml"
        if candidate.is_file():
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def resolve_project_root(
    project: str | Path | None = None,
    *,
    cwd: Path | None = None,
) -> tuple[Path, Path | None]:
    """Return ``(project_root, config_path_or_none)``."""
    cwd = (cwd or Path.cwd()).resolve()
    if project:
        root = Path(project).expanduser().resolve()
        if not root.is_dir():
            raise CoordinatorError(f"--project is not a directory: {root}")
        cfg = root / ".anchor" / "mcp.yaml"
        return root, (cfg if cfg.is_file() else find_config_file(root))

    found = find_config_file(cwd)
    if found:
        data = load_yaml_config(found)
        pr = data.get("project_root", ".")
        root = (found.parent.parent / str(pr)).resolve()
        if not root.is_dir():
            raise CoordinatorError(f"config project_root is not a directory: {root}")
        return root, found

    # Fall back: cwd if it has .plans/
    if (cwd / ".plans").is_dir():
        return cwd, None
    raise CoordinatorError(
        "no --project and no .anchor/mcp.yaml found upward from cwd; "
        "pass --project /path/to/app"
    )


def build_config(
    project: str | Path | None = None,
    *,
    agent_id: str | None = None,
    tier: str | None = None,
    cwd: Path | None = None,
) -> CoordinatorConfig:
    root, cfg_path = resolve_project_root(project, cwd=cwd)
    data: dict[str, Any] = {}
    if cfg_path:
        data = load_yaml_config(cfg_path)

    aid = agent_id or str(data.get("agent_id") or "mcp-agent")
    def_tier = normalize_fit_tier(str(tier or data.get("default_tier") or "mid"))
    wt_raw = data.get("worker_tiers")
    if isinstance(wt_raw, list) and wt_raw:
        worker_tiers = [normalize_fit_tier(str(t)) for t in wt_raw]
    else:
        worker_tiers = [def_tier]

    caps_raw = data.get("capabilities")
    if isinstance(caps_raw, list) and caps_raw:
        caps = [str(c).upper() if str(c).upper().startswith("L") else str(c) for c in caps_raw]
        # normalize L0 / l0
        caps = [c if c.startswith("L") else c for c in caps]
        caps = [f"L{c[1:]}" if re.match(r"^[Ll]\d", c) else c for c in caps]
    else:
        caps = list(DEFAULT_CAPS)

    stale = _parse_duration_hours(data.get("stale_after"), DEFAULT_STALE_HOURS)
    parked = _parse_duration_hours(
        data.get("parked_stale_after"), max(stale * 2, DEFAULT_STALE_HOURS * 2)
    )

    return CoordinatorConfig(
        project_root=root,
        agent_id=aid,
        default_tier=def_tier,
        worker_tiers=worker_tiers,
        capabilities=caps,
        stale_after_hours=stale,
        parked_stale_hours=parked,
    )


def _real(path: Path) -> Path:
    return path.resolve()


def assert_under_project(cfg: CoordinatorConfig, path: Path) -> Path:
    """Resolve path and require it under project_root (no escape)."""
    root = _real(cfg.project_root)
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise CoordinatorError(f"cannot resolve path: {path}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CoordinatorError(
            f"path escapes project root ({root}): {path}"
        ) from exc
    return resolved


def plans_rel_under(cfg: CoordinatorConfig, rel: str) -> Path:
    """Resolve a path relative to .plans/ or project; must stay under project."""
    raw = rel.replace("\\", "/")
    # Absolute paths: check containment only (never strip leading /)
    p = Path(raw)
    if p.is_absolute():
        return assert_under_project(cfg, p)

    rel_n = raw.lstrip("./")
    if rel_n.startswith(".plans/"):
        candidate = cfg.project_root / rel_n
    elif any(rel_n.startswith(f"{lane}/") for lane in LANES_READ):
        candidate = cfg.plans_root / rel_n
    else:
        candidate = cfg.plans_root / rel_n
    return assert_under_project(cfg, candidate)


def require_cap(cfg: CoordinatorConfig, *need: str) -> None:
    have = {c.upper() for c in cfg.capabilities}
    for n in need:
        if n.upper() not in have and n.upper().replace("L0.5", "L0") not in have:
            # L0.5 tools allowed when L0 present
            if n.upper().startswith("L0") and "L0" in have:
                continue
            if n.upper() in {"L0.5", "L0_5"} and "L0" in have:
                continue
            raise CoordinatorError(
                f"capability {n} not enabled (have: {sorted(have)})"
            )


def _worker(cfg: CoordinatorConfig) -> Worker:
    return Worker(name=cfg.agent_id, tier=cfg.default_tier)


def _read_conventions(cfg: CoordinatorConfig) -> dict[str, Any]:
    for name in ("ANCHOR-CONVENTIONS.md", "CLAUDE.md", "AGENTS.md"):
        p = cfg.project_root / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            m = re.search(
                r"(?im)^\s*[-*]?\s*\**Preferred orchestrator\**:?\s*(.+)$",
                text,
            )
            orch = m.group(1).strip() if m else None
            return {
                "file": name,
                "preferred_orchestrator": orch,
                "excerpt": text[:2000],
            }
    return {"file": None, "preferred_orchestrator": None, "excerpt": None}


def project_info(cfg: CoordinatorConfig) -> dict[str, Any]:
    require_cap(cfg, CAP_L0)
    plans = cfg.plans_root
    conv = _read_conventions(cfg)
    stale = plans_stale_report(cfg)
    return {
        "project_root": str(cfg.project_root),
        "plans_root": str(plans),
        "plans_exists": plans.is_dir(),
        "agent_id": cfg.agent_id,
        "default_tier": cfg.default_tier,
        "worker_tiers": list(cfg.worker_tiers),
        "capabilities": list(cfg.capabilities),
        "stale_after_hours": cfg.stale_after_hours,
        "preferred_orchestrator": conv.get("preferred_orchestrator"),
        "conventions_file": conv.get("file"),
        "stale_warnings": stale.get("warnings", [])[:12],
    }


def _record_to_dict(r: plan_select.PlanRecord) -> dict[str, Any]:
    return {
        "rel": r.rel,
        "lane": r.lane,
        "slug": r.slug,
        "value": r.value,
        "preferred": r.preferred,
        "title": r.title,
        "fit": r.fit.value if hasattr(r.fit, "value") else str(r.fit),
        "owner": r.owner,
        "depends_on": list(r.depends_on),
        "deps_met": r.deps_met,
        "deps_unmet": list(r.deps_unmet),
    }


def plans_list(cfg: CoordinatorConfig, *, include_in_progress: bool = True) -> dict[str, Any]:
    require_cap(cfg, CAP_L0)
    if not cfg.plans_root.is_dir():
        return {"plans": [], "stale_warnings": [], "error": "no .plans/ directory"}
    w = _worker(cfg)
    ready = plan_select.inventory_ready(cfg.plans_root, w)
    records = [_record_to_dict(r) for r in ready]
    if include_in_progress:
        ip = plan_select.inventory_in_progress(
            cfg.plans_root, w, agent_id=cfg.agent_id, only_mine=False
        )
        for r in ip:
            d = _record_to_dict(r)
            d["mine"] = r.owner == cfg.agent_id if r.owner else False
            records.append(d)
    stale = plans_stale_report(cfg)
    return {
        "plans": records,
        "stale_warnings": stale.get("warnings", [])[:20],
        "agent_id": cfg.agent_id,
    }


def plan_read(cfg: CoordinatorConfig, plan_ref: str) -> dict[str, Any]:
    require_cap(cfg, CAP_L0)
    path = _resolve_plan_path(cfg, plan_ref)
    # Only under .plans/
    plans = _real(cfg.plans_root)
    try:
        path.relative_to(plans)
    except ValueError as exc:
        raise CoordinatorError("plan_read only allows paths under .plans/") from exc
    if not path.is_file():
        raise CoordinatorError(f"plan not found: {plan_ref}")
    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(plans)).replace("\\", "/")
    lane = rel.split("/", 1)[0] if "/" in rel else ""
    return {
        "rel": f".plans/{rel}" if not rel.startswith(".plans") else rel,
        "lane": lane,
        "slug": plan_slug(path),
        "path": str(path),
        "text": text,
        "depends_on": plan_select.parse_depends_on(text),
        "preferred": plan_select.parse_preferred(text),
        "value": plan_select.parse_value(text),
        "title": plan_select.parse_title(text, path.name),
    }


def _resolve_plan_path(cfg: CoordinatorConfig, plan_ref: str) -> Path:
    ref = plan_ref.replace("\\", "/").strip()
    if not ref:
        raise CoordinatorError("empty plan_ref")
    # Absolute path: containment check first
    if Path(ref).is_absolute():
        return plans_rel_under(cfg, ref)
    # slug only
    if "/" not in ref and not ref.endswith(".md"):
        hits = plan_select.find_slug_paths(cfg.plans_root, ref)
        if not hits:
            raise CoordinatorError(f"no plan with slug {ref!r}")
        if len(hits) > 1:
            locs = ", ".join(f"{lane}/{p.name}" for lane, p in hits)
            raise CoordinatorError(f"ambiguous slug {ref!r}: {locs}")
        return hits[0][1].resolve()
    # strip leading .plans/
    if ref.startswith(".plans/"):
        ref = ref[len(".plans/") :]
    return plans_rel_under(cfg, ref)


def plans_inventory_for_deps(cfg: CoordinatorConfig) -> dict[str, Any]:
    require_cap(cfg, CAP_L0)
    if not cfg.plans_root.is_dir():
        return {"summaries": []}
    return {"summaries": plan_select.inventory_all_plan_summaries(cfg.plans_root)}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if t not in _STOP}


_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "plan",
        "when",
        "done",
        "must",
        "only",
        "into",
        "under",
        "have",
        "will",
        "should",
        "via",
        "not",
        "any",
        "all",
        "use",
        "using",
        "also",
        "than",
        "then",
        "them",
        "they",
        "are",
        "was",
        "can",
        "may",
        "its",
        "per",
        "out",
        "add",
        "new",
    }
)


def plans_suggest_dependencies(
    cfg: CoordinatorConfig,
    goal_or_plan_text: str,
    *,
    exclude_slug: str | None = None,
) -> dict[str, Any]:
    """Heuristic-only dependency suggestions (no LLM, no file writes)."""
    require_cap(cfg, CAP_L0)
    text = goal_or_plan_text or ""
    # If looks like a slug, load plan body
    if text.strip() and "/" not in text and len(text.strip()) < 80 and not text.strip().startswith("#"):
        try:
            loaded = plan_read(cfg, text.strip())
            text = loaded.get("text") or text
            exclude_slug = exclude_slug or loaded.get("slug")
        except CoordinatorError:
            pass

    query_tokens = _tokens(text)
    existing_deps = set(plan_select.parse_depends_on(text))
    summaries = plan_select.inventory_all_plan_summaries(cfg.plans_root)
    candidates: list[dict[str, Any]] = []

    for s in summaries:
        slug = s["slug"]
        if exclude_slug and slug.lower() == exclude_slug.lower():
            continue
        if s["lane"] == "drafts" and slug.lower() == (exclude_slug or "").lower():
            continue
        blob = f"{s.get('title', '')} {s.get('goal', '')} {slug}"
        st = _tokens(blob)
        if not st:
            continue
        overlap = query_tokens & st
        # boost if slug mentioned in text
        mentioned = slug.lower() in text.lower().replace("_", "-")
        score = len(overlap) + (5 if mentioned else 0)
        if score < 2 and not mentioned:
            continue
        # Prefer hard deps that are still open
        open_lane = s["lane"] in plan_select.OPEN_LANES
        rationale_bits = []
        if mentioned:
            rationale_bits.append("slug mentioned in text")
        if overlap:
            sample = ", ".join(sorted(overlap)[:8])
            rationale_bits.append(f"token overlap: {sample}")
        if open_lane:
            rationale_bits.append(f"still open in {s['lane']}/")
        else:
            rationale_bits.append(f"lane={s['lane']} (may already be done)")
        if slug in existing_deps or slug.lower() in {d.lower() for d in existing_deps}:
            rationale_bits.append("already listed in Depends on")
        candidates.append(
            {
                "slug": slug,
                "lane": s["lane"],
                "rel": s["rel"],
                "title": s["title"],
                "score": score,
                "rationale": "; ".join(rationale_bits),
                "propose_depends_on": open_lane
                and s["lane"] not in ("completed", "drafts"),
            }
        )

    candidates.sort(key=lambda c: (-c["score"], c["slug"]))
    proposed = [
        c["slug"]
        for c in candidates
        if c.get("propose_depends_on") and c["score"] >= 3
    ][:8]
    return {
        "method": "heuristic_token_overlap",
        "note": "Propose only — apply Depends on in the plan file yourself; MCP does not write plans.",
        "candidates": candidates[:15],
        "suggested_depends_on": proposed or (["none"] if not candidates else proposed),
        "exclude_slug": exclude_slug,
    }


def _preferred_tiers(preferred: str | None) -> list[str]:
    tiers, _names = plan_select._parse_preferred_tokens(preferred)
    return tiers


def plans_stale_report(cfg: CoordinatorConfig) -> dict[str, Any]:
    require_cap(cfg, CAP_L0)
    warnings: list[dict[str, Any]] = []
    if not cfg.plans_root.is_dir():
        return {"warnings": [], "capacity": "unknown", "known_tiers": list(cfg.worker_tiers)}

    known = {normalize_fit_tier(t) for t in cfg.worker_tiers}
    capacity = "known" if known else "unknown"
    now = time.time()
    stale_sec = cfg.stale_after_hours * 3600.0
    parked_sec = cfg.parked_stale_hours * 3600.0

    for lane in ("bugs", "features"):
        lane_dir = cfg.plans_root / lane
        if not lane_dir.is_dir():
            continue
        for path in sorted(lane_dir.glob("*.md")):
            if path.name == "README.md":
                continue
            try:
                age_h = (now - path.stat().st_mtime) / 3600.0
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if age_h < cfg.stale_after_hours:
                continue
            preferred = plan_select.parse_preferred(text)
            pref_tiers = _preferred_tiers(preferred)
            deps = plan_select.parse_depends_on(text)
            met, unmet, _notes = plan_select.evaluate_dependencies(
                cfg.plans_root, deps, git_check=False
            )
            rel = f"{lane}/{path.name}"
            slug = plan_slug(path)
            if not met and unmet:
                warnings.append(
                    {
                        "code": "STALE-DEPS",
                        "cause": "unmet_deps",
                        "rel": rel,
                        "slug": slug,
                        "age_hours": round(age_h, 1),
                        "preferred": preferred,
                        "hint": f"Depends on unmet: {', '.join(unmet)} — not a capacity issue",
                    }
                )
                continue
            if pref_tiers and known and not any(t in known for t in pref_tiers):
                warnings.append(
                    {
                        "code": "STALE-TIER-GAP",
                        "cause": "tier_gap",
                        "rel": rel,
                        "slug": slug,
                        "age_hours": round(age_h, 1),
                        "preferred": preferred,
                        "preferred_tiers": pref_tiers,
                        "known_tiers": sorted(known),
                        "hint": (
                            f"prefers {pref_tiers}; known workers {sorted(known)} — "
                            "start a matching tier or lower Preferred models"
                        ),
                    }
                )
            elif not known:
                warnings.append(
                    {
                        "code": "STALE-UNCLAIMED",
                        "cause": "no_workers",
                        "rel": rel,
                        "slug": slug,
                        "age_hours": round(age_h, 1),
                        "preferred": preferred,
                        "capacity": "unknown",
                        "hint": "ready past threshold; declare worker_tiers in .anchor/mcp.yaml",
                    }
                )
            else:
                warnings.append(
                    {
                        "code": "STALE-UNCLAIMED",
                        "cause": "idle_capacity",
                        "rel": rel,
                        "slug": slug,
                        "age_hours": round(age_h, 1),
                        "preferred": preferred,
                        "hint": "capacity present but idle — check fleet_watch / human /work",
                    }
                )

    # Expired leases on in-progress
    ip = cfg.plans_root / "in-progress"
    if ip.is_dir():
        for path in sorted(ip.glob("*.md")):
            if path.name == "README.md":
                continue
            rel = f"in-progress/{path.name}"
            lease = plan_lease.read_lease(cfg.plans_root, rel)
            if lease and lease.expired:
                age_h = (now - path.stat().st_mtime) / 3600.0
                warnings.append(
                    {
                        "code": "STALE-LEASE",
                        "cause": "expired_lease",
                        "rel": rel,
                        "slug": plan_slug(path),
                        "age_hours": round(age_h, 1),
                        "owner": lease.agent_id,
                        "hint": "lease expired; claimer gone — release or resume",
                    }
                )
            elif lease is None:
                age_h = (now - path.stat().st_mtime) / 3600.0
                if age_h >= cfg.stale_after_hours:
                    warnings.append(
                        {
                            "code": "STALE-LEASE",
                            "cause": "expired_lease",
                            "rel": rel,
                            "slug": plan_slug(path),
                            "age_hours": round(age_h, 1),
                            "hint": "in-progress with no active lease — orphan claim",
                        }
                    )

    for lane in ("ambiguous", "blocked"):
        lane_dir = cfg.plans_root / lane
        if not lane_dir.is_dir():
            continue
        for path in sorted(lane_dir.glob("*.md")):
            if path.name == "README.md":
                continue
            try:
                age_h = (now - path.stat().st_mtime) / 3600.0
            except OSError:
                continue
            if age_h < cfg.parked_stale_hours:
                continue
            warnings.append(
                {
                    "code": "STALE-PARKED",
                    "cause": "parked",
                    "rel": f"{lane}/{path.name}",
                    "slug": plan_slug(path),
                    "age_hours": round(age_h, 1),
                    "hint": f"parked in {lane}/ too long — human unpark when ready",
                }
            )

    return {
        "warnings": warnings,
        "capacity": capacity,
        "known_tiers": sorted(known),
        "stale_after_hours": cfg.stale_after_hours,
    }


def plans_claim(
    cfg: CoordinatorConfig,
    plan_ref: str,
    *,
    allow_unmet_deps: bool = False,
    ttl_seconds: int = plan_lease.DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    require_cap(cfg, CAP_L1)
    path = _resolve_plan_path(cfg, plan_ref)
    plans = _real(cfg.plans_root)
    try:
        rel = str(path.relative_to(plans)).replace("\\", "/")
    except ValueError as exc:
        raise CoordinatorError("claim only under .plans/") from exc

    lane = rel.split("/", 1)[0]
    if lane in plan_select.NON_EXECUTABLE_LANES:
        raise CoordinatorError(
            f"refuse claim/execute for lane {lane}/ (drafts|completed|ambiguous|blocked)"
        )
    if lane == "in-progress":
        owner = plan_lease.owner_of(cfg.plans_root, rel)
        if owner and owner != cfg.agent_id:
            raise CoordinatorError(
                f"foreign in-progress owned by {owner!r} — ignore"
            )
    elif lane not in plan_select.READY_LANES:
        raise CoordinatorError(f"cannot claim from lane {lane}/")

    # Dep check on ready plans
    if lane in plan_select.READY_LANES and not allow_unmet_deps:
        text = path.read_text(encoding="utf-8")
        deps = plan_select.parse_depends_on(text)
        met, unmet, notes = plan_select.evaluate_dependencies(
            cfg.plans_root, deps, git_check=True
        )
        if not met:
            raise CoordinatorError(
                f"unmet Depends on: {', '.join(unmet)}. "
                f"Pass allow_unmet_deps=true to override. Notes: {'; '.join(notes)}"
            )

    try:
        lease, dest = plan_lease.claim_and_move(
            cfg.plans_root, rel, cfg.agent_id, ttl_seconds=ttl_seconds
        )
    except ClaimError as exc:
        raise CoordinatorError(str(exc)) from exc

    return {
        "ok": True,
        "plan_rel": lease.plan_rel,
        "path": str(dest),
        "agent_id": lease.agent_id,
        "expires_at": lease.expires_at,
        "origin_rel": lease.origin_rel,
    }


def plans_release(
    cfg: CoordinatorConfig,
    plan_ref: str,
    *,
    target_lane: str | None = None,
) -> dict[str, Any]:
    """Return in-progress plan to ready (or drop lease only if already ready)."""
    require_cap(cfg, CAP_L1)
    path = _resolve_plan_path(cfg, plan_ref)
    plans = _real(cfg.plans_root)
    rel = str(path.relative_to(plans)).replace("\\", "/")
    lane = rel.split("/", 1)[0]
    try:
        if lane == "in-progress":
            dest = plan_lease.return_to_ready(
                cfg.plans_root,
                rel,
                agent_id=cfg.agent_id,
                target_lane=target_lane,
            )
            return {"ok": True, "action": "return_to_ready", "path": str(dest)}
        # drop lease only
        dropped = plan_lease.release(
            cfg.plans_root, rel, agent_id=cfg.agent_id, force=False
        )
        return {"ok": True, "action": "release_lease", "dropped": dropped, "rel": rel}
    except ClaimError as exc:
        raise CoordinatorError(str(exc)) from exc


def plans_complete(cfg: CoordinatorConfig, plan_ref: str) -> dict[str, Any]:
    """Move-only complete: client asserts Done when; no verify gate."""
    require_cap(cfg, CAP_L1)
    path = _resolve_plan_path(cfg, plan_ref)
    plans = _real(cfg.plans_root)
    rel = str(path.relative_to(plans)).replace("\\", "/")
    lane = rel.split("/", 1)[0]

    if lane in ("drafts", "completed"):
        raise CoordinatorError(f"refuse complete from {lane}/")
    if lane != "in-progress":
        raise CoordinatorError(
            "plans_complete requires an in-progress plan (claim first); "
            f"got {lane}/"
        )

    try:
        plan_lease._assert_owner_if_in_progress(cfg.plans_root, rel, cfg.agent_id)
        plan_lease.release(cfg.plans_root, rel, force=True)
        dest_rel, dest_path = plan_lease._move_file(cfg.plans_root, rel, "completed")
    except ClaimError as exc:
        raise CoordinatorError(str(exc)) from exc

    return {
        "ok": True,
        "action": "move_only_complete",
        "plan_rel": dest_rel,
        "path": str(dest_path),
        "note": "Client asserted Done when; no verify ran inside MCP.",
    }


def conventions_get(cfg: CoordinatorConfig) -> dict[str, Any]:
    require_cap(cfg, CAP_L0)
    raw = _read_conventions(cfg)
    return {
        "found": bool(raw.get("file")),
        "file": raw.get("file"),
        "preferred_orchestrator": raw.get("preferred_orchestrator"),
        "excerpt": raw.get("excerpt"),
    }
