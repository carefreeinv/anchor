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

MAX_ATTEMPTS = 2  # Anchor stop condition: two failures → escalate/hold, never a third.

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
                 hold_on_fail: bool, insist: bool = False) -> dict:
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
    ap.add_argument("--out", default="orchestration_run.json")
    ap.add_argument("--registry", default=None)
    args = ap.parse_args()
    if not args.goal and not args.plan_file:
        ap.error("--goal or --plan-file required")

    fleet = Fleet(args.registry) if args.registry else Fleet()
    context = Path(args.context).read_text(encoding="utf-8") if args.context else ""
    if args.plan_file:
        plan_path = Path(args.plan_file)
        assert_plan_file_allowed(plan_path)
        plan = plan_path.read_text(encoding="utf-8")
    else:
        plan = make_plan(args.goal, context, fleet)

    try:
        tasks = split_tasks(plan)
    except ValueError as exc:
        sys.exit(str(exc))

    results = [execute_task(t, plan, fleet, args.verify, args.hold_on_fail, args.insist)
               for t in tasks]
    verdict = review(args.goal or "(plan file)", plan, results, fleet)

    run = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "goal": args.goal, "plan": plan,
           "results": results, "review": verdict}
    Path(args.out).write_text(json.dumps(run, indent=2), encoding="utf-8")

    ok = sum(r["status"] == "ok" for r in results)
    print(f"\n{ok}/{len(results)} tasks ok → {args.out}\n\n{verdict}")


if __name__ == "__main__":
    main()
