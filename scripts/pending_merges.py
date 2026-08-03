#!/usr/bin/env python3
"""Advise which finished work is committed but **not yet merged** into integration.

The normal path is human **``/review``**: Approve merges ``feature/<slug>`` into
``dev``/``develop`` and archives the plan; an empty ``review-needed/`` queue can
**Promote** integration into ``main``/``master``. This script still surfaces
branches that were signed off without a merge, diverged, or never reviewed —
advisory only (it never merges).

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
    # Where the work physically is, and what state it is in. Unmerged work most
    # often stalls in a worktree nobody revisits, so "which branch is ahead" is
    # only half the answer — the other half is where to go look.
    worktree: str | None = None
    dirty: bool = False
    plan_lane: str | None = None
    held: bool = False
    stale_registry: bool = False


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


PLAN_LANES = (
    "bugs", "features", "in-progress", "review-needed",
    "completed", "drafts", "ambiguous", "blocked",
)


def branch_worktrees(root: Path) -> dict[str, str]:
    """``{branch: worktree path}`` from ``git worktree list --porcelain``."""
    out: dict[str, str] = {}
    try:
        text = _git(root, "worktree", "list", "--porcelain")
    except GitError:
        return out
    path = ""
    for line in text.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and path:
            out[line[len("branch "):].strip().removeprefix("refs/heads/")] = path
    return out


def registry_worktrees(root: Path) -> dict[str, str]:
    """``{branch: path}`` recorded in ``var/worktrees/registry.json`` (may be stale)."""
    reg = root / "var" / "worktrees" / "registry.json"
    if not reg.is_file():
        return {}
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, dict):
        return {}
    return {
        str(rec["branch"]): str(rec["path"])
        for rec in agents.values()
        if isinstance(rec, dict) and rec.get("branch") and rec.get("path")
    }


def worktree_dirty(path: str) -> bool:
    """True when that worktree has uncommitted changes (False if unreadable)."""
    try:
        return bool(_git(Path(path), "status", "--porcelain").strip())
    except GitError:
        return False


def plan_file(root: Path, slug: str) -> Path | None:
    """The plan file for ``slug`` in whatever lane currently holds it."""
    for lane in PLAN_LANES:
        lane_dir = root / ".plans" / lane
        if not lane_dir.is_dir():
            continue
        for path in lane_dir.glob("*.md"):
            stem = path.name[:-9] if path.name.endswith(".local.md") else path.name[:-3]
            if re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem) == slug:
                return path
    return None


def is_held(path: Path | None) -> bool:
    """True when the plan carries a ``## Handoff`` note recording a hold.

    A held plan is finished work its operator deliberately parked for testing —
    visibly different from work nobody has looked at, which is the whole point of
    surfacing it here.
    """
    if path is None or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    section = re.search(r"^##\s+Handoff\s*$(.*?)(?=^##\s|\Z)", text,
                        re.MULTILINE | re.DOTALL)
    # The documented note starts with the word itself ("hold — <reason> — <date>"),
    # so anchor to the start of a line: a prose "hold off on the follow-up" is not
    # a hold, and "held"/"holding" as an opener is.
    return bool(section and re.search(
        # `(?![a-z])` rather than `\b`: underscore is a word character, so `\b`
        # never fires on the closing delimiter of `__held__`.
        r"^\s*(?:[-*]\s*)?(?:\*\*|__)?\s*(hold|held|holding)(?![a-z])",
        section.group(1), re.IGNORECASE | re.MULTILINE))


def find_pending(root: Path | str, *, worktrees: bool = True) -> list[PendingBranch]:
    root = Path(root)
    branches = local_branches(root)
    bset = set(branches)
    done = completed_slugs(root)
    git_trees = branch_worktrees(root) if worktrees else {}
    reg_trees = registry_worktrees(root) if worktrees else {}
    pending: list[PendingBranch] = []
    for branch in branches:
        target = merge_target(branch, bset)
        if not target:
            continue
        ahead = ahead_count(root, target, branch)
        if ahead <= 0:
            continue
        slug = _slug_from_branch(branch)
        # Git is the authority on where a worktree actually is; the registry is a
        # convenience index that outlives removals, so a registry-only hit is
        # reported *and* labeled rather than silently trusted or dropped.
        tree = git_trees.get(branch)
        stale = False
        if tree is None and branch in reg_trees:
            tree, stale = reg_trees[branch], True
        plan = plan_file(root, slug) if slug else None
        pending.append(
            PendingBranch(
                branch=branch,
                target=target,
                ahead=ahead,
                plan_slug=slug,
                completed_plan=bool(slug and slug in done),
                worktree=tree,
                dirty=bool(tree) and not stale and worktree_dirty(tree),
                plan_lane=plan.parent.name if plan else None,
                held=is_held(plan),
                stale_registry=stale,
            )
        )
    # Most-pending first, then completed-plan branches surfaced above bare ones.
    pending.sort(key=lambda p: (not p.completed_plan, -p.ahead, p.branch))
    return pending


def _note(p: PendingBranch) -> str:
    bits: list[str] = []
    if p.held:
        bits.append("held for testing")
    if p.completed_plan:
        bits.append(f"completed plan '{p.plan_slug}' awaiting merge")
    elif p.plan_lane:
        bits.append(f"plan '{p.plan_slug}' in {p.plan_lane}/")
    elif p.plan_slug:
        bits.append(f"plan '{p.plan_slug}' (no plan file found)")
    if p.dirty:
        bits.append("worktree dirty")
    if p.stale_registry:
        bits.append("stale registry")
    return " · ".join(bits)


def format_brief(pending: list[PendingBranch], target: str = "dev") -> str:
    """One line, for the tail of another command's output."""
    if not pending:
        return "handoff: nothing unmerged — every local branch is on its target."
    completed = sum(1 for p in pending if p.completed_plan)
    held = sum(1 for p in pending if p.held)
    targets = {p.target for p in pending} or {target}
    where = "/".join(sorted(targets))
    return (
        f"handoff: {len(pending)} branch(es) ahead of {where} · "
        f"{completed} completed awaiting merge · {held} held"
    )


def format_report(pending: list[PendingBranch], *, worktrees: bool = True) -> str:
    if not pending:
        return "All local branches are merged into their integration target — nothing pending."
    lines = [
        f"{len(pending)} branch(es) with unmerged commits:",
        "",
    ]
    if worktrees:
        lines.append(f"{'branch':<38} {'→ target':<11} {'ahead':>5}  {'worktree':<24} note")
    else:
        lines.append(f"{'branch':<38} {'→ target':<11} {'ahead':>5}  note")
    for p in pending:
        row = f"{p.branch:<38} {'→ ' + p.target:<11} {p.ahead:>5}  "
        if worktrees:
            tree = Path(p.worktree).name if p.worktree else "—"
            row += f"{tree:<24} "
        lines.append(row + _note(p))
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
    ap.add_argument("--brief", action="store_true",
                    help="one summary line instead of the table")
    ap.add_argument("--worktrees", action=argparse.BooleanOptionalAction, default=True,
                    help="join worktree path/dirty state onto each row (default: on)")
    args = ap.parse_args(argv)

    try:
        pending = find_pending(args.root, worktrees=args.worktrees)
    except GitError as exc:
        print(f"pending-merges: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([asdict(p) for p in pending], indent=2))
    elif args.brief:
        print(format_brief(pending))
    else:
        print(format_report(pending, worktrees=args.worktrees))

    return 1 if (pending and args.exit_code) else 0


if __name__ == "__main__":
    sys.exit(main())
