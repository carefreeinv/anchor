#!/usr/bin/env python3
"""Lightweight checks for a repo's .plans/ tree.

Exit 0 if OK, 1 if violations. No args: check ./.plans relative to CWD (or
pass a repo root).

Usage:
  python3 scripts/check_plans.py
  python3 scripts/check_plans.py /path/to/project
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

KNOWN_LANES = ("bugs", "features", "drafts", "completed")
REQUIRED_SECTIONS = ("## Goal", "## Steps", "## Done when")
STATUS_RE = re.compile(r"^\s*-\s*\*\*Status:\*\*\s*(\w+)", re.MULTILINE | re.IGNORECASE)
# Also accept bare "Status: ready" lines
STATUS_BARE_RE = re.compile(r"^\s*Status:\s*(\w+)", re.MULTILINE | re.IGNORECASE)


def _status(text: str) -> str | None:
    m = STATUS_RE.search(text) or STATUS_BARE_RE.search(text)
    return m.group(1).lower() if m else None


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
            problems.append(f"{rel}: not under a known lane (bugs|features|drafts|completed)")
            continue
        lane = parts[0]
        if lane not in KNOWN_LANES:
            problems.append(f"{rel}: unknown lane '{lane}'")
            continue

        text = path.read_text(encoding="utf-8")
        status = _status(text)

        if status == "draft" and lane != "drafts":
            problems.append(f"{rel}: Status draft but not under drafts/")
        if status in ("ready", "in_progress") and lane == "drafts":
            problems.append(
                f"{rel}: Status {status} under drafts/ "
                f"(promotion is human-only; keep Status: draft until human git mv)"
            )
        if status == "done" and lane != "completed":
            problems.append(f"{rel}: Status done but not under completed/ (warn)")
        if lane in ("bugs", "features"):
            for sec in REQUIRED_SECTIONS:
                if sec not in text:
                    problems.append(f"{rel}: ready-lane plan missing '{sec}'")

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
