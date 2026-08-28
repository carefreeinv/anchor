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

A task that outgrows one context window degrades into a planned continuation
rather than a truncated answer: near its declared ceiling the executor is told to
emit a structured handoff (`anchor/templates/handoff.md`, parsed by
`scripts/handoff.py`), and the orchestrator respawns a *fresh* context seeded with
it — up to `--max-respawns` (default 2), after which the task is reported back to
the planner as a decomposition error rather than respawned again.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from anchor_client import Endpoint, Fleet, has_required_footer, load_prompt
from fleet_metrics import (
    FIT_TIER_LADDER,
    load_outcomes,
    normalize_fit_tier,
    record_task_outcome,
    render_human_report,
    should_stop,
    task_id_for,
)
from handoff import (
    Handoff,
    HandoffError,
    accumulate,
    build_continuation,
    looks_like_handoff,
    parse_handoff,
)
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

BUDGET_CHARS_PER_TOKEN = 4  # matches prompt_tuner's conservative estimate

# Fraction of an endpoint's declared ceiling at which the executor is told to hand
# off rather than start work it cannot finish. Below 100% because a handoff must
# itself fit in the window that writes it.
HANDOFF_THRESHOLD = 0.8
# A task needing a fourth window is decomposed wrong, not merely large.
MAX_RESPAWNS = 2

# Fit-gate tokens (mythos-core rule 11). A rule-13 preflight block may precede them.
FIT_GATE_SCAN_LINES = 12
_FIT_GATE_PREFIXES = ("SUGGEST-ESCALATE", "SUGGEST-DOWNGRADE", "SUGGEST-REROUTE")


def fit_gate_line(out: str) -> str | None:
    """Return the first power/specialty fit-gate line, or None.

    Honors a bare first line *and* a token after mythos-core rule 13's six-item
    preflight. Only the first ``FIT_GATE_SCAN_LINES`` non-empty lines are
    inspected so later prose quoting the tokens cannot trip the gate.
    """
    seen = 0
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            continue
        seen += 1
        upper = line.upper()
        if any(upper.startswith(p) for p in _FIT_GATE_PREFIXES):
            return line
        if seen >= FIT_GATE_SCAN_LINES:
            break
    return None


def estimate_tokens(text: str) -> int:
    """Conservative token estimate for budget accounting.

    Provider-reported usage is preferable and is what the orchestrator would use
    where an endpoint exposes it, but ``Endpoint.chat`` returns completion text
    only — so accounting falls back to the same chars-per-token estimate the
    prompt tuner uses. It runs deliberately high rather than low: the cost of
    over-estimating is an early handoff, the cost of under-estimating is a
    truncated task.
    """
    return len(text) // BUDGET_CHARS_PER_TOKEN + 1


def budget_pressure(text: str, target: Endpoint) -> float | None:
    """Fraction of ``target``'s declared ceiling that ``text`` already consumes.

    ``None`` when the endpoint declares no ``max_context`` — pressure against an
    unknown ceiling is not a number, and inventing one would trigger handoffs on
    endpoints that never needed them.
    """
    ceiling = target.quirks.get("max_context")
    if not ceiling:
        return None
    try:
        ceiling = int(ceiling)
    except (TypeError, ValueError):
        return None  # an unparseable ceiling is not a number to divide by
    if ceiling <= 0:
        return None
    return estimate_tokens(text) / ceiling


def handoff_directive(pressure: float) -> str:
    """Instruction appended when a dispatch is close to its ceiling.

    The trigger is the orchestrator's token accounting, not the model's own sense
    of how much room it has left — mythos-core tells the executor to hand off near
    its budget, and this is the harness making that measurable rather than felt.
    """
    return (
        f"\n\nBUDGET NOTICE: this prompt already uses ~{pressure:.0%} of your serving "
        "context ceiling. If you cannot finish this task AND its verification within "
        "what remains, do NOT truncate, guess, or stop silently — emit a structured "
        "handoff instead, following anchor/templates/handoff.md exactly: "
        "## Done / ## Remaining / ## Decisions made / ## Files touched / ## Open concerns. "
        "Every ## Remaining item needs its own 'Verify by:' line, and its scope may only "
        "shrink. A handoff is a successful outcome here; a partial answer is not."
    )


def check_budget(text: str, target: Endpoint) -> tuple[bool, str]:
    """Refuse dispatch when `text` already exceeds `target`'s serving ceiling.

    Budget is advisory when the endpoint's max_context is unset (nothing to check
    against) — never invented. A violation is a decomposition error, not a retryable
    failure: the caller must reject, never silently truncate the prompt.
    """
    ceiling = target.quirks.get("max_context")
    if not ceiling:
        return True, ""
    tokens = estimate_tokens(text)
    if tokens > int(ceiling):
        return False, (
            f"BUDGET: task text (~{tokens} tokens) exceeds {target.name}'s max_context "
            f"({ceiling} tokens) — decomposed wrong, send back to the planner rather than truncate."
        )
    return True, ""

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


# --- harness-enforced stop condition (mythos-core rule 6, mirrored harness-side) --
# should_stop() reads the persistent outcome ledger rather than an in-memory attempt
# counter, so the backstop survives across separate orchestrate.py invocations —
# exactly the case a flailing model's own attempt-counting can't cover.


def endpoint_model_name(ep) -> str:
    """Same identity should_stop's (task, model) counting keys on — matches how
    _ledger_outcome already names an endpoint when writing a row."""
    return getattr(ep, "model", None) or getattr(ep, "name", "unknown")


def endpoint_fit_tier(ep) -> str:
    return normalize_fit_tier(getattr(ep, "tier", None) or "mid")


def available_fit_tiers(fleet) -> tuple[str, ...]:
    """This fleet's configured tiers, ascending. Falls back to the full ladder when
    ``fleet`` can't be introspected (e.g. a test double with no ``.endpoints``) —
    a conservative default that never claims exhaustion it can't actually see.
    """
    endpoints = getattr(fleet, "endpoints", None)
    if not endpoints:
        return FIT_TIER_LADDER
    present = {endpoint_fit_tier(ep) for ep in endpoints}
    return tuple(t for t in FIT_TIER_LADDER if t in present)


def pick_escalation_endpoint(fleet, fit_tier: str):
    """First endpoint at ``fit_tier``, or None if the fleet has none / can't be
    introspected. Bypasses the executor role's tier-preference list on purpose —
    escalation targets a specific rung, not "whatever the role prefers".
    """
    endpoints = getattr(fleet, "endpoints", None)
    if not endpoints:
        return None
    for ep in endpoints:
        if endpoint_fit_tier(ep) == fit_tier:
            return ep
    return None


def write_human_report(root: Path, *, task_id: str, task_slug: str | None, report: str) -> Path:
    """Persist a top-tier-exhaustion report to disk — "the orchestrator generates
    it even if the model never did" means a file a human can actually open, not
    just a string in an in-memory result dict."""
    out_dir = Path(root) / "var" / "human-reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    short = task_id.split(":")[-1]
    name = f"{task_slug}-{short}" if task_slug else short
    path = out_dir / f"{name}.md"
    path.write_text(report, encoding="utf-8")
    return path


def escalation_directive(decision) -> str:
    """Text appended to an escalated spec — both failures' evidence, per the plan's
    "attaching both failures' evidence to the escalated spec" constraint."""
    lines = "\n".join(
        f"- attempt at tier '{rec.tier}' (model `{rec.model}`): "
        f"verify_exit={rec.actual_verify_exit!r}, scope_verdict={rec.scope_verdict!r}"
        for rec in decision.evidence
    )
    return (
        f"\n\nESCALATION: {decision.reason}\n"
        "Prior failed attempts (from the outcome ledger):\n"
        f"{lines}\n"
        "You are being dispatched at a higher tier because the lower tier failed "
        "this task twice. Do not repeat the same approach without addressing why "
        "it failed."
    )


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


def _ledger_outcome(
    *,
    task: str,
    out: str | None,
    ep,
    verify_exit: int | None,
    scope_verdict: str | None,
    metrics_ledger: Path | None,
    task_slug: str | None,
    sink: dict | None = None,
) -> None:
    """Append claimed-vs-actual row; never raise into the orchestrator loop.

    When ``sink`` is given the row is *held* rather than written: the caller
    finishes it later via :func:`_flush_outcome`. The orchestrated path needs
    this because a task's role verdict is only known after ``execute_task``
    returns — writing at the verify step would score a role-violating run as an
    accurate claim.
    """
    if metrics_ledger is None:
        return
    fields = dict(
        output=out,
        verify_exit=verify_exit,
        model=getattr(ep, "model", None) or getattr(ep, "name", "unknown"),
        tier=getattr(ep, "tier", None) or "unknown",
        task=task,
        ledger_path=metrics_ledger,
        scope_verdict=scope_verdict,
        endpoint=getattr(ep, "name", None),
        task_slug=task_slug,
    )
    if sink is not None:
        sink.clear()
        sink.update(fields)
        return
    try:
        record_task_outcome(**fields)
    except OSError as exc:
        print(f"[metrics] failed to write outcome ledger: {exc}", file=sys.stderr)


def _flush_outcome(sink: dict, *, role_verdict: str | None) -> None:
    """Write a held outcome row, stamped with the role verdict main() computed."""
    if not sink:
        return  # nothing recorded (no ledger, or the task never reached a record point)
    try:
        record_task_outcome(role_verdict=role_verdict, **sink)
    except OSError as exc:
        print(f"[metrics] failed to write outcome ledger: {exc}", file=sys.stderr)
    finally:
        sink.clear()


def execute_task(task: str, plan: str, fleet: Fleet, verify_cmd: str | None,
                 hold_on_fail: bool, insist: bool = False,
                 scope: ScopeConfig | None = None,
                 metrics_ledger: Path | None = None,
                 task_slug: str | None = None,
                 outcome_sink: dict | None = None) -> dict:
    system = load_prompt("anchor/system-prompts/mythos-core.md")
    history: list[str] = []
    last_ep = None
    last_out: str | None = None
    recorded = False
    tid = task_id_for(task, slug=task_slug)
    fit_tiers = available_fit_tiers(fleet)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ep = fleet.pick("executor")
        last_ep = ep
        escalation_suffix = ""

        # Harness-enforced stop condition (mythos-core rule 6, mirrored harness-side):
        # a persistent ledger check, not an in-memory attempt count, so a resumed
        # invocation still refuses a third dispatch to a model that already failed
        # this task twice — the model's own attempt-counting is a backstop, not this.
        #
        # This re-checks should_stop after EVERY hop, not just once against the base
        # tier: fleet.pick("executor") always returns the same base-tier endpoint, so
        # checking only that endpoint would forget an escalated tier's own failures on
        # the next invocation and re-escalate the same one hop forever, never reaching
        # a tier that is itself exhausted. The ladder is strictly monotone
        # (target_tier is always one rung higher), so this always terminates.
        if metrics_ledger is not None:
            ledger_rows = load_outcomes(metrics_ledger)
            while True:
                decision = should_stop(tid, endpoint_model_name(ep), ledger_rows,
                                       tier=endpoint_fit_tier(ep), tier_ladder=fit_tiers)
                if decision.action == "continue":
                    break
                if decision.action == "human-report":
                    report = render_human_report(task, decision.evidence)
                    print(f"[stop] human-report: {decision.reason}", file=sys.stderr)
                    return {"task": task, "status": "human-report", "attempts": attempt,
                            "message": decision.reason, "report": report}
                escalated = pick_escalation_endpoint(fleet, decision.target_tier)
                if escalated is None:
                    print(f"[stop] escalate-tier to '{decision.target_tier}' requested but no "
                          "such endpoint is configured — reporting up instead", file=sys.stderr)
                    return {"task": task, "status": "escalate", "attempts": attempt,
                            "message": decision.reason, "target_tier": decision.target_tier}
                print(f"[stop] {decision.reason} -> {escalated.name} ({decision.target_tier})",
                      file=sys.stderr)
                ep = escalated
                last_ep = ep
                escalation_suffix = escalation_directive(decision)

        print(f"[exec {attempt}/{MAX_ATTEMPTS}] {ep.name}: {task[:70]}", file=sys.stderr)
        prompt = f"PLAN (context only):\n{plan}\n\nYOUR SINGLE TASK:\n{task}"
        if history:
            prompt += f"\n\nPREVIOUS ATTEMPT FAILED. Verbatim failure output:\n{history[-1]}"
        if escalation_suffix:
            prompt += escalation_suffix

        # Budget gate: refuse dispatch rather than truncate when the prompt already
        # exceeds this endpoint's serving ceiling — a decomposition error, not
        # something a retry fixes. The handoff directive is measured here too: it is
        # appended below, and sizing the check without it let a prompt that "fits"
        # dispatch over the ceiling this module promises never to exceed.
        pressure = budget_pressure(system + prompt, ep)
        directive = (handoff_directive(pressure)
                     if pressure is not None and pressure >= HANDOFF_THRESHOLD else "")
        ok, budget_msg = check_budget(system + prompt + directive, ep)
        if not ok:
            print(f"[budget] rejected: {budget_msg}", file=sys.stderr)
            return {"task": task, "status": "failed-budget", "attempts": attempt,
                    "message": budget_msg}

        # Approaching (but not over) the ceiling: instruct a handoff rather than
        # letting the executor discover mid-answer that it has no room left.
        if directive:
            print(f"[budget] {ep.name} at ~{pressure:.0%} of ceiling — handoff directive attached",
                  file=sys.stderr)
            prompt += directive

        out = ep.chat([{"role": "system", "content": system},
                       {"role": "user", "content": prompt}], max_tokens=8192)
        last_out = out

        # A handoff is a planned outcome, not a malformed result — check for it
        # before the footer gate, which a handoff deliberately does not satisfy.
        # A handoff that is not dispatchable (vague Remaining, no Verify by) gets
        # exactly one corrective retry via the normal attempt loop, then escalates.
        # A handoff has no '## Result' footer by design, so output carrying both is a
        # finished result that happens to quote the template (e.g. a task whose job is
        # to edit it) — not a handoff. Without this guard such a task burns every
        # window and escalates with its verify command never run.
        if looks_like_handoff(out) and not has_required_footer(out):
            try:
                parsed = parse_handoff(out)
            except HandoffError as exc:
                print(f"[handoff] rejected: {exc}", file=sys.stderr)
                history.append(str(exc))
                continue
            print(f"[handoff] {ep.name}: {len(parsed.done)} done, "
                  f"{len(parsed.remaining)} remaining", file=sys.stderr)
            return {"task": task, "status": "handoff", "attempts": attempt,
                    "handoff": parsed, "output": out}

        # Fit check (mythos-core rules 10–11): dual-axis, bidirectional — power
        # too-hard (ESCALATE), power too-easy (DOWNGRADE), or specialty (REROUTE).
        # Honor a bare first line *or* a token after rule 13's preflight instead
        # of burning attempts, unless the operator ran with --insist.
        _fit_line = fit_gate_line(out)
        if _fit_line:
            suggestion = _fit_line[:300]
            _fit_upper = _fit_line.upper()
            if _fit_upper.startswith("SUGGEST-DOWNGRADE"):
                kind = "downgrade"
            elif _fit_upper.startswith("SUGGEST-REROUTE"):
                kind = "re-route"
            else:
                kind = "escalation"
            if not insist:
                print(f"[fit] {ep.name} suggests {kind}: {suggestion}", file=sys.stderr)
                status = "hold" if hold_on_fail else "escalate"
                _ledger_outcome(
                    task=task, out=out, ep=ep, verify_exit=None,
                    scope_verdict=None, metrics_ledger=metrics_ledger, sink=outcome_sink,
                    task_slug=task_slug,
                )
                recorded = True
                return {"task": task, "status": status, "attempts": attempt,
                        "suggestion": suggestion, "history": history}
            history.append(
                f"Your previous output was a fit gate ({suggestion[:80]}…). "
                "The operator insists you proceed at this tier/profile: stay strictly "
                "in scope, mark shaky output (unverified), and do not SUGGEST-ESCALATE, "
                "SUGGEST-DOWNGRADE, or SUGGEST-REROUTE again."
            )
            continue

        if not has_required_footer(out):
            history.append("FORMAT: output missing required '## Result'/'## How to verify' footer")
            continue

        # Scope gate (mythos-core rule 7, machine-enforced): reject any change
        # outside the task spec's ## Files in scope BEFORE running tests. A scope
        # violation is not a retryable failure — widening scope is the planner's
        # call, so route it straight back rather than burning another attempt.
        scope_label: str | None = None
        if scope is not None:
            try:
                verdict = enforce_config(scope)
            except ScopeError as exc:
                print(f"[scope] could not check scope: {exc}", file=sys.stderr)
                status = "hold" if hold_on_fail else "escalate"
                history.append(f"SCOPE: could not determine worktree changes: {exc}")
                _ledger_outcome(
                    task=task, out=out, ep=ep, verify_exit=None,
                    scope_verdict="error", metrics_ledger=metrics_ledger, sink=outcome_sink,
                    task_slug=task_slug,
                )
                recorded = True
                return {"task": task, "status": status, "attempts": attempt,
                        "history": history}
            if not verdict.ok:
                print(f"[scope] rejected: {', '.join(verdict.offending)}", file=sys.stderr)
                _ledger_outcome(
                    task=task, out=out, ep=ep, verify_exit=None,
                    scope_verdict="fail", metrics_ledger=metrics_ledger, sink=outcome_sink,
                    task_slug=task_slug,
                )
                recorded = True
                return {"task": task, "status": "failed-scope", "attempts": attempt,
                        "offending": list(verdict.offending), "message": verdict.message,
                        "output": out}
            scope_label = "pass"

        if verify_cmd:
            ok, log = run_cmd(verify_cmd)
            if not ok:
                history.append(log)
                # Final attempt records the failed verify; intermediate retries
                # keep trying so we do not double-count one task as many outcomes.
                if attempt >= MAX_ATTEMPTS:
                    _ledger_outcome(
                        task=task, out=out, ep=ep, verify_exit=1,
                        scope_verdict=scope_label, metrics_ledger=metrics_ledger, sink=outcome_sink,
                        task_slug=task_slug,
                    )
                    recorded = True
                continue
            _ledger_outcome(
                task=task, out=out, ep=ep, verify_exit=0,
                scope_verdict=scope_label, metrics_ledger=metrics_ledger, sink=outcome_sink,
                task_slug=task_slug,
            )
            recorded = True
            return {"task": task, "status": "ok", "attempts": attempt, "output": out}

        # No verify command: still record claim vs unknown actual (exit None).
        _ledger_outcome(
            task=task, out=out, ep=ep, verify_exit=None,
            scope_verdict=scope_label, metrics_ledger=metrics_ledger, sink=outcome_sink,
            task_slug=task_slug,
        )
        recorded = True
        return {"task": task, "status": "ok", "attempts": attempt, "output": out}

    status = "hold" if hold_on_fail else "escalate"
    # Exhausted retries (format failures, etc.) — record once if not already.
    if not recorded and last_ep is not None:
        _ledger_outcome(
            task=task, out=last_out, ep=last_ep, verify_exit=None,
            scope_verdict=None, metrics_ledger=metrics_ledger, sink=outcome_sink,
            task_slug=task_slug,
        )
    return {"task": task, "status": status, "attempts": MAX_ATTEMPTS, "history": history}


def execute_with_continuations(task: str, plan: str, fleet: Fleet, verify_cmd: str | None,
                               hold_on_fail: bool, insist: bool = False,
                               scope: ScopeConfig | None = None,
                               metrics_ledger: Path | None = None,
                               task_slug: str | None = None,
                               outcome_sink: dict | None = None,
                               max_respawns: int = MAX_RESPAWNS,
                               events: list[dict] | None = None) -> dict:
    """Run one task, respawning fresh contexts from handoffs up to the cap.

    Each continuation is a *new* context seeded with the handoff — never a longer
    conversation, which is the failure this whole mechanism exists to avoid. The
    cap is the orchestrator's, not the model's: a task that hands off more times
    than ``max_respawns`` is reported as a decomposition error for the planner
    rather than respawned again.
    """
    spec = task
    in_scope = tuple(scope.in_scope) if scope is not None else ()
    history: Handoff | None = None
    windows: list[dict] = []

    def log(event: str, **details) -> None:
        if events is not None:
            log_event(events, event, **details)

    for window in range(max_respawns + 1):
        result = execute_task(
            spec, plan, fleet, verify_cmd, hold_on_fail, insist, scope,
            metrics_ledger=metrics_ledger, task_slug=task_slug,
            outcome_sink=outcome_sink,
        )
        if result["status"] != "handoff":
            if windows:
                result["windows"] = window + 1
                result["handoffs"] = windows
            return result

        history = accumulate(history, result["handoff"])
        windows.append({"window": window + 1,
                        "done": list(result["handoff"].done),
                        "remaining": [item.title for item in history.remaining]})
        log("handoff", window=window + 1, remaining=len(history.remaining))

        if window >= max_respawns:
            message = (
                f"HANDOFF CAP: task still incomplete after {window + 1} context windows "
                f"({max_respawns} respawns, the maximum). A task that cannot finish in "
                "this many windows is decomposed wrong — send it back to the planner to "
                "split rather than respawning a third continuation."
            )
            print(f"[handoff] {message}", file=sys.stderr)
            log("handoff-cap-reached", windows=window + 1)
            return {"task": task, "status": "hold" if hold_on_fail else "escalate",
                    "attempts": result["attempts"], "message": message,
                    "windows": window + 1, "handoffs": windows}

        try:
            spec = build_continuation(task, history, window=window + 2, in_scope=in_scope)
        except HandoffError as exc:
            # Scope widening smuggled into remaining work: the planner owns that
            # decision, so stop rather than dispatch a continuation that grew.
            print(f"[handoff] {exc}", file=sys.stderr)
            log("handoff-scope-refused", window=window + 1)
            return {"task": task, "status": "hold" if hold_on_fail else "escalate",
                    "attempts": result["attempts"], "message": str(exc),
                    "windows": window + 1, "handoffs": windows}

    raise AssertionError("unreachable: loop returns on every path")  # pragma: no cover


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
                    help="override workers' SUGGEST-ESCALATE / SUGGEST-DOWNGRADE / "
                         "SUGGEST-REROUTE fit checks and make them proceed")
    ap.add_argument("--scope-spec",
                    help="task-spec markdown with '## Files in scope'; changes outside it "
                         "are rejected before --verify runs")
    ap.add_argument("--worktree", default=".",
                    help="worktree root for scope checks (default: cwd)")
    ap.add_argument("--out", default="orchestration_run.json")
    ap.add_argument("--registry", default=None)
    ap.add_argument(
        "--metrics-ledger",
        default=None,
        help="JSONL path for claimed-vs-actual outcomes "
             "(default: <worktree>/var/fleet-metrics/outcomes.jsonl; "
             "pass empty string to disable)",
    )
    ap.add_argument(
        "--max-respawns", type=lambda v: max(0, int(v)), default=MAX_RESPAWNS,
        help=f"continuation windows allowed after a handoff (default: {MAX_RESPAWNS}; "
             "0 disables continuations and escalates on the first handoff)",
    )
    ap.add_argument(
        "--task-slug",
        default=None,
        help="optional slug prefix for outcome task_id (defaults from --plan-file stem)",
    )
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

    if args.metrics_ledger == "":
        metrics_ledger: Path | None = None
    elif args.metrics_ledger:
        metrics_ledger = Path(args.metrics_ledger)
    else:
        metrics_ledger = root / "var" / "fleet-metrics" / "outcomes.jsonl"

    task_slug = args.task_slug
    if task_slug is None and args.plan_file:
        stem = Path(args.plan_file).name
        if stem.endswith(".local.md"):
            task_slug = stem[: -len(".local.md")]
        elif stem.endswith(".md"):
            task_slug = stem[:-3]
        else:
            task_slug = Path(args.plan_file).stem

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
        # Hold the ledger row until the role verdict exists: a task can pass verify
        # and still have written outside its role's allowed paths, and a row written
        # at the verify step would score that run as an accurate claim.
        outcome_sink: dict = {}
        r = execute_with_continuations(
            t, plan, fleet, args.verify, args.hold_on_fail, args.insist, scope,
            metrics_ledger=metrics_ledger, task_slug=task_slug,
            outcome_sink=outcome_sink, max_respawns=args.max_respawns, events=events,
        )
        if r.get("status") == "human-report":
            report_path = write_human_report(
                root, task_id=task_id_for(t, slug=task_slug), task_slug=task_slug,
                report=r["report"],
            )
            r["report_path"] = str(report_path)
            log_event(events, "human-report", path=str(report_path))
        role_verdict = guard(EXECUTOR, before, spec_deny)
        if role_verdict is not None and not role_verdict.ok:
            r["status"] = "failed-role"
            r["role_offending"] = list(role_verdict.offending)
        _flush_outcome(
            outcome_sink,
            role_verdict=None if role_verdict is None else ("pass" if role_verdict.ok else "fail"),
        )
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
