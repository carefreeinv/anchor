#!/usr/bin/env python3
"""Headless one-shot (optionally bounded-loop) consumer of the /work contract.

Pull-per-endpoint: each worker knows its own model/tier, picks one fit-appropriate
ready plan (or resumes its own in-progress work), moves it to .plans/in-progress/,
claims a lease, then either prints the path or hands off to orchestrate.py
--plan-file. Other agents ignore foreign in-progress plans. Not a daemon; not a
central assigner.

Usage:
  python work_once.py --list
  python work_once.py --once --tier mid --agent-id worker-1
  python work_once.py --once --endpoint h100-executor --registry endpoints.yaml
  python work_once.py --max-plans 3 --tier small --print-only
  python work_once.py --slug fix-login --no-fit-check --run

Exit codes:
  0  listed or at least one plan picked/claimed (or --max-plans completed)
  1  nothing to do (empty backlog / no fit / claim failures only)
  2  usage or hard error (missing tree, blocked path, etc.)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from plan_lease import (
    DEFAULT_TTL_SECONDS,
    ClaimError,
    active_lease,
    claim_and_move,
    claimed_rels,
    park,
    release,
    return_to_ready,
)
from plan_select import (
    REGISTRY_TIER_TO_FIT,
    Fit,
    Worker,
    format_list_table,
    inventory,
    inventory_in_progress,
    normalize_fit_tier,
    plan_slug,
    plans_root_for,
    select_one,
)


def _load_endpoint(registry: Path | None, name: str) -> tuple[str, str]:
    """Return (model_or_name, fit_tier) from endpoints.yaml."""
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None

    path = registry or Path(__file__).resolve().parent / "endpoints.yaml"
    if not path.is_file():
        raise SystemExit(f"registry not found: {path}")

    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
        endpoints = data.get("endpoints") or []
    else:
        # Minimal fallback without PyYAML: scan for name/tier lines (best-effort)
        endpoints = _parse_endpoints_crude(text)

    for ep in endpoints:
        if not isinstance(ep, dict):
            continue
        if ep.get("name") == name:
            reg_tier = str(ep.get("tier") or "executor")
            fit = REGISTRY_TIER_TO_FIT.get(reg_tier, normalize_fit_tier(reg_tier))
            model = str(ep.get("model") or name)
            return model, fit
    raise SystemExit(f"endpoint {name!r} not found in {path}")


def _parse_endpoints_crude(text: str) -> list[dict]:
    """Tiny YAML-ish scrape when PyYAML is unavailable."""
    endpoints: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            if current:
                endpoints.append(current)
            current = {"name": stripped.split(":", 1)[1].strip()}
        elif current is not None and stripped.startswith("tier:"):
            current["tier"] = stripped.split(":", 1)[1].strip()
        elif current is not None and stripped.startswith("model:"):
            current["model"] = stripped.split(":", 1)[1].strip()
    if current:
        endpoints.append(current)
    return endpoints


def resolve_worker(args: argparse.Namespace) -> Worker:
    if args.endpoint:
        model, tier = _load_endpoint(
            Path(args.registry) if args.registry else None, args.endpoint
        )
        name = args.model or model
        if args.tier:
            tier = normalize_fit_tier(args.tier)
        return Worker(name=name, tier=tier)
    name = args.model or args.agent_id or "work-once"
    tier = normalize_fit_tier(args.tier or "mid")
    return Worker(name=name, tier=tier)


def run_orchestrate(plan_path: Path, extra: list[str]) -> int:
    script = Path(__file__).resolve().parent / "orchestrate.py"
    cmd = [sys.executable, str(script), "--plan-file", str(plan_path), *extra]
    print(f"[work_once] running: {' '.join(cmd)}", file=sys.stderr)
    return subprocess.call(cmd)


def cmd_list(plans_root: Path, worker: Worker, agent_id: str) -> int:
    records = inventory(plans_root, worker, agent_id=agent_id)
    print(format_list_table(records))
    others = inventory_in_progress(plans_root, worker, only_mine=False)
    foreign = [r for r in others if r.owner and r.owner != agent_id]
    if foreign:
        print("\n# in-progress (other agents — ignore):", file=sys.stderr)
        for r in foreign:
            print(f"#   {r.rel}  agent={r.owner}", file=sys.stderr)
    claimed = claimed_rels(plans_root)
    if claimed:
        print("\n# active leases:", file=sys.stderr)
        for rel in sorted(claimed):
            lease = active_lease(plans_root, rel)
            who = lease.agent_id if lease else "?"
            print(f"#   {rel}  agent={who}", file=sys.stderr)
    return 0


def pick_claim_one(
    plans_root: Path,
    worker: Worker,
    args: argparse.Namespace,
) -> Path | None:
    """Select one plan, move to in-progress/, claim lease. Returns absolute path."""
    # Do not skip our own in-progress leases — those are resume candidates.
    skip = {r for r in claimed_rels(plans_root) if not r.startswith("in-progress/")}
    named = bool(args.slug or args.path)

    if named:
        try:
            rec = select_one(
                plans_root,
                worker,
                no_fit_check=args.no_fit_check,
                no_dep_check=args.no_dep_check,
                slug=args.slug,
                path=args.path,
                agent_id=args.agent_id,
            )
        except ValueError as exc:
            # Hard errors (blocked lane, foreign in-progress) — let main map to exit 2
            print(f"[work_once] {exc}", file=sys.stderr)
            raise
        if rec is None:
            print("[work_once] no matching plan for slug/path", file=sys.stderr)
            return None
        if not rec.deps_met and not args.no_dep_check:
            print(
                f"[work_once] unmet dependencies for {rec.rel}: "
                f"{', '.join(rec.deps_unmet)} — skip (use --no-dep-check to override)",
                file=sys.stderr,
            )
            for note in rec.deps_notes:
                print(f"[work_once]   dep: {note}", file=sys.stderr)
            return None
        if not args.no_fit_check and rec.fit not in (Fit.GOOD, Fit.UNKNOWN):
            print(
                f"[work_once] fit={rec.fit.value} for {rec.rel} "
                f"(preferred={rec.preferred!r}; worker={worker.name}/{worker.tier}) "
                f"— proceeding because target was named",
                file=sys.stderr,
            )
        elif rec.fit == Fit.UNKNOWN:
            print(
                f"[work_once] fit=unknown for {rec.rel} (no Preferred models or names-only miss)",
                file=sys.stderr,
            )
        try:
            lease, dest = claim_and_move(
                plans_root,
                rec.rel,
                args.agent_id,
                ttl_seconds=args.lease_ttl,
            )
        except ClaimError as exc:
            print(f"[work_once] claim failed: {exc}", file=sys.stderr)
            return None
        print(
            f"[work_once] claimed {lease.plan_rel} as {args.agent_id}"
            + (f" (from {lease.origin_rel})" if lease.origin_rel else ""),
            file=sys.stderr,
        )
        return dest

    skip_now = set(skip)
    for _ in range(32):
        rec = select_one(
            plans_root,
            worker,
            no_fit_check=args.no_fit_check,
            no_dep_check=args.no_dep_check,
            skip_rels=skip_now,
            agent_id=args.agent_id,
        )
        if rec is None:
            return None
        if not rec.deps_met and not args.no_dep_check:
            print(
                f"[work_once] skip {rec.rel}: unmet deps {', '.join(rec.deps_unmet)}",
                file=sys.stderr,
            )
            skip_now.add(rec.rel)
            continue
        # Already own in-progress — refresh claim without re-fitting
        if rec.lane == "in-progress":
            try:
                lease, dest = claim_and_move(
                    plans_root,
                    rec.rel,
                    args.agent_id,
                    ttl_seconds=args.lease_ttl,
                )
            except ClaimError as exc:
                print(f"[work_once] resume failed: {exc}", file=sys.stderr)
                skip_now.add(rec.rel)
                continue
            print(
                f"[work_once] resuming {lease.plan_rel} as {args.agent_id}",
                file=sys.stderr,
            )
            return dest
        if not args.no_fit_check and rec.fit not in (Fit.GOOD, Fit.UNKNOWN):
            skip_now.add(rec.rel)
            continue
        if rec.fit == Fit.UNKNOWN and not args.no_fit_check:
            print(
                f"[work_once] fit=unknown for {rec.rel}; taking as eligible",
                file=sys.stderr,
            )
        try:
            lease, dest = claim_and_move(
                plans_root,
                rec.rel,
                args.agent_id,
                ttl_seconds=args.lease_ttl,
            )
        except ClaimError:
            skip_now.add(rec.rel)
            continue
        print(
            f"[work_once] claimed {lease.plan_rel} fit={rec.fit.value} "
            f"as {args.agent_id} (from {lease.origin_rel}; "
            f"worker={worker.name}/{worker.tier})",
            file=sys.stderr,
        )
        return dest
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--root",
        default=".",
        help="project root containing .plans/ (default: cwd)",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="list ready plans with fit; do not claim or execute",
    )
    ap.add_argument(
        "--once",
        action="store_true",
        help="pick and claim exactly one plan (default if no --list/--max-plans)",
    )
    ap.add_argument(
        "--max-plans",
        type=int,
        default=None,
        metavar="N",
        help="bounded loop: claim up to N plans (still one-at-a-time); for cron",
    )
    ap.add_argument("--no-fit-check", action="store_true",
                    help="ignore Preferred-models filter (still one plan per pick)")
    ap.add_argument(
        "--no-dep-check",
        action="store_true",
        help="allow pick/claim even when Depends on are unmet (still state them)",
    )
    ap.add_argument("--slug", help="named plan slug under ready lanes")
    ap.add_argument("--path", help="named plan path (refuses drafts/completed)")
    ap.add_argument(
        "--tier",
        help="worker fit tier: small|mid|reasoner|frontier (or registry tier name)",
    )
    ap.add_argument("--model", help="worker model name for Preferred-models name match")
    ap.add_argument(
        "--endpoint",
        help="resolve model+tier from endpoints.yaml by endpoint name",
    )
    ap.add_argument("--registry", help="path to endpoints.yaml")
    ap.add_argument(
        "--agent-id",
        default=None,
        help="claim identity (default: work-once-$USER or work-once)",
    )
    ap.add_argument(
        "--lease-ttl",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help=f"lease TTL seconds (default {DEFAULT_TTL_SECONDS})",
    )
    ap.add_argument(
        "--print-only",
        action="store_true",
        default=True,
        help="print claimed plan path(s) to stdout (default)",
    )
    ap.add_argument(
        "--run",
        action="store_true",
        help="invoke orchestrate.py --plan-file on each claimed plan",
    )
    ap.add_argument(
        "--release",
        metavar="PLAN_REL",
        help="release lease for plan rel (e.g. in-progress/foo.md) and exit",
    )
    ap.add_argument(
        "--park",
        choices=("ambiguous", "blocked"),
        help="move PLAN into ambiguous/ or blocked/ (use with --path or --slug)",
    )
    ap.add_argument(
        "--return-ready",
        action="store_true",
        help="move plan back to bugs|features (with --path/--slug); drops lease",
    )
    ap.add_argument(
        "--target-lane",
        choices=("bugs", "features"),
        help="with --return-ready, destination ready lane (default: origin or features)",
    )
    ap.add_argument(
        "--ensure-worktree",
        action="store_true",
        help=(
            "after claim, ensure a per-agent git worktree (var/worktrees/<agent-id>/) "
            "and print WORKTREE=… lines; uses worktree_for_agent.py"
        ),
    )
    ap.add_argument(
        "orchestrate_args",
        nargs="*",
        help="extra args after -- forwarded to orchestrate when using --run",
    )
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    plans_root = plans_root_for(root)
    if not plans_root.is_dir():
        print(f"[work_once] no .plans/ under {root}", file=sys.stderr)
        return 2

    if args.agent_id is None:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "agent"
        args.agent_id = f"work-once-{user}"

    if args.release:
        try:
            ok = release(plans_root, args.release, agent_id=args.agent_id, force=True)
        except ClaimError as exc:
            print(f"[work_once] {exc}", file=sys.stderr)
            return 2
        print("released" if ok else "no lease", args.release)
        return 0

    if args.park or args.return_ready:
        if not args.path and not args.slug:
            print("[work_once] --park / --return-ready require --path or --slug", file=sys.stderr)
            return 2
        try:
            from plan_select import resolve_target

            # resolve under ready/in-progress; for park also allow resolving by path
            rec = None
            if args.path:
                p = Path(args.path)
                if not p.is_absolute():
                    for c in (Path.cwd() / p, root / p, plans_root / p):
                        if c.is_file():
                            p = c
                            break
                if p.is_file():
                    try:
                        rel = p.resolve().relative_to(plans_root.resolve())
                        rec_rel = str(rel).replace("\\", "/")
                    except ValueError:
                        print(f"[work_once] path outside .plans/: {p}", file=sys.stderr)
                        return 2
                else:
                    print(f"[work_once] plan not found: {args.path}", file=sys.stderr)
                    return 2
            else:
                rec = resolve_target(
                    plans_root, slug=args.slug, agent_id=args.agent_id
                )
                if rec is None:
                    # try in-progress by slug without ownership for error message
                    for lane in ("in-progress", "bugs", "features", "ambiguous", "blocked"):
                        for name in (f"{args.slug}.md", f"{args.slug}.local.md"):
                            cand = plans_root / lane / name
                            if cand.is_file():
                                rec_rel = f"{lane}/{name}"
                                break
                        else:
                            continue
                        break
                    else:
                        print(f"[work_once] no plan for slug {args.slug!r}", file=sys.stderr)
                        return 1
                else:
                    rec_rel = rec.rel

            if args.park:
                dest = park(
                    plans_root, rec_rel, args.park, agent_id=args.agent_id
                )
                print(dest)
                print(f"[work_once] parked → {args.park}/", file=sys.stderr)
                return 0
            dest = return_to_ready(
                plans_root,
                rec_rel,
                agent_id=args.agent_id,
                target_lane=args.target_lane,
            )
            print(dest)
            print("[work_once] returned to ready", file=sys.stderr)
            return 0
        except ClaimError as exc:
            print(f"[work_once] {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"[work_once] {exc}", file=sys.stderr)
            return 2

    try:
        worker = resolve_worker(args)
    except SystemExit as exc:
        if exc.code not in (0, None):
            return 2 if isinstance(exc.code, int) and exc.code != 1 else int(exc.code or 2)
        raise

    if args.list:
        return cmd_list(plans_root, worker, args.agent_id)

    max_n = args.max_plans
    if max_n is None:
        max_n = 1  # --once default
    if max_n < 1:
        print("[work_once] --max-plans must be >= 1", file=sys.stderr)
        return 2

    # Named slug with max>1 still only one plan
    if args.slug or args.path:
        max_n = 1

    picked = 0
    for i in range(max_n):
        try:
            plan_path = pick_claim_one(plans_root, worker, args)
        except ValueError as exc:
            print(f"[work_once] {exc}", file=sys.stderr)
            return 2
        except FileNotFoundError as exc:
            print(f"[work_once] {exc}", file=sys.stderr)
            return 2

        if plan_path is None:
            if picked == 0:
                print(
                    "[work_once] nothing to do "
                    "(empty ready lanes, no model-fit plan, or all claimed)",
                    file=sys.stderr,
                )
                return 1
            break

        picked += 1
        print(plan_path)
        if args.ensure_worktree:
            try:
                from worktree_for_agent import WorktreeError, ensure_worktree

                slug = plan_slug(plan_path)
                rec = ensure_worktree(root, args.agent_id, slug=slug)
                print(f"WORKTREE={rec.path}")
                print(f"BRANCH={rec.branch}")
                print(f"INTEGRATION={rec.integration}")
                print(
                    f"[work_once] worktree ready — run code edits in {rec.path}",
                    file=sys.stderr,
                )
            except WorktreeError as exc:
                print(f"[work_once] worktree ensure failed: {exc}", file=sys.stderr)
                return 2
            except Exception as exc:  # noqa: BLE001 — surface unexpected git issues
                print(f"[work_once] worktree ensure failed: {exc}", file=sys.stderr)
                return 2
        if args.run:
            code = run_orchestrate(plan_path, args.orchestrate_args)
            if code != 0:
                print(
                    f"[work_once] orchestrate exit {code}; lease left on plan "
                    f"(release with --release or wait for TTL)",
                    file=sys.stderr,
                )
                return code
        # After first named/once, stop unless looping
        if args.slug or args.path:
            break
        if args.once and args.max_plans is None:
            break

    return 0 if picked else 1


if __name__ == "__main__":
    sys.exit(main())
