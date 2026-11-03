#!/usr/bin/env python3
"""Headless one-shot (optionally bounded-loop) consumer of the /work contract.

Pull-per-endpoint: each worker knows its own model/tier, picks one fit-appropriate
**ready** plan (bugs/features only), moves it to .plans/in-progress/ and writes a
lease atomically (the move IS the claim), then prints the path or hands off to
orchestrate.py --plan-file. Bare pick never scans in-progress — resuming your own
work is an explicit --slug/--path claim you own; a stalled foreign lease is taken
over only with --recover. Live workers extend their lease with --heartbeat. Other
agents ignore foreign in-progress plans. Not a daemon; not a central assigner.

**Never merges, never asks.** Interactive `/work` may land a finished branch on the
integration branch when the operator answers its end-of-run culmination question
(see `.claude/commands/work.md` §6). That path requires a human answer in-session,
so it does not exist here. A headless worker's finish is the **autonomous critic
loop** (work → review → review → PR): work → critic → (REVISE → work)* →
**ACCEPT** (critic ACCEPT), then `in-progress/` → `completed/` **on
``feature/<slug>``**, push, and open a PR targeting integration.
Do not add a flag that stands in for a merge answer — an unattended merge is
exactly what the gate is designed to prevent. Do not open a PR or archive to
`completed/` on critic **REVISE**. `review-needed/` is not this worker's finish
lane.

Usage:
  python work_once.py --list
  python work_once.py --once --tier mid --agent-id worker-1
  python work_once.py --once --endpoint h100-executor --registry endpoints.yaml
  python work_once.py --max-plans 3 --tier small --print-only
  python work_once.py --slug fix-login --no-fit-check --run

A worker bound to a **local** endpoint also honors the site inference-load policy
(``inference_load.py``): when the published level bars this worker's tier, the run
refuses **before** claiming and exits idle, so a capped site never leaves plans
parked under a lease nobody is running. Opt-in; unconfigured sites are unaffected.

Exit codes:
  0  listed or at least one plan picked/claimed (or --max-plans completed)
  1  nothing to do (empty backlog / no fit / load-capped / claim failures only)
  2  usage or hard error (missing tree, blocked path, etc.)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import plan_store
from inference_load import check_local_work, endpoint_is_local, load_config
from plan_lease import (
    DEFAULT_TTL_SECONDS,
    ClaimError,
    active_lease,
    claim_and_move,
    claimed_rels,
    finish_to_review,
    park,
    release,
    renew,
    return_to_ready,
)
from plan_parse import TriageAction, triage_plan
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


def _load_endpoint(
    registry: Path | None,
    name: str,
    overlay_root: Path | None = None,
) -> tuple[str, str, bool, str | None]:
    """Return (model_or_name, fit_tier, is_local, effort) from endpoints.yaml."""
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None

    path = registry or Path(__file__).resolve().parent / "endpoints.yaml"
    if not path.is_file():
        raise SystemExit(f"registry not found: {path}")

    try:
        from anchor_client import Fleet, RegistryConflict
        fleet = Fleet(
            path,
            overlay_root=overlay_root or Path.cwd(),
            probe_health=False,
        )
        ep = fleet.lookup(name)
        fit = REGISTRY_TIER_TO_FIT.get(ep.tier, normalize_fit_tier(ep.tier))
        return ep.model or ep.name, fit, ep.is_local, ep.effort
    except LookupError:
        raise SystemExit(f"endpoint {name!r} not found in {path}") from None
    except RegistryConflict as exc:
        raise SystemExit(str(exc)) from None

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
        if ep.get("name") == name or name in (ep.get("aliases") or []):
            reg_tier = str(ep.get("tier") or "executor")
            fit = REGISTRY_TIER_TO_FIT.get(reg_tier, normalize_fit_tier(reg_tier))
            model = str(ep.get("model") or name)
            nick_effort = ep.get("effort")
            effort = str(nick_effort).strip().lower() if nick_effort not in (None, "") else None
            return model, fit, endpoint_is_local(ep), effort
    raise SystemExit(f"endpoint {name!r} not found in {path}")


def _crude_value(line: str) -> str:
    """Value half of a ``key: value`` line, minus any inline comment or quotes.

    YAML starts an inline comment at a ``#`` preceded by whitespace, so that is
    what we cut on — a ``#`` inside a URL or an unspaced token stays put. Getting
    this wrong is not cosmetic: an endpoint annotated ``local: true   # my rack``
    used to parse as the whole string, miss the truthy set, and read as *not*
    local, silently disabling the load governor for that endpoint.
    """
    value = line.split(":", 1)[1]
    for i, ch in enumerate(value):
        if ch == "#" and (i == 0 or value[i - 1] in " \t"):
            value = value[:i]
            break
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _parse_endpoints_crude(text: str) -> list[dict]:
    """Tiny YAML-ish scrape when PyYAML is unavailable."""
    endpoints: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- name:"):
            if current:
                endpoints.append(current)
            current = {"name": _crude_value(stripped)}
        elif current is not None and stripped.startswith("tier:"):
            current["tier"] = _crude_value(stripped)
        elif current is not None and stripped.startswith("model:"):
            current["model"] = _crude_value(stripped)
        elif current is not None and stripped.startswith("base_url:"):
            # Needed for locality: without it the load governor could not tell a
            # local box from a cloud tier when PyYAML is unavailable.
            current["base_url"] = _crude_value(stripped)
        elif current is not None and stripped.startswith("local:"):
            current["local"] = _crude_value(stripped)
    if current:
        endpoints.append(current)
    return endpoints


def resolve_worker(args: argparse.Namespace) -> Worker:
    from plan_select import worker_with_effort

    effort = getattr(args, "effort", None)
    if args.endpoint:
        root = getattr(args, "root", None)
        model, tier, is_local, nick_effort = _load_endpoint(
            Path(args.registry) if args.registry else None,
            args.endpoint,
            overlay_root=Path(root) if root else Path.cwd(),
        )
        args.endpoint_is_local = is_local
        name = args.model or model
        if args.tier:
            tier = normalize_fit_tier(args.tier)
        return worker_with_effort(name, tier, effort or nick_effort)
    # Lease / worktree ids are not product names — never feed --agent-id into
    # effective_fit_tier (``grok-effort-*`` would look like the Grok family).
    name = args.model or "work-once"
    tier = normalize_fit_tier(args.tier or "mid")
    return worker_with_effort(name, tier, effort)


def load_gate(root: Path, worker: Worker, args: argparse.Namespace) -> str | None:
    """Refusal reason when the site load policy bars this worker, else None.

    Only **local-bound** workers are gated: one resolved to a local endpoint, or
    one told it is local with ``--local-worker``. A worker driving a cloud tier
    is never blocked by a site power policy — that is the constraint the whole
    governor rests on.
    """
    if getattr(args, "ignore_load", False):
        return None
    is_local = bool(getattr(args, "local_worker", False)) or bool(
        getattr(args, "endpoint_is_local", False)
    )
    if not is_local:
        return None
    cfg = load_config(root)
    if not cfg.enabled:
        return None
    allowed, reason, _policy = check_local_work(worker.tier, root, cfg)
    return None if allowed else reason


def orchestrate_identity_args(args) -> list[str]:
    """Forward claim identity into ``orchestrate.py`` (``--endpoint`` / ``--registry``)."""
    extra: list[str] = []
    registry = getattr(args, "registry", None)
    if registry:
        extra.extend(["--registry", str(registry)])
    endpoint = getattr(args, "endpoint", None)
    if endpoint:
        extra.extend(["--endpoint", str(endpoint)])
    return extra


MAINLINE_BRANCHES = frozenset({"main", "master", "dev", "develop"})


def _git_branch(cwd: Path) -> str | None:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    name = (r.stdout or "").strip()
    return name or None


def orchestrate_worktree_args(
    root: Path | str,
    agent_id: str | None,
    slug: str | None,
) -> list[str]:
    """``--worktree`` for a feature tree; never main/master/dev/develop."""
    path: Path | None = None
    if agent_id:
        try:
            from worktree_for_agent import ensure_worktree

            rec = ensure_worktree(Path(root), agent_id, slug=slug)
            path = Path(rec.path)
        except Exception as exc:  # noqa: BLE001 — WorktreeError or missing git
            print(
                f"[work_once] worktree ensure skipped: {exc}",
                file=sys.stderr,
            )
            path = None
    if path is None:
        path = Path.cwd()
    branch = _git_branch(path)
    if branch in MAINLINE_BRANCHES:
        print(
            f"[work_once] refusing --worktree on integration/mainline "
            f"branch {branch!r} at {path}",
            file=sys.stderr,
        )
        return []
    return ["--worktree", str(path)]


def run_orchestrate(plan_path: Path, extra: list[str]) -> int:
    script = Path(__file__).resolve().parent / "orchestrate.py"
    cmd = [sys.executable, str(script), "--plan-file", str(plan_path), *extra]
    print(f"[work_once] running: {' '.join(cmd)}", file=sys.stderr)
    return subprocess.call(cmd)


def _in_progress_rel(
    plans_root: Path, root: Path, path: str | None, slug: str | None
) -> str | None:
    """Resolve --path/--slug to an ``in-progress/<name>`` rel, or None.

    Bypasses lease-ownership checks on purpose — used only by --recover, which
    then goes through claim_and_move(recover=True).
    """
    if path:
        p = Path(path)
        if not p.is_absolute():
            for c in (Path.cwd() / p, root / p, plans_root / p):
                if c.is_file():
                    p = c
                    break
        if not p.is_file():
            return None
        ref = plan_store.ref_for_path(plans_root, p)
        return ref.rel if ref is not None and ref.lane == "in-progress" else None
    if slug:
        hits = plan_store.lookup(plans_root, "in-progress", slug)
        if hits:
            return hits[0].rel
    return None


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


def cmd_triage(
    plans_root: Path,
    worker: Worker,
    agent_id: str,
    *,
    ignore_deps: bool = False,
) -> int:
    """Mechanical accept/skip/reject over ready + own in-progress plans.

    No LLM, no network, no claim/move/dispatch — purely a read of already-parsed
    ``PlanRecord``s through :func:`plan_parse.triage_plan`. Safe to run on every
    daemon/fleet-worker poll before anything that would cost tokens. Exit ``0``
    when at least one plan is a **take**, ``1`` otherwise (mirrors ``plan_fit.py``).
    """
    records = inventory(plans_root, worker, agent_id=agent_id)
    if not records:
        print("(no ready or own in-progress plans)")
        return 1
    any_take = False
    for rec in records:
        verdict = triage_plan(rec, worker, ignore_deps=ignore_deps, agent_id=agent_id)
        print(f"{verdict.action.value}: {rec.rel} — {verdict.reason}")
        if verdict.action is TriageAction.TAKE:
            any_take = True
    return 0 if any_take else 1


def pick_claim_one(
    plans_root: Path,
    worker: Worker,
    args: argparse.Namespace,
) -> Path | None:
    """Select one ready plan, move to in-progress/, claim lease. Returns path."""
    # Guard against racing a ready plan another worker is mid-claim on (a lease
    # exists transiently on the ready path before the move). In-progress is never
    # bare-picked, so no resume candidates to preserve here.
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
        if not rec.agent_assignable and not args.allow_assigned:
            print(
                f"[work_once] {rec.rel} is assigned to {rec.assignee or 'a human'} "
                f"— agents do not complete it (use --allow-assigned to force)",
                file=sys.stderr,
            )
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
        # Bare pick only yields ready-lane plans (in-progress is never scanned).
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
        "--triage",
        action="store_true",
        help="mechanical take/skip/reject over ready + own in-progress plans "
             "(no LLM, no network, no claim); exit 0 if anything is a take",
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
    ap.add_argument(
        "--watch",
        action="store_true",
        help="stay up: pull on .plans/ events (inotify) with a long poll heartbeat",
    )
    ap.add_argument(
        "--watch-debounce",
        type=float,
        default=None,
        metavar="SEC",
        help="coalesce filesystem bursts (default 0.4s)",
    )
    ap.add_argument(
        "--watch-heartbeat",
        type=float,
        default=None,
        metavar="SEC",
        help="poll fallback interval while --watch (default 300s)",
    )
    ap.add_argument(
        "--watch-cycles",
        type=int,
        default=None,
        metavar="N",
        help="stop after N wakeups (tests); omit to run until signal",
    )
    ap.add_argument("--no-fit-check", action="store_true",
                    help="ignore Preferred-models filter (still one plan per pick)")
    ap.add_argument(
        "--no-dep-check",
        action="store_true",
        help="allow pick/claim even when Depends on are unmet (still state them)",
    )
    ap.add_argument(
        "--allow-assigned",
        action="store_true",
        help="claim a named plan even if its Assignee is a human (default: refuse)",
    )
    ap.add_argument("--slug", help="named plan slug under ready lanes")
    ap.add_argument("--path", help="named plan path (refuses drafts/completed)")
    ap.add_argument(
        "--tier",
        help="worker fit tier: small|mid|reasoner|frontier (or registry tier name)",
    )
    ap.add_argument("--model", help="worker model name for Preferred-models name match")
    ap.add_argument(
        "--effort",
        help="reasoning effort; for Grok family sets effective fit tier "
             "(low→mid, medium/high→reasoner, xhigh→frontier; omit→mid)",
    )
    ap.add_argument(
        "--endpoint",
        help="resolve model+tier from endpoints.yaml by endpoint name",
    )
    ap.add_argument(
        "--local-worker",
        action="store_true",
        help=(
            "treat this worker as local inference even without --endpoint, so the "
            "site load policy (inference_load.py) can cap it"
        ),
    )
    ap.add_argument(
        "--ignore-load",
        action="store_true",
        help="bypass the site inference-load policy for this run (operator override)",
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
        "--no-finish",
        action="store_true",
        help="with --run, leave the plan in in-progress/ even when orchestrate exits 0",
    )
    ap.add_argument(
        "--release",
        metavar="PLAN_REL",
        help="release lease for plan rel (e.g. in-progress/foo.md) and exit",
    )
    ap.add_argument(
        "--heartbeat",
        metavar="PLAN_REL",
        help="extend your lease on an in-progress plan (e.g. in-progress/foo.md) and exit",
    )
    ap.add_argument(
        "--recover",
        action="store_true",
        help=(
            "take over an in-progress plan whose lease has expired past the long "
            "TTL (crashed agent); requires --path or --slug. Never reclaims an "
            "active foreign lease."
        ),
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

    if args.heartbeat:
        try:
            lease = renew(
                plans_root, args.heartbeat, args.agent_id, ttl_seconds=args.lease_ttl
            )
        except ClaimError as exc:
            print(f"[work_once] {exc}", file=sys.stderr)
            return 2
        print(
            f"[work_once] heartbeat {lease.plan_rel} as {lease.agent_id}; "
            f"expires_at={lease.expires_at}",
            file=sys.stderr,
        )
        print(lease.plan_rel)
        return 0

    if args.recover:
        if not args.path and not args.slug:
            print("[work_once] --recover requires --path or --slug", file=sys.stderr)
            return 2
        rel = _in_progress_rel(plans_root, root, args.path, args.slug)
        if rel is None:
            print(
                "[work_once] --recover needs an existing in-progress plan path/slug",
                file=sys.stderr,
            )
            return 1
        try:
            lease, dest = claim_and_move(
                plans_root,
                rel,
                args.agent_id,
                ttl_seconds=args.lease_ttl,
                recover=True,
            )
        except ClaimError as exc:
            print(f"[work_once] recover failed: {exc}", file=sys.stderr)
            return 2
        print(
            f"[work_once] recovered {lease.plan_rel} as {args.agent_id}",
            file=sys.stderr,
        )
        print(dest)
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
                    ref = plan_store.ref_for_path(plans_root, p)
                    if ref is None:
                        print(f"[work_once] path outside .plans/: {p}", file=sys.stderr)
                        return 2
                    rec_rel = ref.rel
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
                        hits = plan_store.lookup(plans_root, lane, args.slug)
                        if hits:
                            rec_rel = hits[0].rel
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

    if args.triage:
        return cmd_triage(
            plans_root, worker, args.agent_id, ignore_deps=args.no_dep_check
        )

    if args.watch:
        return _watch_loop(root, plans_root, worker, args)

    return _claim_loop(root, plans_root, worker, args)


def _one_claim(root: Path, plans_root: Path, worker, args) -> tuple[int, int]:
    """Run one pull. Returns (exit_code, picked_count). exit 1 = idle, 2 = hard."""
    refusal = load_gate(root, worker, args)
    if refusal is not None:
        print(f"[work_once] {refusal} — not claiming", file=sys.stderr)
        return 1, 0
    try:
        plan_path = pick_claim_one(plans_root, worker, args)
    except ValueError as exc:
        print(f"[work_once] {exc}", file=sys.stderr)
        return 2, 0
    except FileNotFoundError as exc:
        print(f"[work_once] {exc}", file=sys.stderr)
        return 2, 0
    if plan_path is None:
        return 1, 0
    print(plan_path)
    extra = list(args.orchestrate_args)
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
            if "--worktree" not in extra:
                extra = ["--worktree", str(rec.path), *extra]
        except WorktreeError as exc:
            print(f"[work_once] worktree ensure failed: {exc}", file=sys.stderr)
            return 2, 0
        except Exception as exc:  # noqa: BLE001
            print(f"[work_once] worktree ensure failed: {exc}", file=sys.stderr)
            return 2, 0
    if args.run:
        extra = orchestrate_identity_args(args) + extra
        code = run_orchestrate(plan_path, extra)
        if code != 0:
            print(
                f"[work_once] orchestrate exit {code}; lease left on plan "
                f"(release with --release or wait for TTL)",
                file=sys.stderr,
            )
            return code, 1
        if not args.no_finish:
            try:
                rel = str(plan_path.resolve().relative_to(plans_root.resolve()))
                dest = finish_to_review(plans_root, rel, args.agent_id)
                print(
                    f"[work_once] orchestrate exit 0 → {dest.relative_to(plans_root)}",
                    file=sys.stderr,
                )
            except ClaimError as exc:
                print(f"[work_once] auto-finish skipped: {exc}", file=sys.stderr)
    return 0, 1


def _claim_loop(root: Path, plans_root: Path, worker, args) -> int:
    max_n = args.max_plans
    if max_n is None:
        max_n = 1
    if max_n < 1:
        print("[work_once] --max-plans must be >= 1", file=sys.stderr)
        return 2
    if args.slug or args.path:
        max_n = 1
    picked = 0
    last_hard = 1
    for _ in range(max_n):
        code, n = _one_claim(root, plans_root, worker, args)
        if code == 2:
            return 2
        if n == 0:
            if picked == 0:
                print(
                    "[work_once] nothing to do "
                    "(empty ready lanes, no model-fit plan, or all claimed)",
                    file=sys.stderr,
                )
                return 1
            break
        picked += n
        last_hard = code
        if args.slug or args.path:
            break
        if args.once and args.max_plans is None:
            break
    return 0 if picked else last_hard


def _watch_loop(root: Path, plans_root: Path, worker, args) -> int:
    import plan_watch

    debounce = (
        plan_watch.DEFAULT_DEBOUNCE_S
        if args.watch_debounce is None
        else args.watch_debounce
    )
    heartbeat = (
        plan_watch.DEFAULT_HEARTBEAT_S
        if args.watch_heartbeat is None
        else args.watch_heartbeat
    )
    watch = plan_watch.open_watch(plans_root)
    print(
        f"[work_once] watching {plans_root} debounce={debounce}s heartbeat={heartbeat}s",
        file=sys.stderr,
    )
    picked = 0
    last = 1
    for reason in plan_watch.run_loop(
        watch,
        debounce_s=debounce,
        heartbeat_s=heartbeat,
        cycles=args.watch_cycles,
        on_event=lambda r: plan_watch.publish_mqtt_poke() if r == "inotify" else None,
    ):
        print(f"[work_once] wake ({reason})", file=sys.stderr)
        code, n = _one_claim(root, plans_root, worker, args)
        if code == 2:
            return 2
        picked += n
        last = code
        if n == 0:
            print("[work_once] idle after wake", file=sys.stderr)
    return 0 if picked else last


if __name__ == "__main__":
    sys.exit(main())
