#!/usr/bin/env python3
"""Answer one question in one screen: **which ready plans should I take?**

Read-only triage for a worker that knows who it is. It never claims, moves, or
edits anything — pair it with ``plan_select.py --next --claim`` (or
``work_once.py``) once you have picked.

Why this exists: judging fit by reading plan headers is exactly the reasoning
step models get wrong in both directions — expensive sessions grabbing
boilerplate, and capable sessions refusing work that suits them because a
stronger model's name appears in ``Preferred models``. The rules are mechanical,
so a script should apply them.

    python scripts/plan_fit.py --tier mid --effort high
    take: features/foo — good (Preferred: mid) → effort high→low (overpaying)
    skip: features/bar — underqualified (Preferred: reasoner)
    1 eligible · 1 skipped

Identify yourself with **one** of ``--tier`` / ``--model`` / ``--endpoint``, and
optionally ``--effort`` for cost advice. Effort never changes eligibility — it
is a cost dial, not a tier promotion.

Exit codes: 0 something is eligible · 1 nothing eligible · 2 error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from plan_select import (
    EFFORT_LEVELS,
    EffortAdvice,
    Fit,
    PlanRecord,
    Worker,
    classify_effort,
    inventory_ready,
    normalize_effort,
    plan_effort_tier,
    plans_root_for,
)

# Fit values a bare pick may take. Mirrors work_once/select_one: `unknown` is
# eligible — an unmatched or absent Preferred list does not reserve a plan.
ELIGIBLE_FITS = (Fit.GOOD, Fit.UNKNOWN)


def _resolve_worker(args: argparse.Namespace) -> Worker:
    if args.endpoint:
        from work_once import _load_endpoint  # local: keeps YAML cost off the common path

        model, tier = _load_endpoint(
            Path(args.registry) if args.registry else None, args.endpoint
        )
        return Worker(name=args.model or model, tier=args.tier or tier)
    if not args.tier and not args.model:
        raise SystemExit(
            "say who you are: --tier small|mid|reasoner|frontier "
            "(and/or --model NAME, or --endpoint NAME from endpoints.yaml)"
        )
    return Worker(name=args.model or args.tier or "worker", tier=args.tier or "mid")


def _reason(rec: PlanRecord, worker: Worker) -> str:
    """Why this plan is skipped, in one clause."""
    if not rec.agent_assignable:
        # Assigned to a person: strongest reason, independent of fit/deps.
        return f"assigned to {rec.assignee or 'a human'} (agents don't complete this)"
    if not rec.deps_met:
        return "deps UNMET: " + ", ".join(rec.deps_unmet)
    pref = rec.preferred or "(none)"
    if rec.fit is Fit.UNDERQUALIFIED:
        return f"underqualified (Preferred: {pref}; you: {worker.tier})"
    if rec.fit is Fit.OVERQUALIFIED:
        return f"overqualified (Preferred: {pref}; you: {worker.tier})"
    return f"{rec.fit.value} (Preferred: {pref})"


def triage(
    records: list[PlanRecord],
    worker: Worker,
    effort: str | None,
    *,
    ignore_deps: bool = False,
) -> tuple[list[tuple[PlanRecord, EffortAdvice]], list[PlanRecord]]:
    """Split ready plans into (eligible + effort advice, skipped)."""
    take: list[tuple[PlanRecord, EffortAdvice]] = []
    skip: list[PlanRecord] = []
    for rec in records:
        blocked = (
            not rec.agent_assignable
            or rec.fit not in ELIGIBLE_FITS
            or (not rec.deps_met and not ignore_deps)
        )
        if blocked:
            skip.append(rec)
        else:
            take.append((rec, classify_effort(effort, rec.preferred)))
    return take, skip


def _line(rec: PlanRecord, advice: EffortAdvice | None, worker: Worker) -> str:
    if advice is None:
        return f"skip: {rec.rel} — {_reason(rec, worker)}"
    head = f"take: {rec.rel} — {rec.fit.value} (Preferred: {rec.preferred or '(none)'})"
    note = advice.note()
    return f"{head} → {note}" if note else head


def _as_json(
    take: list[tuple[PlanRecord, EffortAdvice]],
    skip: list[PlanRecord],
    worker: Worker,
    effort: str | None,
) -> str:
    return json.dumps(
        {
            "worker": {"name": worker.name, "tier": worker.tier,
                       "effort": normalize_effort(effort)},
            "eligible": [
                {
                    "rel": r.rel, "lane": r.lane, "slug": r.slug,
                    "priority": r.priority, "value": r.value,
                    "preferred": r.preferred, "fit": r.fit.value,
                    "effort": {
                        "verdict": a.verdict.value,
                        "suggested": a.suggested,
                        "band": list(a.band),
                        "should_change": a.should_change,
                    },
                }
                for r, a in take
            ],
            "skipped": [
                {
                    "rel": r.rel, "lane": r.lane, "slug": r.slug,
                    "preferred": r.preferred, "fit": r.fit.value,
                    "deps_met": r.deps_met, "deps_unmet": list(r.deps_unmet),
                    "assignee": r.assignee, "agent_assignable": r.agent_assignable,
                    "reason": _reason(r, worker),
                }
                for r in skip
            ],
            "next": take[0][0].rel if take else None,
        },
        indent=2,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="plan_fit.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", default=".", help="project root containing .plans/")
    ap.add_argument("--tier", help="your fit tier: small|mid|reasoner|frontier "
                                   "(registry tier names also accepted)")
    ap.add_argument("--model", help="your model name, for Preferred-models name matching")
    ap.add_argument("--endpoint", help="resolve model+tier from endpoints.yaml by name")
    ap.add_argument("--registry", help="path to endpoints.yaml (with --endpoint)")
    ap.add_argument("--effort", help="current reasoning effort: "
                                     f"{'|'.join(EFFORT_LEVELS)}")
    ap.add_argument("--eligible-only", action="store_true",
                    help="print only plans you should take (quiet skips)")
    ap.add_argument("--next", action="store_true",
                    help="print just the top eligible plan path, for scripting")
    ap.add_argument("--ignore-deps", action="store_true",
                    help="do not treat unmet Depends on as a skip")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    plans_root = plans_root_for(Path(args.root).resolve())
    if not plans_root.is_dir():
        print(f"error: no .plans/ under {args.root}", file=sys.stderr)
        return 2

    try:
        worker = _resolve_worker(args)
    except SystemExit as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.effort and normalize_effort(args.effort) is None:
        print(f"error: unknown effort {args.effort!r} "
              f"(use {'|'.join(EFFORT_LEVELS)})", file=sys.stderr)
        return 2

    records = inventory_ready(plans_root, worker)
    take, skip = triage(records, worker, args.effort, ignore_deps=args.ignore_deps)

    if args.next:
        if not take:
            return 1
        print(take[0][0].path)
        return 0

    if args.json:
        print(_as_json(take, skip, worker, args.effort))
        return 0 if take else 1

    if not records:
        print("(no ready plans under bugs/ or features/)")
        return 1

    for rec, advice in take:
        print(_line(rec, advice, worker))
    if not args.eligible_only:
        for rec in skip:
            print(_line(rec, None, worker))

    print(f"{len(take)} eligible · {len(skip)} skipped"
          f"  [you: {worker.name}/{worker.tier}"
          + (f", effort {normalize_effort(args.effort)}" if args.effort else "")
          + "]")
    if take:
        top = take[0][0]
        print(f"claim: python scripts/plan_select.py --next --claim --agent-id <id> "
              f"--tier {worker.tier} --root {args.root}   # → {top.rel}")
    elif skip:
        # Nothing for this worker: name the tier that would clear the top plan.
        top = skip[0]
        print(f"none for you — top pending {top.rel} wants "
              f"{top.preferred or plan_effort_tier(top.preferred)}")
    return 0 if take else 1


if __name__ == "__main__":
    sys.exit(main())
