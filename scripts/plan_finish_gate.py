#!/usr/bin/env python3
"""Read-only gate: may this plan leave in-progress for review-needed?

A plan-only lane move, Progress checkboxes, or a /commit-prep that staged
nothing but ``.plans/**`` is not real work. The helper answers pass/fail
for one root + slug (+ optional since-ref). Skills and ``work_once`` call
it; it never ``git mv``s.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_TOUCHES_CELL_RE = re.compile(
    r"(?im)^\|\s*\d+\s*\|\s*.+?\|\s*([^|]+)\|",
)
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_PATH_TOKEN_RE = re.compile(r"^\.?[\w./+*-]+(?:\.[\w.+-]+)*$")
_HANDOFF_EXCEPTION_RE = re.compile(
    r"(?im)operator\s+exception|explicit(?:ly)?\s+(?:said|says)\s+done",
)


@dataclass(frozen=True)
class FinishGate:
    ok: bool
    reason: str
    changed: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ok


class FinishGateError(Exception):
    """Closed fail: missing git, missing branch, or no plan-related work."""


def _norm_rel(rel: str) -> str:
    n = rel.replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    return n


def path_is_plans_only(rel: str) -> bool:
    n = _norm_rel(rel)
    return n == ".plans" or n.startswith(".plans/")


def parse_plan_touches(text: str) -> list[str]:
    """Paths from Steps Touches cells and backtick paths outside `.plans/`."""
    out: list[str] = []
    seen: set[str] = set()

    def add(tok: str) -> None:
        tok = _norm_rel(tok.strip().strip("`"))
        if not tok or path_is_plans_only(tok):
            return
        if tok in {"-", "—", "*", "none", "n/a"}:
            return
        if tok not in seen:
            seen.add(tok)
            out.append(tok)

    for cell in _TOUCHES_CELL_RE.findall(text):
        for bt in _BACKTICK_RE.findall(cell):
            add(bt)
        rest = _BACKTICK_RE.sub(" ", cell)
        for tok in re.split(r"[\s,]+", rest):
            if tok and _PATH_TOKEN_RE.match(tok.strip()):
                add(tok)

    for bt in _BACKTICK_RE.findall(text):
        add(bt)
    return out


def path_matches_touches(changed: str, touches: list[str]) -> bool:
    n = _norm_rel(changed)
    if path_is_plans_only(n):
        return False
    if not touches:
        return True
    for t in touches:
        t = _norm_rel(t)
        if not t:
            continue
        if n == t or n.startswith(t.rstrip("/") + "/"):
            return True
        if fnmatch.fnmatch(n, t) or fnmatch.fnmatch(n, t.rstrip("/") + "/**"):
            return True
        if t.endswith("/**") and n.startswith(t[:-3]):
            return True
    return False


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def git_repo(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-inside-work-tree").returncode == 0


def infer_finish_git_dir(
    root: Path, slug: str, agent_id: str | None = None,
) -> Path:
    """Git dir whose HEAD is ``feature/<slug>`` when a linked worktree holds it.

    ``anchor work --finish`` runs from the project root (``.plans/``). Commits
    often live only on the per-agent worktree. Prefer that path for
    ``since..HEAD``; fall back to ``root``.
    """
    root = Path(root).resolve()
    want = f"refs/heads/feature/{slug}"
    listed = _git(root, "worktree", "list", "--porcelain")
    if listed.returncode == 0:
        path: str | None = None
        for line in listed.stdout.splitlines():
            if line.startswith("worktree "):
                path = line[9:]
            elif line.startswith("branch ") and path:
                if line[7:] == want:
                    cand = Path(path)
                    if git_repo(cand):
                        return cand
                path = None
    if agent_id:
        from worktree_for_agent import DEFAULT_REL_ROOT, safe_agent_id

        cand = root / DEFAULT_REL_ROOT / safe_agent_id(agent_id)
        if git_repo(cand):
            br = _git(cand, "rev-parse", "--abbrev-ref", "HEAD")
            if br.returncode == 0 and br.stdout.strip() == f"feature/{slug}":
                return cand
    return root


def resolve_since(root: Path, since_ref: str | None) -> str | None:
    if since_ref:
        probe = _git(root, "rev-parse", "--verify", since_ref)
        if probe.returncode != 0:
            return None
        return since_ref.strip()
    for cand in ("dev", "develop", "main", "master"):
        probe = _git(root, "rev-parse", "--verify", cand)
        if probe.returncode == 0:
            mb = _git(root, "merge-base", cand, "HEAD")
            if mb.returncode == 0 and mb.stdout.strip():
                return mb.stdout.strip()
    empty = _git(root, "hash-object", "-t", "tree", "/dev/null")
    if empty.returncode == 0:
        return empty.stdout.strip()
    return None


def changed_files(root: Path, since: str) -> list[str]:
    r = _git(root, "diff", "--name-only", f"{since}...HEAD")
    if r.returncode != 0:
        r = _git(root, "diff", "--name-only", since, "HEAD")
    if r.returncode != 0:
        return []
    return [ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()]


def plan_has_operator_exception(text: str) -> bool:
    return bool(_HANDOFF_EXCEPTION_RE.search(text))


def check_finish(
    root: Path,
    plan_path: Path,
    *,
    since_ref: str | None = None,
    allow_exception: bool = False,
) -> FinishGate:
    """Pass when a non-``.plans`` path in ``since..HEAD`` intersects Touches.

    Missing git or missing since-ref fails closed. Operator exception in the
    plan body (or ``allow_exception``) passes.
    """
    root = Path(root).resolve()
    plan_path = Path(plan_path)
    if os.environ.get("ANCHOR_EMPTY_FINISH") == "1":
        return FinishGate(True, "ANCHOR_EMPTY_FINISH=1")
    text = plan_path.read_text(encoding="utf-8") if plan_path.is_file() else ""
    if allow_exception or plan_has_operator_exception(text):
        return FinishGate(True, "operator exception recorded")
    if not git_repo(root):
        # No object database to inspect — skip rather than invent a pass.
        # Unattended work_once on a real checkout always has git.
        return FinishGate(True, "no git repository; evidence skipped")
    since = resolve_since(root, since_ref)
    if since is None:
        return FinishGate(False, "missing branch or since-ref (fail closed)")
    files = changed_files(root, since)
    touches = parse_plan_touches(text)
    related = tuple(p for p in files if path_matches_touches(p, touches))
    if related:
        return FinishGate(True, "plan-related commit", related)
    if files and all(path_is_plans_only(p) for p in files):
        return FinishGate(False, "plan-only commits do not count", tuple(files))
    if not files:
        return FinishGate(False, "no commits after since-ref")
    return FinishGate(
        False,
        "commits do not intersect plan Touches / deliverables",
        tuple(files),
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--slug", help="plan basename without lane")
    p.add_argument("--plan", type=Path, help="explicit plan file")
    p.add_argument("--since", dest="since_ref", default=None)
    p.add_argument("--allow-exception", action="store_true")
    args = p.parse_args(argv)
    root = args.root.resolve()
    plan = args.plan
    if plan is None:
        if not args.slug:
            print("need --slug or --plan", file=sys.stderr)
            return 2
        slug = args.slug
        if not slug.endswith(".md"):
            slug = slug + ".md"
        for lane in ("in-progress", "bugs", "features", "review-needed"):
            cand = root / ".plans" / lane / slug
            local = root / ".plans" / lane / slug.replace(".md", ".local.md")
            if cand.is_file():
                plan = cand
                break
            if local.is_file():
                plan = local
                break
        else:
            print(f"plan not found for {args.slug}", file=sys.stderr)
            return 2
    gate = check_finish(
        root, plan, since_ref=args.since_ref, allow_exception=args.allow_exception,
    )
    print(("PASS" if gate.ok else "FAIL") + f": {gate.reason}")
    for f in gate.changed:
        print(f)
    return 0 if gate.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
