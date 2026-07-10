#!/usr/bin/env python3
"""The orchestrator pattern as a runnable loop: plan → execute (fresh context per task) →
verify (tooling, not trust) → critic review. Frontier judgment twice, cheap tokens between.

Usage:
  python orchestrate.py --goal "Add CSV export to the report page" --verify "pytest -q"
  python orchestrate.py --plan-file .plans/features/foo.md --hold-on-fail  # detached/Space-1
  python orchestrate.py --plan-file .plans/bugs/fix-login.md --verify "pytest -q"

The plan is produced by the 'planner' role (point it at a frontier model, Nemotron
thinking-on, or a committed ready plan via --plan-file under .plans/bugs|features).
Paths under .plans/drafts/ or .plans/completed/ are rejected.

Roles are harness-enforced capability sets (scripts/roles.py), not prompt framing:
writes made during the planner phase may only touch .plans/**, executor writes may
never touch .plans/** or the task spec, and the critic phase may write nothing.
Role transitions are logged as explicit orchestrator events; a role violation is a
hard error — the run still emits its outputs (plan/review text and the run JSON),
then exits 4.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from anchor_client import Fleet, has_required_footer, load_prompt
from roles import CRITIC, EXECUTOR, PLANNER, RoleCapabilities, check_role_writes
from scope_gate import (
    ScopeConfig,
    ScopeError,
    enforce_config,
    parse_scope,
    worktree_changes,
)

MAX_ATTEMPTS = 2  # Anchor stop condition: two failures → escalate/hold, never a third.
ROLE_VIOLATION_EXIT = 4

# Never execute drafts/completed/ambiguous/blocked via --plan-file.
_BLOCKED_PLAN_LANES = frozenset({"drafts", "completed", "ambiguous", "blocked"})


def assert_plan_file_allowed(path: Path) -> None:
    """Refuse --plan-file under non-executable .plans/ lanes.

    Paths under bugs/, features/, or in-progress/ are allowed (in-progress is for
    the claiming agent; other workers should not pick foreign in-progress plans).
    """
    parts = path.resolve().parts
    if ".plans" not in parts:
        return
    i = parts.index(".plans")
    if i + 1 < len(parts) and parts[i + 1] in _BLOCKED_PLAN_LANES:
        lane = parts[i + 1]
        raise SystemExit(
            f"--plan-file refuses .plans/{lane}/ (not an executable lane). "
            f"Pick under bugs/, features/, or your own in-progress/ "
            f"(ambiguous/blocked are parked; promote drafts via /draft --promote <slug> only). "
            f"Got: {path}"
        )


def run_cmd(cmd: str) -> tuple[bool, str]:
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=1800)
    out = (p.stdout + p.stderr)[-4000:]
    return p.returncode == 0, out


def log_event(events: list[dict], event: str, **details) -> dict:
    """Role transitions and violations are explicit, logged orchestrator events."""
    rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **details}
    events.append(rec)
    tail = " ".join(f"{k}={v}" for k, v in details.items())
    print(f"[event] {event}{f' {tail}' if tail else ''}", file=sys.stderr)
    return rec


def snapshot_changes(root: Path | str) -> set[str] | None:
    """Worktree change set for phase attribution; None when not a git worktree."""
    try:
        return set(worktree_changes(root))
    except ScopeError:
        return None


def enforce_role_phase(caps: RoleCapabilities, root: Path | str,
                       before: set[str] | None, events: list[dict],
                       extra_deny: tuple[str, ...] = ()):
    """Check writes made during one phase against the role's capability map.

    Only paths that changed since ``before`` are attributed to the phase, so
    pre-existing worktree state is never blamed on a role. A violation is a
    hard error: logged as an event and printed; the caller decides run flow
    (the run continues to its outputs, then exits nonzero).
    """
    if before is None:
        return None
    after = snapshot_changes(root)
    if after is None:
        return None
    verdict = check_role_writes(caps, sorted(after - before), extra_deny=extra_deny)
    if not verdict.ok:
        log_event(events, "role-violation", role=caps.role,
                  offending=",".join(verdict.offending))
        print(f"HARD ERROR:\n{verdict.message}", file=sys.stderr)
    return verdict


def make_plan(goal: str, context: str, fleet: Fleet) -> str:
    ep = fleet.pick("planner")
    print(f"[plan] {ep.name}", file=sys.stderr)
    return ep.chat(
        [{"role": "system", "content": load_prompt("anchor/system-prompts/mythos-core.md")
          + "\nYour ONLY output is a plan following the template. Do not implement."},
         {"role": "user", "content": f"TEMPLATE:\n{load_prompt('anchor/templates/plan.md')}\n\n"
                                      f"GOAL: {goal}\n\nCONTEXT:\n{context}"}],
        thinking=True, max_tokens=8192)


def split_tasks(plan: str) -> list[str]:
    """Extract task rows from the plan's Steps table; fall back to numbered lines.

    Raises ValueError (rather than returning an empty list) so the caller's error
    message can say exactly what was expected and show what the planner actually
    produced — the planner is a model, and drifting off the expected plan.md
    format is a real, silent failure mode worth surfacing clearly.
    """
    rows = re.findall(r"^\|\s*\d+\s*\|(.+)$", plan, re.MULTILINE)
    if rows:
        return [r.strip(" |") for r in rows]
    numbered = re.findall(r"^\s*\d+\.\s+(.+)$", plan, re.MULTILINE)
    if numbered:
        return numbered
    if not plan.strip():
        raise ValueError("Plan text is empty — nothing to execute.")
    preview = plan.strip()[:300]
    raise ValueError(
        "No tasks found in plan: expected a Steps table (rows like '| 1 | ... |') "
        f"or a numbered list ('1. ...'). Got {len(plan)} chars starting with:\n{preview}"
    )


def execute_task(task: str, plan: str, fleet: Fleet, verify_cmd: str | None,
                 hold_on_fail: bool, insist: bool = False,
                 scope: ScopeConfig | None = None) -> dict:
    system = load_prompt("anchor/system-prompts/mythos-core.md")
    history: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ep = fleet.pick("executor")
        print(f"[exec {attempt}/{MAX_ATTEMPTS}] {ep.name}: {task[:70]}", file=sys.stderr)
        prompt = f"PLAN (context only):\n{plan}\n\nYOUR SINGLE TASK:\n{task}"
        if history:
            prompt += f"\n\nPREVIOUS ATTEMPT FAILED. Verbatim failure output:\n{history[-1]}"
        out = ep.chat([{"role": "system", "content": system},
                       {"role": "user", "content": prompt}], max_tokens=8192)

        # Fit check (mythos-core rule 11): a worker that judges the task a poor fit
        # for its tier says so up front — honor it immediately instead of burning
        # attempts, unless the operator ran with --insist.
        if out.lstrip().upper().startswith("SUGGEST-ESCALATE"):
            suggestion = out.strip().splitlines()[0][:300]
            if not insist:
                print(f"[fit] {ep.name} suggests escalation: {suggestion}", file=sys.stderr)
                status = "hold" if hold_on_fail else "escalate"
                return {"task": task, "status": status, "attempts": attempt,
                        "suggestion": suggestion, "history": history}
            history.append("Your previous output was SUGGEST-ESCALATE. The operator insists "
                           "you proceed at this tier: stay strictly in scope, mark shaky "
                           "output (unverified), and do not SUGGEST-ESCALATE again.")
            continue

        if not has_required_footer(out):
            history.append("FORMAT: output missing required '## Result'/'## How to verify' footer")
            continue

        # Scope gate (mythos-core rule 7, machine-enforced): reject any change
        # outside the task spec's ## Files in scope BEFORE running tests. A scope
        # violation is not a retryable failure — widening scope is the planner's
        # call, so route it straight back rather than burning another attempt.
        if scope is not None:
            try:
                verdict = enforce_config(scope)
            except ScopeError as exc:
                print(f"[scope] could not check scope: {exc}", file=sys.stderr)
                status = "hold" if hold_on_fail else "escalate"
                history.append(f"SCOPE: could not determine worktree changes: {exc}")
                return {"task": task, "status": status, "attempts": attempt,
                        "history": history}
            if not verdict.ok:
                print(f"[scope] rejected: {', '.join(verdict.offending)}", file=sys.stderr)
                return {"task": task, "status": "failed-scope", "attempts": attempt,
                        "offending": list(verdict.offending), "message": verdict.message,
                        "output": out}

        if verify_cmd:
            ok, log = run_cmd(verify_cmd)
            if not ok:
                history.append(log)
                continue
        return {"task": task, "status": "ok", "attempts": attempt, "output": out}

    status = "hold" if hold_on_fail else "escalate"
    return {"task": task, "status": status, "attempts": MAX_ATTEMPTS, "history": history}


def review(goal: str, plan: str, results: list[dict], fleet: Fleet) -> str:
    ep = fleet.pick("critic")
    print(f"[review] {ep.name}", file=sys.stderr)
    summary = "\n\n".join(f"### {r['task']}\nstatus={r['status']}\n{r.get('output', '')[:2000]}"
                          for r in results)
    return ep.chat(
        [{"role": "system", "content": load_prompt("anchor/system-prompts/mythos-core.md")
          + "\nYou are the critic. Review only; do not fix. Use the review template."},
         {"role": "user", "content": f"TEMPLATE:\n{load_prompt('anchor/templates/review.md')}\n\n"
                                      f"GOAL: {goal}\n\nPLAN:\n{plan}\n\nRESULTS:\n{summary}"}],
        thinking=True, max_tokens=8192)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--goal", help="what to accomplish")
    ap.add_argument("--context", default="", help="file with codebase/context notes")
    ap.add_argument(
        "--plan-file",
        help="skip planning; use this plan (ready path under .plans/bugs|features preferred)",
    )
    ap.add_argument("--verify", help="shell command that must pass after each task")
    ap.add_argument("--hold-on-fail", action="store_true",
                    help="detached mode: hold failed tasks for later instead of escalating")
    ap.add_argument("--insist", action="store_true",
                    help="override workers' SUGGEST-ESCALATE fit checks and make them proceed")
    ap.add_argument("--scope-spec",
                    help="task-spec markdown with '## Files in scope'; changes outside it "
                         "are rejected before --verify runs")
    ap.add_argument("--worktree", default=".",
                    help="worktree root for scope checks (default: cwd)")
    ap.add_argument("--out", default="orchestration_run.json")
    ap.add_argument("--registry", default=None)
    args = ap.parse_args()
    if not args.goal and not args.plan_file:
        ap.error("--goal or --plan-file required")

    fleet = Fleet(args.registry) if args.registry else Fleet()
    context = Path(args.context).read_text(encoding="utf-8") if args.context else ""
    root = Path(args.worktree)
    events: list[dict] = []
    violations: list[dict] = []

    def guard(caps, before, extra_deny=()):
        verdict = enforce_role_phase(caps, root, before, events, extra_deny)
        if verdict is not None and not verdict.ok:
            violations.append({"role": verdict.role,
                               "offending": list(verdict.offending),
                               "message": verdict.message})
        return verdict

    if args.plan_file:
        plan_path = Path(args.plan_file)
        assert_plan_file_allowed(plan_path)
        plan = plan_path.read_text(encoding="utf-8")
        log_event(events, "plan-loaded", plan_file=args.plan_file)
    else:
        log_event(events, "role-start", role="planner")
        before = snapshot_changes(root)
        plan = make_plan(args.goal, context, fleet)
        guard(PLANNER, before)
    log_event(events, "role-transition", role_from="planner", role_to="executor",
              note="plan approved; executors spawned")

    try:
        tasks = split_tasks(plan)
    except ValueError as exc:
        sys.exit(str(exc))

    scope = None
    spec_deny: tuple[str, ...] = ()
    if args.scope_spec:
        in_scope, allowed = parse_scope(Path(args.scope_spec).read_text(encoding="utf-8"))
        scope = ScopeConfig(root=root,
                            in_scope=tuple(in_scope), allowed_generated=tuple(allowed))
        try:  # an executor may never edit its own spec
            spec_deny = (str(Path(args.scope_spec).resolve()
                             .relative_to(root.resolve())).replace("\\", "/"),)
        except ValueError:
            spec_deny = ()  # spec lives outside the worktree — unreachable anyway

    results = []
    for t in tasks:
        before = snapshot_changes(root)
        r = execute_task(t, plan, fleet, args.verify, args.hold_on_fail, args.insist, scope)
        role_verdict = guard(EXECUTOR, before, spec_deny)
        if role_verdict is not None and not role_verdict.ok:
            r["status"] = "failed-role"
            r["role_offending"] = list(role_verdict.offending)
        results.append(r)

    log_event(events, "role-transition", role_from="executor", role_to="critic",
              note="execution finished; review starts")
    before = snapshot_changes(root)
    verdict = review(args.goal or "(plan file)", plan, results, fleet)
    guard(CRITIC, before)

    run = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "goal": args.goal, "plan": plan,
           "results": results, "review": verdict,
           "events": events, "role_violations": violations}
    Path(args.out).write_text(json.dumps(run, indent=2), encoding="utf-8")

    ok = sum(r["status"] == "ok" for r in results)
    print(f"\n{ok}/{len(results)} tasks ok → {args.out}\n\n{verdict}")
    if violations:
        print(f"\n{len(violations)} role violation(s) — see {args.out}", file=sys.stderr)
        sys.exit(ROLE_VIOLATION_EXIT)


if __name__ == "__main__":
    main()
