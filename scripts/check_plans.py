#!/usr/bin/env python3
"""Lightweight checks for a repo's .plans/ tree.

Exit 0 if OK, 1 if violations. No args: check ./.plans relative to CWD (or
pass a repo root).

Path is authoritative: lane/lifecycle come only from the directory
(bugs|features|in-progress|ambiguous|blocked|drafts|completed). In-file
Lane:/Status: headers are obsolete and flagged.

Usage:
  python3 scripts/check_plans.py
  python3 scripts/check_plans.py /path/to/project
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

KNOWN_LANES = (
    "bugs",
    "features",
    "in-progress",
    "ambiguous",
    "blocked",
    "review-needed",
    "drafts",
    "completed",
)
REQUIRED_SECTIONS = ("## Goal", "## Steps", "## Done when")

# Obsolete in-file markers (path is authoritative)
LANE_HEADER_RE = re.compile(
    r"^\s*-\s*\*\*Lane:\*\*\s*.+$", re.MULTILINE | re.IGNORECASE
)
LANE_BARE_RE = re.compile(r"^\s*Lane:\s*\S+", re.MULTILINE | re.IGNORECASE)
STATUS_HEADER_RE = re.compile(
    r"^\s*-\s*\*\*Status:\*\*\s*.+$", re.MULTILINE | re.IGNORECASE
)
STATUS_BARE_RE = re.compile(r"^\s*Status:\s*\S+", re.MULTILINE | re.IGNORECASE)


def check_plans(root: Path) -> list[str]:
    plans = root / ".plans"
    problems: list[str] = []
    if not plans.is_dir():
        return [f"no .plans/ directory under {root}"]

    for path in sorted(plans.rglob("*.md")):
        rel = path.relative_to(plans)
        if path.name == "README.md" and rel.parts == ("README.md",):
            continue
        if path.name == ".gitkeep":
            continue
        parts = rel.parts
        if len(parts) < 2:
            problems.append(
                f"{rel}: not under a known lane "
                f"(bugs|features|in-progress|ambiguous|blocked|drafts|completed)"
            )
            continue
        lane = parts[0]
        if lane not in KNOWN_LANES:
            problems.append(f"{rel}: unknown lane '{lane}'")
            continue

        text = path.read_text(encoding="utf-8")

        if LANE_HEADER_RE.search(text) or LANE_BARE_RE.search(text):
            problems.append(
                f"{rel}: obsolete Lane: header — path is authoritative; remove the field"
            )
        if STATUS_HEADER_RE.search(text) or STATUS_BARE_RE.search(text):
            problems.append(
                f"{rel}: obsolete Status: header — path is authoritative; remove the field"
            )

        # Ready + in-progress should stay executable-complete; parked may be thin
        if lane in ("bugs", "features", "in-progress"):
            for sec in REQUIRED_SECTIONS:
                if sec not in text:
                    problems.append(f"{rel}: executable-lane plan missing '{sec}'")

    # no todo/ dual hierarchy
    if (plans / "todo").exists():
        problems.append(".plans/todo exists — migrate to bugs/ or features/; no todo/ lane")

    return problems


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    problems = check_plans(root)
    if problems:
        print("check_plans: FAIL")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("check_plans: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
