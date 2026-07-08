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
