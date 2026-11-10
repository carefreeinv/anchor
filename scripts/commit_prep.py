#!/usr/bin/env python3
"""Deterministic commit-prep for unattended ``--run`` (no harness).

Runs project tests, optionally nudges CHANGELOG.md, prints green/red.
Does **not** ``git commit``. Callers commit on ``feature/<slug>`` after green.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROTECTED_BRANCHES = frozenset({"main", "master", "dev", "develop"})


@dataclass
class PrepResult:
    ok: bool
    notes: list[str] = field(default_factory=list)
    sha: str | None = None
    error: str | None = None


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def current_branch(root: Path) -> str:
    p = _git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    if p.returncode != 0:
        return ""
    return p.stdout.strip()


def dirty_paths(root: Path) -> list[str]:
    p = _git(root, "status", "--porcelain", "-uall", check=False)
    if p.returncode != 0:
        return []
    out: list[str] = []
    for line in p.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.append(path)
    return out


def product_dirty(paths: list[str]) -> list[str]:
    return [p for p in paths if not p.startswith(".plans/") and p != ".plans"]


def run_tests(root: Path) -> tuple[bool, str]:
    """Discover a cheap default. No tests → green skip."""
    has_tests = (root / "tests").is_dir() or (root / "pytest.ini").is_file()
    if not has_tests:
        return True, "no tests directory; skipped"
    py = sys.executable
    p = subprocess.run(
        [py, "-m", "pytest", "-q", "--tb=line"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    log = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        return True, "pytest green"
    return False, f"pytest exit {p.returncode}\n{log[-4000:]}"


def nudge_changelog(root: Path, dirty: list[str]) -> str | None:
    """Add a Changed bullet if CHANGELOG exists and was not already edited."""
    cl = root / "CHANGELOG.md"
    if not cl.is_file():
        return None
    if any(p == "CHANGELOG.md" or p.endswith("/CHANGELOG.md") for p in dirty):
        return None
    product = product_dirty(dirty)
    if not product:
        return None
    text = cl.read_text(encoding="utf-8")
    files = ", ".join(product[:8])
    bullet = f"- **Unattended --run apply.** Touched: {files}.\n"
    if bullet.strip() in text:
        return None
    marker = "### Changed"
    if marker in text:
        text = text.replace(marker, marker + "\n\n" + bullet.rstrip(), 1)
    elif "## [Unreleased]" in text:
        text = text.replace(
            "## [Unreleased]",
            "## [Unreleased]\n\n### Changed\n\n" + bullet.rstrip(),
            1,
        )
    else:
        return None
    cl.write_text(text, encoding="utf-8")
    return "CHANGELOG.md nudged"


def message_from_plan(plan_path: Path | None) -> str:
    if plan_path is None or not plan_path.is_file():
        return "Apply orchestrate --run result."
    body = plan_path.read_text(encoding="utf-8")
    m = re.search(r"^## Goal\s*\n+(.+?)(?=\n## |\Z)", body, re.S | re.M)
    if m:
        line = m.group(1).strip().splitlines()[0].strip()
        if line:
            return line[:200]
    return "Apply orchestrate --run result."


def run_prep(root: Path) -> PrepResult:
    notes: list[str] = []
    ok, msg = run_tests(root)
    notes.append(msg)
    if not ok:
        print(f"[commit-prep] red: {msg}", file=sys.stderr)
        return PrepResult(False, notes=notes, error="tests red")
    dirty = dirty_paths(root)
    nudged = nudge_changelog(root, dirty)
    if nudged:
        notes.append(nudged)
    print("[commit-prep] green", file=sys.stderr)
    return PrepResult(True, notes=notes)


def commit_on_feature(
    root: Path,
    slug: str,
    message: str,
    *,
    no_commit: bool = False,
) -> PrepResult:
    """Green prep then one product commit on ``feature/<slug>``. Never protected branches."""
    branch = current_branch(root)
    if branch in PROTECTED_BRANCHES:
        return PrepResult(
            False,
            error=f"refusing to commit on protected branch {branch!r}",
        )
    expected = f"feature/{slug}"
    if branch != expected:
        return PrepResult(
            True,
            notes=[f"skip commit: HEAD is {branch!r}, not {expected!r}"],
        )
    if no_commit:
        return PrepResult(True, notes=["--no-commit: apply-only"])
    dirty = dirty_paths(root)
    product = product_dirty(dirty)
    if not product:
        return PrepResult(True, notes=["skip commit: no product dirty files"])
    prep = run_prep(root)
    if not prep.ok:
        return prep
    dirty = dirty_paths(root)
    product = product_dirty(dirty)
    if not product:
        return PrepResult(True, notes=prep.notes + ["skip commit: tree clean after prep"])
    add = [p for p in dirty if not p.startswith(".plans/")]
    _git(root, "add", "--", *add)
    msg = message.strip() or "Apply orchestrate --run result."
    p = _git(
        root,
        "commit",
        "-m",
        msg,
        "--",
        *add,
        check=False,
    )
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "git commit failed").strip()
        return PrepResult(False, notes=prep.notes, error=err)
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    print(f"[commit-prep] committed {sha[:12]} on {branch}", file=sys.stderr)
    return PrepResult(True, notes=prep.notes, sha=sha)


def after_run_success(
    worktree: Path | None,
    slug: str,
    plan_path: Path | None,
    *,
    no_commit: bool = False,
) -> PrepResult:
    if worktree is None or not worktree.is_dir():
        return PrepResult(True, notes=["skip commit: no worktree"])
    return commit_on_feature(
        worktree,
        slug,
        message_from_plan(plan_path),
        no_commit=no_commit,
    )
