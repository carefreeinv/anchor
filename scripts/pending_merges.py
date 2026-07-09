#!/usr/bin/env python3
"""Advise which finished work is committed but **not yet merged** into integration.

Completed plans move to ``.plans/completed/`` and their code lands on a
``feature/<slug>`` branch — but the branch still has to be merged into
``dev``/``develop`` (and eventually ``main``/``master``). It is easy to pile up
green feature branches that never land. This script surfaces them for a human or
a coordinator.

For each local branch it computes the commits it carries that its **merge target**
does not:

- ``feature/*`` (and any non-integration branch) → the integration branch
  (``dev``, else ``develop``, else ``main``, else ``master``)
- the integration branch itself → the mainline (``main``/``master``)

Branches with commits ahead of their target are *pending*. When a pending
``feature/<slug>`` branch matches a plan under ``.plans/completed/``, that is
flagged as **completed work awaiting merge**.

Usage:
  python pending_merges.py                 # human table (cwd repo)
  python pending_merges.py --root /srv/app --json
  python pending_merges.py --exit-code     # exit 1 if anything is pending (for CI/monitors)

Exit codes: 0 nothing pending (or advisory default), 1 pending found with
``--exit-code``, 2 not a git repo / git error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Integration candidates in priority order; a feature branch targets the first
# that exists, and an integration branch targets the first *mainline* below it.
INTEGRATION_ORDER = ("dev", "develop", "main", "master")
MAINLINE_ORDER = ("main", "master")


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class PendingBranch:
    branch: str
    target: str
    ahead: int
    plan_slug: str | None = None
    completed_plan: bool = False


def _git(root: Path, *args: str) -> str:
    try:
        p = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git {' '.join(args)} failed: {exc}") from exc
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def local_branches(root: Path) -> list[str]:
    out = _git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return [b.strip() for b in out.splitlines() if b.strip()]


def _first_existing(candidates: tuple[str, ...], branches: set[str]) -> str | None:
    for name in candidates:
        if name in branches:
            return name
    return None


def merge_target(branch: str, branches: set[str]) -> str | None:
    """The branch a given branch is expected to merge into (or None)."""
    if branch in MAINLINE_ORDER:
        return None  # mainlines are the end of the line
    if branch in INTEGRATION_ORDER:  # dev/develop → mainline
        return _first_existing(MAINLINE_ORDER, branches - {branch})
    integ = _first_existing(INTEGRATION_ORDER, branches)  # feature → integration
    return integ if integ and integ != branch else None


def ahead_count(root: Path, target: str, branch: str) -> int:
    out = _git(root, "rev-list", "--count", f"{target}..{branch}")
    return int(out.strip() or "0")


def _slug_from_branch(branch: str) -> str | None:
    m = re.match(r"(?:feature|fix|bugfix)/(.+)", branch)
    return m.group(1) if m else None


def completed_slugs(root: Path) -> set[str]:
    """Slugs of plans under .plans/completed/ (date prefix and .local stripped)."""
    comp = root / ".plans" / "completed"
    slugs: set[str] = set()
    if not comp.is_dir():
        return slugs
    for path in comp.glob("*.md"):
        if path.name == "README.md":
            continue
        stem = path.name[:-9] if path.name.endswith(".local.md") else path.name[:-3]
        stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)  # drop YYYY-MM-DD- prefix
        slugs.add(stem)
    return slugs


def find_pending(root: Path | str) -> list[PendingBranch]:
    root = Path(root)
    branches = local_branches(root)
    bset = set(branches)
    done = completed_slugs(root)
    pending: list[PendingBranch] = []
    for branch in branches:
        target = merge_target(branch, bset)
        if not target:
            continue
        ahead = ahead_count(root, target, branch)
        if ahead <= 0:
            continue
        slug = _slug_from_branch(branch)
        pending.append(
            PendingBranch(
                branch=branch,
                target=target,
                ahead=ahead,
                plan_slug=slug,
                completed_plan=bool(slug and slug in done),
            )
        )
    # Most-pending first, then completed-plan branches surfaced above bare ones.
    pending.sort(key=lambda p: (not p.completed_plan, -p.ahead, p.branch))
    return pending


def format_report(pending: list[PendingBranch]) -> str:
    if not pending:
        return "All local branches are merged into their integration target — nothing pending."
    lines = [
        f"{len(pending)} branch(es) with unmerged commits:",
        "",
        f"{'branch':<40} {'→ target':<12} {'ahead':>5}  note",
    ]
    for p in pending:
        note = ""
        if p.completed_plan:
            note = f"completed plan '{p.plan_slug}' awaiting merge"
        elif p.plan_slug:
            note = f"plan '{p.plan_slug}' (no completed record)"
        lines.append(f"{p.branch:<40} {'→ ' + p.target:<12} {p.ahead:>5}  {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Surface completed/committed work not yet merged into integration."
    )
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument(
        "--exit-code",
        action="store_true",
        help="exit 1 when anything is pending (for CI / monitors)",
    )
    args = ap.parse_args(argv)

    try:
        pending = find_pending(args.root)
    except GitError as exc:
        print(f"pending-merges: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([asdict(p) for p in pending], indent=2))
    else:
        print(format_report(pending))

    return 1 if (pending and args.exit_code) else 0


if __name__ == "__main__":
    sys.exit(main())
