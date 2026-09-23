#!/usr/bin/env python3
"""Select up to N ready plans that are unlikely to conflict, and prepare each
one (claim + dedicated worktree) for a **separate** parallel executor session.

This is a **selection + preparation** tool, not an agent-spawning runtime:
Anchor doesn't run its own agents. This script picks the batch, claims each
plan, and creates its worktree; an operator or an orchestrating harness (e.g.
its own subagent/Task mechanism) is what actually runs K parallel executor
sessions against the prepared batch.

## Conflict model

Each plan's ``## Likely touch points`` bullets are
parsed to a flat set of normalized paths, symbol suffix (``: func()``)
stripped — *which* symbol changed inside a shared file doesn't make two plans
safer to run in parallel; the file is the unit of conflict. Two plans
conflict if any pair of their touch points is identical, or one is a
directory-scoped entry that is an ancestor of the other. A plan with **zero**
parsed touch points is excluded from batch selection entirely (conservative
per C2 — it can still run through ordinary serial ``/work``).

    python scripts/batch_dispatch.py --tier mid --max 10
    python scripts/batch_dispatch.py --max 5 --claim --agent-prefix batch

Exit codes: 0 a batch (possibly smaller than --max, possibly empty) was
selected/printed · 2 error (no .plans/ etc.).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from plan_lease import ClaimError, claim_and_move
from plan_parse import safe_read_text, strip_code_fences
from plan_select import (
    Fit,
    PlanRecord,
    Worker,
    inventory_ready,
    plans_root_for,
    worker_with_effort,
)
from worktree_for_agent import WorktreeError, ensure_worktree

TOUCH_SECTION_RE = re.compile(
    r"^##\s+Likely touch points\s*$([\s\S]*?)(?=^##\s|\Z)",
    re.MULTILINE | re.IGNORECASE,
)
# One bullet = one line; backtick/note stripping happens in _normalize_path
# so this regex never has to look past its own line (a `\s*` spanning the
# newline between bullets would swallow the next bullet's leading `-`).
TOUCH_BULLET_RE = re.compile(r"^\s*-\s*(.+)$", re.MULTILINE)
NOT_APPLICABLE_RE = re.compile(r"^\s*not applicable\s*$", re.IGNORECASE)
# A backtick-quoted path, optionally followed by a ` — note` / `: note` /
# ` - note` trailing explanation on the same bullet line.
TOUCH_ENTRY_RE = re.compile(r"^`([^`]+)`(?:\s*[—:-]\s*.*)?$")


@dataclass(frozen=True)
class TouchPoint:
    path: str  # normalized POSIX-relative path, no trailing slash
    is_dir: bool


def _normalize_path(raw: str) -> str:
    line = raw.strip()
    m = TOUCH_ENTRY_RE.match(line)
    p = m.group(1).strip() if m else line.strip("`").strip()
    # A remaining `: symbol()` / `: ClassName` suffix (unquoted note, or the
    # backtick span itself included the symbol) still needs stripping — the
    # symbol never participates in overlap (see plan Step 1 design note).
    if ":" in p and not p.startswith("http"):
        p = p.split(":")[0].strip()
    p = p.replace("\\", "/")
    while p.endswith("/") and len(p) > 1:
        p = p[:-1]
    return p


def parse_touch_points(text: str, *, project_root: Path | None = None) -> list[TouchPoint]:
    """Parse a plan's ``## Likely touch points`` section into normalized entries.

    Returns ``[]`` for a missing section, an empty section, or a literal
    "not applicable" body (all three mean: no data to select against — the
    caller excludes the plan from batch selection, per C2).
    """
    m = TOUCH_SECTION_RE.search(text)
    if not m:
        return []
    body = m.group(1)
    raw_entries: list[str] = []
    for bm in TOUCH_BULLET_RE.finditer(body):
        candidate = bm.group(1).strip()
        if not candidate or NOT_APPLICABLE_RE.match(candidate):
            continue
        raw_entries.append(candidate)
    if not raw_entries:
        return []

    normalized = [_normalize_path(r) for r in raw_entries]
    normalized = [p for p in normalized if p]
    if not normalized:
        return []

    # A path is dir-scoped if it exists as a directory on disk, or if some
    # *other* entry in this same plan is nested under it (the planner named
    # the directory as a touch point even without a trailing slash).
    dir_flags: dict[str, bool] = {}
    for p in normalized:
        is_dir = False
        if project_root is not None:
            is_dir = (project_root / p).is_dir()
        if not is_dir:
            for other in normalized:
                if other != p and (other == p or other.startswith(p.rstrip("/") + "/")):
                    is_dir = True
                    break
        # A wildcard entry is conservatively directory-scoped, truncated at
        # the first wildcard segment (no glob in current backlog data; kept
        # simple rather than adding real glob matching for a case that
        # doesn't exist yet).
        if "*" in p:
            p = p.split("*", 1)[0].rstrip("/")
            is_dir = True
        dir_flags[p] = dir_flags.get(p, False) or is_dir

    return [TouchPoint(path=p, is_dir=is_dir) for p, is_dir in dir_flags.items()]


def touch_points_for_plan(path: Path, project_root: Path) -> list[TouchPoint]:
    raw_text, parse_error = safe_read_text(path)
    if parse_error is not None:
        return []
    text = strip_code_fences(raw_text)
    return parse_touch_points(text, project_root=project_root)


def _is_ancestor(dir_path: str, other: str) -> bool:
    """True if ``dir_path`` is ``other`` itself or a path-prefix directory of it."""
    if dir_path == other:
        return True
    return other.startswith(dir_path.rstrip("/") + "/")


def touch_points_overlap(a: list[TouchPoint], b: list[TouchPoint]) -> str | None:
    """Return a human-readable reason if ``a`` and ``b`` overlap, else None."""
    for pa in a:
        for pb in b:
            if pa.path == pb.path:
                return f"both touch `{pa.path}`"
            if pa.is_dir and _is_ancestor(pa.path, pb.path):
                return f"`{pb.path}` is under declared dir touch point `{pa.path}`"
            if pb.is_dir and _is_ancestor(pb.path, pa.path):
                return f"`{pa.path}` is under declared dir touch point `{pb.path}`"
    return None


@dataclass
class BatchCandidate:
    record: PlanRecord
    touch_points: list[TouchPoint]


@dataclass
class SelectionResult:
    selected: list[BatchCandidate]
    skipped_conflict: list[tuple[BatchCandidate, str]]  # (candidate, reason)
    excluded_no_touch_map: list[PlanRecord]


def select_batch(
    plans_root: Path,
    project_root: Path,
    worker: Worker,
    *,
    max_n: int = 10,
    no_fit_check: bool = False,
) -> SelectionResult:
    """Pick up to ``max_n`` mutually non-conflicting ready plans.

    Reuses ``plan_select.inventory_ready`` for the ready-plan pool and its
    Priority → Value → oldest-mtime ordering — this function adds the
    touch-point conflict filter, and (unless ``no_fit_check``) the same
    fit gate solo ``/work`` applies (C3): a plan whose fit for ``worker`` is
    not ``GOOD``/``UNKNOWN`` is excluded from the batch exactly as a solo
    session would skip it, mirroring ``plan_select.select_one``'s own gate.
    Greedy: walk the existing priority order, keep a plan iff it conflicts
    with none of the plans already selected.
    """
    records = inventory_ready(plans_root, worker)
    # inventory_ready already sorts by plan_sort_key; walk in that order.
    excluded_no_touch_map: list[PlanRecord] = []
    candidates: list[BatchCandidate] = []
    for rec in records:
        if not rec.deps_met:
            continue  # C3: unmet Depends on excluded same as solo /work
        if not rec.agent_assignable:
            continue  # C3: human-assigned plans excluded same as solo /work
        if not no_fit_check and rec.fit not in (Fit.GOOD, Fit.UNKNOWN):
            continue  # C3: poor fit excluded same as solo /work
        tps = touch_points_for_plan(rec.path, project_root)
        if not tps:
            excluded_no_touch_map.append(rec)
            continue
        candidates.append(BatchCandidate(record=rec, touch_points=tps))

    selected: list[BatchCandidate] = []
    skipped_conflict: list[tuple[BatchCandidate, str]] = []
    for cand in candidates:
        if len(selected) >= max_n:
            break
        conflict_reason = None
        for chosen in selected:
            reason = touch_points_overlap(cand.touch_points, chosen.touch_points)
            if reason:
                conflict_reason = f"conflicts with {chosen.record.rel} ({reason})"
                break
        if conflict_reason:
            skipped_conflict.append((cand, conflict_reason))
        else:
            selected.append(cand)

    return SelectionResult(
        selected=selected,
        skipped_conflict=skipped_conflict,
        excluded_no_touch_map=excluded_no_touch_map,
    )


@dataclass
class PrepResult:
    slug: str
    rel: str  # original ready-lane rel path, pre-claim
    agent_id: str
    ok: bool
    plan_path: str | None = None
    worktree_path: str | None = None
    branch: str | None = None
    error: str | None = None


def prepare_batch(
    project_root: Path,
    plans_root: Path,
    selection: list[BatchCandidate],
    *,
    agent_prefix: str = "batch",
) -> list[PrepResult]:
    """Claim + worktree each selected plan. Partial success is normal (C4):
    one plan's claim race is reported as a skip, not an abort of the rest."""
    results: list[PrepResult] = []
    for i, cand in enumerate(selection, start=1):
        rec = cand.record
        agent_id = f"{agent_prefix}-{i}-{rec.slug}"
        try:
            lease, dest = claim_and_move(plans_root, rec.rel, agent_id)
        except ClaimError as exc:
            results.append(
                PrepResult(slug=rec.slug, rel=rec.rel, agent_id=agent_id,
                           ok=False, error=f"claim failed: {exc}")
            )
            continue
        try:
            wt = ensure_worktree(project_root, agent_id, slug=rec.slug)
        except WorktreeError as exc:
            results.append(
                PrepResult(slug=rec.slug, rel=rec.rel, agent_id=agent_id,
                           ok=False, plan_path=str(dest),
                           error=f"worktree failed: {exc}")
            )
            continue
        results.append(
            PrepResult(
                slug=rec.slug, rel=rec.rel, agent_id=agent_id, ok=True,
                plan_path=str(dest), worktree_path=wt.path, branch=wt.branch,
            )
        )
    return results


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="batch_dispatch.py", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="project root containing .plans/")
    ap.add_argument("--max", type=int, default=10, help="batch size cap (default 10)")
    ap.add_argument("--tier", default="mid", help="worker base fit tier (default mid)")
    ap.add_argument("--model", help="worker model name for Preferred-models match")
    ap.add_argument("--effort", help="reasoning effort (Grok family sets effective tier)")
    ap.add_argument("--no-fit-check", action="store_true",
                     help="ignore Preferred-models filter when building the pool")
    ap.add_argument("--claim", action="store_true",
                     help="also claim + create a worktree for each selected plan")
    ap.add_argument("--agent-prefix", default="batch",
                     help="agent-id prefix used when --claim generates per-plan ids")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)

    project_root = Path(args.root).resolve()
    plans_root = plans_root_for(project_root)
    if not plans_root.is_dir():
        msg = f"no .plans/ under {args.root}"
        print(json.dumps({"ok": False, "error": msg}) if args.json else f"error: {msg}",
              file=sys.stderr)
        return 2

    worker = worker_with_effort(args.model or args.tier, args.tier, args.effort)

    result = select_batch(
        plans_root, project_root, worker,
        max_n=max(1, args.max), no_fit_check=args.no_fit_check,
    )

    prep: list[PrepResult] = []
    if args.claim:
        prep = prepare_batch(project_root, plans_root, result.selected,
                              agent_prefix=args.agent_prefix)

    if args.json:
        out = {
            "ok": True,
            "selected": [
                {"rel": c.record.rel, "slug": c.record.slug, "priority": c.record.priority,
                 "value": c.record.value,
                 "touch_points": [tp.path for tp in c.touch_points]}
                for c in result.selected
            ],
            "skipped_conflict": [
                {"rel": c.record.rel, "slug": c.record.slug, "reason": reason}
                for c, reason in result.skipped_conflict
            ],
            "excluded_no_touch_map": [r.rel for r in result.excluded_no_touch_map],
        }
        if args.claim:
            out["prepared"] = [
                {"slug": p.slug, "rel": p.rel, "agent_id": p.agent_id, "ok": p.ok,
                 "plan_path": p.plan_path, "worktree_path": p.worktree_path,
                 "branch": p.branch, "error": p.error}
                for p in prep
            ]
        print(json.dumps(out))
        return 0

    if not result.selected:
        print("no non-conflicting batch available (see skipped/excluded below)")
    for c in result.selected:
        print(f"select: {c.record.rel}  [{c.record.priority}/{c.record.value}]  "
              f"touches: {', '.join(tp.path for tp in c.touch_points)}")
    for c, reason in result.skipped_conflict:
        print(f"skip (conflict): {c.record.rel} — {reason}")
    for r in result.excluded_no_touch_map:
        print(f"exclude (no touch-map data): {r.rel} — run it through serial /work instead")
    print(f"batch size: {len(result.selected)} / max {args.max}")

    if args.claim:
        ok_n = sum(1 for p in prep if p.ok)
        for p in prep:
            if p.ok:
                print(f"prepared: {p.slug} → agent {p.agent_id} — worktree {p.worktree_path} "
                      f"(branch {p.branch}) — plan now at {p.plan_path}")
            else:
                print(f"prepare FAILED: {p.slug} → agent {p.agent_id} — {p.error}")
        print(f"prepared {ok_n}/{len(prep)} plans (partial success is normal, per C4)")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
