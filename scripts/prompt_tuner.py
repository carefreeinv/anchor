#!/usr/bin/env python3
"""Rewrite a sloppy task description into a full Anchor task spec, using a CHEAP model.

Playbook move #3: never send a sloppy prompt to an expensive (or weak) model.
Usage:
  python prompt_tuner.py "fix the login bug"                 # spec to stdout
  python prompt_tuner.py -f rough_notes.txt -o task.md
  echo "add dark mode" | python prompt_tuner.py -
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from anchor_client import Fleet, load_prompt

TUNER_SYSTEM = """You rewrite rough task descriptions into precise task specs. You do NOT solve the task.
Fill in the template exactly. Where the rough description lacks information, write
`TODO(owner): <the exact question to answer>` rather than inventing details.
A spec with honest TODOs is a success; a spec with plausible invented details is a failure.
Output ONLY the completed template, no commentary."""


def tune(rough: str, fleet: Fleet) -> str:
    template = load_prompt("anchor/templates/task-spec.md")
    ep = fleet.pick("tuner")
    spec = ep.chat(
        [{"role": "system", "content": TUNER_SYSTEM},
         {"role": "user", "content": f"TEMPLATE:\n{template}\n\nROUGH TASK:\n{rough}"}],
        temperature=0.3,
    )
    print(f"[tuner: {ep.name} ({ep.model})]", file=sys.stderr)
    return spec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("task", nargs="?", help="rough task text, or '-' for stdin")
    ap.add_argument("-f", "--file", help="read rough task from file")
    ap.add_argument("-o", "--out", help="write spec to file instead of stdout")
    ap.add_argument("--registry", default=None, help="endpoints.yaml path")
    args = ap.parse_args()

    if args.file:
        rough = Path(args.file).read_text(encoding="utf-8")
    elif args.task == "-" or args.task is None:
        rough = sys.stdin.read()
    else:
        rough = args.task
    if not rough.strip():
        ap.error("empty task description")

    fleet = Fleet(args.registry) if args.registry else Fleet()
    spec = tune(rough, fleet)
    if args.out:
        Path(args.out).write_text(spec, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(spec)


if __name__ == "__main__":
    main()
