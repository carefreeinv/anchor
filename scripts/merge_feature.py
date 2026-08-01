#!/usr/bin/env python3
"""Land a finished ``feature/<slug>`` on the integration branch — but only when a
mechanical gate proves the branch is exactly what the caller thinks it is.

This is the machinery behind ``/work``'s end-of-run **"merge to dev now"** answer.
The normal path remains ``/review``: an AI critic plus a human survey. This path
trades the critic for a much narrower mandate — the operator watched the work
happen, so the gate's job is to prove nothing *else* rode along:

1. **Provenance** — the branch head is the commit the caller just made.
2. **Clean tree** — nothing staged, unstaged, or untracked.
3. **File scope** — every path the branch changes is inside the caller's declared
   touched set (evaluated with ``scope_gate.check_scope``, one glob implementation).
4. **Mergeable** — fast-forward preferred; otherwise a conflict-free merge.
5. **Target** — the integration branch only. A target resolving to ``main``/
   ``master`` aborts the merge path rather than landing on mainline.

**Gate 6 — the human answer — is not enforceable here and is deliberately absent.**
It lives in the ``/work`` skill: the operator must answer the culmination question
in-session. Do not add a ``--yes``/``--confirmed`` flag; a flag is exactly the
inference this path forbids, and a fleet worker that could pass one would be able
to merge unattended.

Refusal is the safe outcome everywhere: any failed check routes the work back to
``/review`` rather than landing something unreviewed. This script never pushes,
never force-updates, never deletes a branch, and never touches mainline.

Usage:
  python merge_feature.py --root . --slug my-plan --touched touched.txt --dry-run
  python merge_feature.py --root . --slug my-plan --touched - --base <sha> \\
      --expect-head <sha>

Exit codes: 0 merged (or would merge under --dry-run), 2 git error, 3 scope
violation, 4 precondition failed, 5 merge conflict.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scope_gate import check_scope

EXIT_OK = 0
EXIT_GIT = 2
EXIT_SCOPE = 3
EXIT_PRECONDITION = 4
EXIT_CONFLICT = 5

INTEGRATION_ORDER = ("dev", "develop")
MAINLINE = ("main", "master")


class GitError(RuntimeError):
    """git itself failed (not a repo, command error) — distinct from a refusal."""


@dataclass(frozen=True)
class MergeVerdict:
    """Why the gate passed or refused, in a form both a human and a caller can use."""

    ok: bool
    code: int
    reason: str
    message: str
    offending: tuple[str, ...] = field(default_factory=tuple)

    def report(self) -> str:
        lines = [self.message]
        if self.offending:
            lines += [f"  - {p}" for p in self.offending]
        return "\n".join(lines)


def evaluate_gate(
    *,
    slug: str,
    branch: str,
    target: str,
    head: str,
    expect_head: str | None,
    dirty: tuple[str, ...],
    changed: tuple[str, ...],
    touched: tuple[str, ...],
    conflicts: tuple[str, ...] = (),
    ff_possible: bool = True,
) -> MergeVerdict:
    """Pure gate: given the facts, may this branch land on ``target``?

    Pure so the refusal rules are testable without a git fixture per case, and so
    the order of checks is visible in one place. Order matters — the target check
    runs first because "we were about to merge to main" is worth reporting even if
    the tree is also dirty.
    """
    if target in MAINLINE:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="target-is-mainline",
            message=(
                f"refuse: resolved target '{target}' is mainline. This path lands on the "
                f"integration branch only — mainline is reached through /review's "
                f"promotion survey, never from /work."
            ),
        )
    if not target:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="no-target",
            message="refuse: no integration branch (dev/develop) resolved.",
        )
    if expect_head and head != expect_head:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="provenance",
            message=(
                f"refuse: {branch} is at {head[:12]}, not the commit this run made "
                f"({expect_head[:12]}). Something else moved the branch — that is exactly "
                f"when a human review is warranted."
            ),
        )
    if dirty:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="dirty-tree",
            message=f"refuse: worktree has {len(dirty)} uncommitted path(s).",
            offending=dirty,
        )

    verdict = check_scope(list(changed), list(touched))
    if not verdict.ok:
        return MergeVerdict(
            ok=False, code=EXIT_SCOPE, reason="scope",
            message=(
                f"refuse: {branch} changes path(s) outside what this run declared it "
                f"touched. The branch is not what /work thinks it is — routing to /review."
            ),
            offending=verdict.offending,
        )
    if conflicts:
        return MergeVerdict(
            ok=False, code=EXIT_CONFLICT, reason="conflict",
            message=f"refuse: merging {branch} into {target} conflicts.",
            offending=conflicts,
        )
    how = "fast-forward" if ff_possible else "merge commit (no-ff)"
    return MergeVerdict(
        ok=True, code=EXIT_OK, reason="ok",
        message=f"gate passed: {branch} → {target} ({how}), plan '{slug}'.",
    )


# --- git shell ---------------------------------------------------------------


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git {' '.join(args)} failed: {exc}") from exc
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p


def local_branches(root: Path) -> set[str]:
    out = _git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
    return {b.strip() for b in out.splitlines() if b.strip()}


def resolve_target(root: Path, explicit: str | None = None) -> str:
    """The integration branch this merge would land on.

    Never creates a branch: creation belongs to ``worktree_for_agent.py`` at claim
    time, and a merge path that invents its own target is a merge path that can
    surprise you about where the code went.
    """
    if explicit:
        return explicit
    branches = local_branches(root)
    for name in INTEGRATION_ORDER:
        if name in branches:
            return name
    return ""


def current_branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def head_sha(root: Path, ref: str) -> str:
    return _git(root, "rev-parse", ref).stdout.strip()


def dirty_paths(root: Path) -> tuple[str, ...]:
    out = _git(root, "status", "--porcelain").stdout
    return tuple(line[3:].strip() for line in out.splitlines() if line.strip())


def changed_files(root: Path, base: str, head: str) -> tuple[str, ...]:
    out = _git(root, "diff", "--name-only", f"{base}..{head}").stdout
    return tuple(p.strip() for p in out.splitlines() if p.strip())


def merge_base(root: Path, a: str, b: str) -> str:
    return _git(root, "merge-base", a, b).stdout.strip()


def is_ancestor(root: Path, maybe_ancestor: str, ref: str) -> bool:
    return _git(root, "merge-base", "--is-ancestor", maybe_ancestor, ref,
                check=False).returncode == 0


def probe_conflicts(root: Path, target: str, branch: str) -> tuple[str, ...]:
    """Conflicting paths for a non-fast-forward merge, leaving the tree as found.

    Uses the real merge machinery (``--no-commit --no-ff`` then ``--abort``) rather
    than a prediction: this git is older than ``merge-tree --write-tree``, and a
    wrong guess here would either block a clean merge or promise one that fails
    halfway. Always restores the original branch.
    """
    original = current_branch(root)
    try:
        _git(root, "checkout", target)
        p = _git(root, "merge", "--no-commit", "--no-ff", branch, check=False)
        if p.returncode != 0:
            out = _git(root, "diff", "--name-only", "--diff-filter=U", check=False).stdout
            conflicts = tuple(x.strip() for x in out.splitlines() if x.strip())
            _git(root, "merge", "--abort", check=False)
            return conflicts or ("(merge failed without conflict paths)",)
        _git(root, "merge", "--abort", check=False)
        _git(root, "reset", "--hard", "HEAD", check=False)
        return ()
    finally:
        _git(root, "checkout", original, check=False)


def land(root: Path, branch: str, target: str, *, title: str = "") -> str:
    """Merge ``branch`` into ``target``; return the target's new HEAD.

    Mirrors /review §11's semantics exactly (ff-only preferred, --no-ff fallback,
    abort on conflict) so the two authorization paths cannot drift into different
    merge behavior. Never pushes.
    """
    original = current_branch(root)
    try:
        _git(root, "checkout", target)
        if _git(root, "merge", "--ff-only", branch, check=False).returncode != 0:
            msg = f"Merge {branch}" + (f": {title}" if title else "")
            p = _git(root, "merge", "--no-ff", branch, "-m", msg, check=False)
            if p.returncode != 0:
                _git(root, "merge", "--abort", check=False)
                raise GitError(f"merge conflicted: {p.stdout.strip()} {p.stderr.strip()}")
        return head_sha(root, "HEAD")
    finally:
        _git(root, "checkout", original, check=False)


def read_touched(source: str) -> tuple[str, ...]:
    """One path or glob per line, from a file or stdin (``-``)."""
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        # Order matters: a plan's Touches column yields "- `app/`", so the bullet
        # comes off before the backticks.
        entry = line.strip().lstrip("-* ").strip().strip("`").strip()
        if entry and not entry.startswith("#"):
            out.append(entry)
    return tuple(out)


def run(root: Path, slug: str, touched: tuple[str, ...], *, base: str | None = None,
        expect_head: str | None = None, target: str | None = None,
        branch: str | None = None, dry_run: bool = False,
        title: str = "") -> tuple[MergeVerdict, str | None]:
    """Evaluate the gate and, unless ``dry_run``, land the branch.

    Returns ``(verdict, new_head)``; ``new_head`` is None whenever nothing merged.
    """
    branch = branch or f"feature/{slug}"
    resolved = resolve_target(root, target)
    if branch not in local_branches(root):
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="no-branch",
            message=f"refuse: no local branch '{branch}' to merge.",
        ), None

    # Mainline/no-target refusals must not depend on rev-parsing a branch that may
    # not exist, so evaluate them before gathering the rest of the facts.
    if resolved in MAINLINE or not resolved:
        return evaluate_gate(
            slug=slug, branch=branch, target=resolved, head="", expect_head=None,
            dirty=(), changed=(), touched=touched,
        ), None

    head = head_sha(root, branch)
    merge_from = base or merge_base(root, resolved, branch)
    ff = is_ancestor(root, resolved, branch)
    dirty = dirty_paths(root)
    changed = changed_files(root, merge_from, head)

    # A conflict probe checks out branches; refuse first on anything cheaper so a
    # dirty tree is never disturbed by a probe it was going to fail anyway.
    verdict = evaluate_gate(
        slug=slug, branch=branch, target=resolved, head=head, expect_head=expect_head,
        dirty=dirty, changed=changed, touched=touched, ff_possible=ff,
    )
    if not verdict.ok:
        return verdict, None

    conflicts = () if ff else probe_conflicts(root, resolved, branch)
    verdict = evaluate_gate(
        slug=slug, branch=branch, target=resolved, head=head, expect_head=expect_head,
        dirty=dirty, changed=changed, touched=touched, conflicts=conflicts, ff_possible=ff,
    )
    if not verdict.ok or dry_run:
        return verdict, None
    return verdict, land(root, branch, resolved, title=title)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Gate and land feature/<slug> on the integration branch (never mainline).",
    )
    ap.add_argument("--root", default=".", help="repo or worktree root (default: cwd)")
    ap.add_argument("--slug", required=True, help="plan slug; branch is feature/<slug>")
    ap.add_argument("--branch", help="override the branch name (default: feature/<slug>)")
    ap.add_argument("--touched", required=True,
                    help="file with one touched path/glob per line, or '-' for stdin")
    ap.add_argument("--base", help="merge-base recorded at claim time (default: computed)")
    ap.add_argument("--expect-head",
                    help="SHA this run committed; refuses if the branch moved since")
    ap.add_argument("--target", help="integration branch (default: dev, else develop)")
    ap.add_argument("--title", default="", help="plan title for the merge commit message")
    ap.add_argument("--dry-run", action="store_true",
                    help="evaluate the gate and report; merge nothing")
    args = ap.parse_args(argv)

    try:
        verdict, new_head = run(
            Path(args.root), args.slug, read_touched(args.touched),
            base=args.base, expect_head=args.expect_head, target=args.target,
            branch=args.branch, dry_run=args.dry_run, title=args.title,
        )
    except GitError as exc:
        print(f"merge-feature: {exc}", file=sys.stderr)
        return EXIT_GIT
    except OSError as exc:
        print(f"merge-feature: {exc}", file=sys.stderr)
        return EXIT_GIT

    print(verdict.report())
    if verdict.ok and args.dry_run:
        print("dry run: nothing merged.")
    elif verdict.ok:
        print(f"merged; {args.target or resolve_target(Path(args.root))} is now {new_head[:12]}.")
    return verdict.code


if __name__ == "__main__":
    sys.exit(main())
