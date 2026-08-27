#!/usr/bin/env python3
"""Route a task to the right fleet tier — the 'which tasks deserve frontier pricing' rule as code.

Heuristic classification first (free), tiny-model classification as fallback.
Usage:
  python router.py "rename this variable across the file"      # prints role + endpoint
  python router.py --send "write a haiku about CI"             # actually dispatches
"""
from __future__ import annotations

import argparse
import re
import sys

from anchor_client import Fleet, load_prompt

RULES: list[tuple[str, str]] = [
    # (regex, role)  — first match wins; order = specificity
    (r"\b(architect|architecture|design decision|trade-?off|migration plan)\b", "planner"),
    (r"\b(review|critique|audit|check (this|the)|verify)\b", "critic"),
    (r"\b(race condition|deadlock|heisenbug|off.by.one|prove|algorithm choice)\b", "critic"),
    (r"\b(rename|typo|format|boilerplate|summari[sz]e|classify|extract|commit message)\b", "tuner"),
    (r".*", "executor"),
]

CLASSIFIER_SYSTEM = """Classify the task into exactly one of: planner, critic, executor, tuner.
planner = requires designing an approach across components. critic = requires judging existing work
or deep single-problem reasoning. tuner = trivial/mechanical text work. executor = everything else.
Reply with the single word only."""

SUMMARY_LINE_CAP = 100  # hard cap per plan constraint; generated, never hand-maintained

_CAPABILITY_BY_TIER = {
    "swarm": "tiny/fast",
    "executor": "mid executor",
    "executor-heavy": "heavier executor",
    "reasoner": "deep reasoning",
    "frontier": "frontier-class",
    "detached": "local/detached",
}


def _capability_phrase(quirks: dict, tier: str) -> str:
    """One short phrase describing what an endpoint is good for — derived only from
    fields already in the registry, never hand-maintained."""
    toggle = quirks.get("think_toggle")
    if toggle:
        return f"hybrid-reasoning ({toggle})"
    if quirks.get("reasoning_effort"):
        return "reasoning-effort dial"
    return _CAPABILITY_BY_TIER.get(tier, "standard chat")


def summarize_endpoints(fleet) -> list[str]:
    """One capped one-line summary per endpoint: name, tier, context size, one
    capability phrase. Never includes base_url, model, or any quirk value that could
    leak infrastructure/secrets — full detail is a deliberate, on-demand lookup
    (``endpoint_detail`` / the model-fleet MCP ``lookup_endpoint`` tool), not
    something every caller gets by default."""
    lines = []
    for ep in getattr(fleet, "endpoints", None) or []:
        ctx = ep.quirks.get("max_context")
        ctx_str = str(int(ctx)) if ctx else "unspecified"
        phrase = _capability_phrase(ep.quirks, ep.tier)
        line = f"{ep.name} · {ep.tier} · ctx={ctx_str} · {phrase}"
        if len(line) > SUMMARY_LINE_CAP:
            prefix = f"{ep.name} · {ep.tier} · ctx={ctx_str} · "
            room = SUMMARY_LINE_CAP - len(prefix) - 1
            phrase = (phrase[:room] + "…") if room > 0 else "…"
            line = prefix + phrase
        lines.append(line)
    return lines


def fleet_summary_block(fleet) -> str:
    """Header + summary lines, or '' when the fleet has no introspectable endpoints
    (e.g. a test double). Safe to splice into a prompt unconditionally."""
    lines = summarize_endpoints(fleet)
    if not lines:
        return ""
    return "FLEET SUMMARY (generated; full endpoint detail via model-fleet MCP lookup_endpoint):\n" + "\n".join(lines)


def endpoint_detail(fleet, name: str) -> str:
    """Full non-secret detail for one endpoint, resolved only on explicit request.
    Never includes an API key — those come from ``ANCHOR_API_KEY`` at request time,
    not the registry."""
    endpoints = getattr(fleet, "endpoints", None) or []
    ep = next((e for e in endpoints if e.name == name), None)
    if ep is None:
        known = ", ".join(e.name for e in endpoints) or "(none configured)"
        return f"No endpoint named {name!r}. Known: {known}"
    quirks = ", ".join(f"{k}={v}" for k, v in ep.quirks.items())
    detail = f"{ep.name} [{ep.tier}] {ep.model} @ {ep.base_url}"
    if quirks:
        detail += f"\nquirks: {quirks}"
    return detail


def route(task: str, fleet: Fleet, use_model: bool = False) -> str:
    for pattern, role in RULES:
        if re.search(pattern, task, re.IGNORECASE):
            if role != "executor" or not use_model:
                return role
            break
    if use_model:
        try:
            ep = fleet.pick("tuner")
            word = ep.chat([{"role": "system", "content": CLASSIFIER_SYSTEM},
                            {"role": "user", "content": task}], max_tokens=8).lower()
            if word in {"planner", "critic", "executor", "tuner"}:
                return word
        except Exception as e:  # classification is best-effort
            print(f"[router] model classify failed: {e}", file=sys.stderr)
    return "executor"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("task")
    ap.add_argument("--send", action="store_true", help="dispatch to the chosen endpoint")
    ap.add_argument("--model-classify", action="store_true", help="use tiny model when rules are unsure")
    ap.add_argument("--registry", default=None)
    args = ap.parse_args()

    fleet = Fleet(args.registry) if args.registry else Fleet()
    role = route(args.task, fleet, use_model=args.model_classify)
    ep = fleet.pick(role)
    print(f"role={role} endpoint={ep.name} model={ep.model} tier={ep.tier}", file=sys.stderr)

    if args.send:
        system = load_prompt("anchor/system-prompts/mythos-core.md")
        print(ep.chat([{"role": "system", "content": system},
                       {"role": "user", "content": args.task}],
                      thinking=(role in {"planner", "critic"})))


if __name__ == "__main__":
    main()
