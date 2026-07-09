#!/usr/bin/env python3
"""Scope gate: reject worktree changes that touch files outside a task spec's
``## Files in scope`` — before tests run. Turns mythos-core rule 7 ("scope is
sacred") from a promise into a mechanical check.

Layers, cleanest first:

- ``check_scope(diff_paths, in_scope, allowed_generated)`` — **pure**; no git, no
  I/O. Classifies each changed path as in-scope, allowlisted, or offending.
- ``worktree_changes(root)`` — the changed paths in a git worktree (tracked diff
  vs HEAD plus untracked files).
- ``enforce_scope(root, in_scope, allowed_generated)`` — the two combined.
- ``parse_scope(spec_text)`` — pull ``## Files in scope`` + ``Allowed generated
  files:`` out of a task-spec.

CLI, usable as a verify **pre-step** so tests never run on an out-of-scope diff::

    python scope_gate.py --root <worktree> --spec <task-spec.md> && pytest -q

Exit codes: 0 in scope (or no scope declared — gate inactive), 3 scope violation,
2 could not determine changes (e.g. not a git worktree).

Glob semantics (gitignore-style; ``PurePath.full_match`` is 3.13+ and this repo
targets 3.10+):

- ``*`` matches within a path segment (not ``/``)
- ``**`` matches across segments (any depth, including none)
- a trailing ``/`` marks a directory subtree (``scripts/`` covers everything under it)
- a plain path with no glob matches exactly, or as a directory prefix
  (``scripts/foo`` matches ``scripts/foo`` and ``scripts/foo/bar.py``, but not
  ``scripts/foobar``)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

FILES_IN_SCOPE_RE = re.compile(
    r"^##\s+Files in scope\s*$([\s\S]*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE
)
ALLOWED_GENERATED_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?Allowed generated files:?(?:\*\*)?\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)


class ScopeError(RuntimeError):
    """Raised when the worktree's changes cannot be determined (e.g. no git)."""


@dataclass(frozen=True)
class ScopeVerdict:
    ok: bool
    offending: tuple[str, ...] = ()
    in_scope: tuple[str, ...] = ()
    allowed_generated: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class ScopeConfig:
    """Everything the gate needs to check one worktree against one spec."""

    root: Path
    in_scope: tuple[str, ...]
    allowed_generated: tuple[str, ...] = ()


def _normalize(path: str) -> str:
    p = path.strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a gitignore-style glob into an anchored regex."""
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                if pattern[i : i + 1] == "/":  # '**/' — slash folded into the .*
                    i += 1
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


def path_matches(path: str, pattern: str) -> bool:
    """True if ``path`` falls under scope ``pattern`` (see module glob semantics)."""
    path = _normalize(path)
    pattern = _normalize(pattern.strip())
    if not pattern:
        return False
    if pattern.endswith("/"):  # already stripped by _normalize, but be explicit
        pattern = pattern.rstrip("/")
    if "*" in pattern or "?" in pattern:
        return _glob_to_regex(pattern).match(path) is not None
    return path == pattern or path.startswith(pattern + "/")


def check_scope(
    diff_paths: list[str] | tuple[str, ...],
    in_scope: list[str] | tuple[str, ...],
    allowed_generated: list[str] | tuple[str, ...] = (),
) -> ScopeVerdict:
    """Pure classifier: which changed paths fall outside the declared scope.

    No ``## Files in scope`` declared (empty ``in_scope`` and no allowlist) →
    the gate is **inactive** (``ok=True``): there is nothing to enforce against,
    and blocking every change would break specs that predate the section.
    """
    in_scope = tuple(s for s in (x.strip() for x in in_scope) if s)
    allowed_generated = tuple(s for s in (x.strip() for x in allowed_generated) if s)

    if not in_scope and not allowed_generated:
        return ScopeVerdict(
            ok=True,
            message="scope gate inactive: no '## Files in scope' declared",
        )

    offending = tuple(
        p
        for p in diff_paths
        if not any(path_matches(p, s) for s in in_scope)
        and not any(path_matches(p, s) for s in allowed_generated)
    )
    ok = not offending
    return ScopeVerdict(
        ok=ok,
        offending=offending,
        in_scope=in_scope,
        allowed_generated=allowed_generated,
        message=_format_message(ok, offending, in_scope, allowed_generated),
    )


def _format_message(
    ok: bool,
    offending: tuple[str, ...],
    in_scope: tuple[str, ...],
    allowed_generated: tuple[str, ...],
) -> str:
    if ok:
        return "scope OK: all changes are within '## Files in scope'"
    lines = [
        "SCOPE VIOLATION: change touches files outside the task spec's "
        "'## Files in scope'.",
        "Offending paths:",
        *(f"  - {p}" for p in offending),
        "In scope:",
        *(f"  - {s}" for s in (in_scope or ("(none declared)",))),
    ]
    if allowed_generated:
        lines += ["Allowed generated:", *(f"  - {s}" for s in allowed_generated)]
    lines.append(
        "Fix: add these paths to the task spec's '## Files in scope' (or "
        "'Allowed generated files:') via the planner — do not widen scope "
        "mid-task."
    )
    return "\n".join(lines)


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
        raise ScopeError(f"git {' '.join(args)} failed: {exc}") from exc
    if p.returncode != 0:
        raise ScopeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def worktree_changes(root: Path | str) -> list[str]:
    """Repo-relative paths changed in the worktree: tracked diff vs HEAD + untracked."""
    root = Path(root)
    tracked = _git(root, "diff", "--name-only", "HEAD")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    paths: set[str] = set()
    for block in (tracked, untracked):
        for line in block.splitlines():
            line = line.strip()
            if line:
                paths.add(_normalize(line))
    return sorted(paths)


def enforce_scope(
    root: Path | str,
    in_scope: list[str] | tuple[str, ...],
    allowed_generated: list[str] | tuple[str, ...] = (),
    *,
    changes: list[str] | None = None,
) -> ScopeVerdict:
    """Read the worktree's changes (unless supplied) and classify them."""
    if changes is None:
        changes = worktree_changes(root)
    return check_scope(changes, in_scope, allowed_generated)


def enforce_config(cfg: ScopeConfig, *, changes: list[str] | None = None) -> ScopeVerdict:
    return enforce_scope(cfg.root, cfg.in_scope, cfg.allowed_generated, changes=changes)


def _clean_entry(line: str) -> str:
    line = re.sub(r"^\s*[-*]\s+", "", line.strip())
    line = line.strip().strip("`").strip()
    # a scope line may carry a trailing note: "path — why" / "path  (why)"
    line = re.split(r"\s+[—–]\s+|\s+-\s+|\s{2,}|\s+\(", line, maxsplit=1)[0]
    return line.strip().strip("`").strip()


def parse_scope(spec_text: str) -> tuple[list[str], list[str]]:
    """Extract (in_scope, allowed_generated) from a task-spec markdown body."""
    in_scope: list[str] = []
    m = FILES_IN_SCOPE_RE.search(spec_text)
    if m:
        for raw in m.group(1).splitlines():
            entry = _clean_entry(raw)
            if not entry:
                continue
            if entry.startswith(("<", "#", "(")) or entry.lower().startswith(
                "allowed generated files"
            ):
                continue
            in_scope.append(entry)

    allowed: list[str] = []
    am = ALLOWED_GENERATED_RE.search(spec_text)
    if am:
        for tok in re.split(r"[,\s]+", am.group(1).strip()):
            tok = tok.strip().strip("`")
            if tok and not tok.startswith(("(", "<", "#")):
                allowed.append(tok)
    return in_scope, allowed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Reject worktree changes outside a task spec's '## Files in scope'. "
            "Use as a verify pre-step: scope_gate.py --root . --spec spec.md && pytest -q"
        )
    )
    ap.add_argument("--root", default=".", help="worktree root (default: cwd)")
    ap.add_argument("--spec", help="task-spec markdown containing '## Files in scope'")
    ap.add_argument(
        "--in-scope",
        nargs="*",
        default=None,
        help="explicit in-scope paths/globs (overrides --spec parsing)",
    )
    ap.add_argument(
        "--allowed-generated",
        nargs="*",
        default=None,
        help="allowlisted generated-file globs (lockfiles, snapshots)",
    )
    args = ap.parse_args(argv)

    in_scope: list[str] = []
    allowed: list[str] = []
    if args.spec:
        in_scope, allowed = parse_scope(Path(args.spec).read_text(encoding="utf-8"))
    if args.in_scope is not None:
        in_scope = args.in_scope
    if args.allowed_generated is not None:
        allowed = args.allowed_generated

    try:
        verdict = enforce_scope(args.root, in_scope, allowed)
    except ScopeError as exc:
        print(f"scope-gate: {exc}", file=sys.stderr)
        return 2

    print(verdict.message, file=sys.stdout if verdict.ok else sys.stderr)
    return 0 if verdict.ok else 3


if __name__ == "__main__":
    sys.exit(main())
