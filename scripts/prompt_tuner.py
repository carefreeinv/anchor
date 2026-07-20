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
import re
import sys
from pathlib import Path

from anchor_client import Endpoint, Fleet, load_prompt

TUNER_SYSTEM = """You rewrite rough task descriptions into precise task specs. You do NOT solve the task.
Fill in the template exactly. Where the rough description lacks information, write
`TODO(owner): <the exact question to answer>` rather than inventing details.
A spec with honest TODOs is a success; a spec with plausible invented details is a failure.
Leave the ## Budget section's values exactly as given in the template — tooling fills
those in after you respond, not you.
Output ONLY the completed template, no commentary."""

BUDGET_MARGIN_TOKENS = 512  # headroom reserved out of the context window
CHARS_PER_TOKEN = 4  # conservative estimate; provider-reported usage wins where available

BUDGET_SECTION_RE = re.compile(
    r"^##\s+Budget\s*$([\s\S]*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE
)


def estimate_tokens(text: str) -> int:
    """Conservative chars/4 estimate — a stand-in when no tokenizer/provider usage is available."""
    return len(text) // CHARS_PER_TOKEN + 1


def find_endpoint(fleet: Fleet, name: str) -> Endpoint | None:
    return next((e for e in fleet.endpoints if e.name == name), None)


def render_budget(target: Endpoint | None, template: str, rough: str,
                  margin: int = BUDGET_MARGIN_TOKENS) -> tuple[str, str]:
    """Compute (context_window, output_ceiling) as strings, or ('unspecified', 'unspecified')
    when the target endpoint or its max_context is unknown. Numbers come from tooling — never
    the tuning model's own guess."""
    if target is None:
        return "unspecified", "unspecified"
    ceiling = target.quirks.get("max_context")
    if not ceiling:
        return "unspecified", "unspecified"
    context_window = int(ceiling)
    spent = estimate_tokens(template) + estimate_tokens(rough) + margin
    output_ceiling = max(context_window - spent, 0)
    return str(context_window), str(output_ceiling)


def inject_budget(spec: str, context_window: str, output_ceiling: str) -> str:
    """Overwrite the spec's ## Budget section with tooling-computed values, appending one if
    the tuning model dropped it."""
    block = (
        "## Budget\n"
        f"- Context window: {context_window}\n"
        f"- Output ceiling: {output_ceiling}\n"
        "- Spec + provided context exceeding this budget means the task is decomposed wrong "
        "— reject back to the planner, never truncate silently.\n"
    )
    if BUDGET_SECTION_RE.search(spec):
        return BUDGET_SECTION_RE.sub(block + "\n", spec, count=1)
    title, _, rest = spec.partition("\n")
    return f"{title}\n\n{block}\n{rest}"


def tune(rough: str, fleet: Fleet, target: str | None = None) -> str:
    template = load_prompt("anchor/templates/task-spec.md")
    ep = fleet.pick("tuner")
    spec = ep.chat(
        [{"role": "system", "content": TUNER_SYSTEM},
         {"role": "user", "content": f"TEMPLATE:\n{template}\n\nROUGH TASK:\n{rough}"}],
        temperature=0.3,
    )
    print(f"[tuner: {ep.name} ({ep.model})]", file=sys.stderr)
    target_ep = find_endpoint(fleet, target) if target else None
    context_window, output_ceiling = render_budget(target_ep, template, rough)
    return inject_budget(spec, context_window, output_ceiling)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("task", nargs="?", help="rough task text, or '-' for stdin")
    ap.add_argument("-f", "--file", help="read rough task from file")
    ap.add_argument("-o", "--out", help="write spec to file instead of stdout")
    ap.add_argument("--registry", default=None, help="endpoints.yaml path")
    ap.add_argument("--target", default=None,
                    help="registered endpoint name the spec will be dispatched to "
                         "(drives the ## Budget numbers; omit for 'unspecified')")
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
    spec = tune(rough, fleet, target=args.target)
    if args.out:
        Path(args.out).write_text(spec, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(spec)


if __name__ == "__main__":
    main()
