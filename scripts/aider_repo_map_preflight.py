#!/usr/bin/env python3
"""Preflight for Aider repo-map noise from deleted-but-still-tracked paths.

Aider's ``get_tracked_files`` is approximately **HEAD tree ∪ index**. When files
are deleted on disk (e.g. ``.md`` → ``.mdx`` migration) but still present in
``HEAD``, Aider prints one::

    Repo-map can't include /…/path
    Has it been deleted from the file system but not from git?

…per path, drowning the chat. ``git add -u`` alone does **not** clear those
warnings — staged deletions leave the path in the HEAD set until you **commit**
or hide the ghosts with ``.aiderignore``.

This helper:

1. Detects worktree deletions (``git ls-files -d``) **and** HEAD paths missing
   on disk (the Aider-relevant set).
2. Prints **one** actionable warning block (count + sample + HEAD∪index caveat).
3. Optionally (``--yes`` required) stages scoped deletions or appends
   ``.aiderignore`` lines. Never commits.

Usage::

    python scripts/aider_repo_map_preflight.py [--root DIR]
    python scripts/aider_repo_map_preflight.py --write-aiderignore --yes
    python scripts/aider_repo_map_preflight.py --stage --yes
    python scripts/aider_repo_map_preflight.py --json

Exit: ``0`` clean (or only advisory printed), ``1`` stale paths found (default),
``2`` not a git worktree / git error. ``--ok-exit`` forces ``0`` when stale so
launchers can warn without failing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SAMPLE_DEFAULT = 8

# Cited consumer repro (2026-09-06): network-lunar module docs .md → .mdx left
# dozens of HEAD paths missing on disk; Aider flooded repo-map warnings.


@dataclass
class StaleIndexReport:
    root: str
    deleted_in_worktree: list[str] = field(default_factory=list)
    missing_from_head: list[str] = field(default_factory=list)

    @property
    def stale_for_aider(self) -> list[str]:
        """Paths Aider may still try to map (union, stable order)."""
        seen: set[str] = set()
        out: list[str] = []
        for p in self.missing_from_head + self.deleted_in_worktree:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    @property
    def ok(self) -> bool:
        return not self.stale_for_aider


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git_lines(root: Path, *args: str) -> list[str]:
    proc = _git(root, *args)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {root}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return [ln for ln in proc.stdout.splitlines() if ln]


def _git_lines_or_empty(root: Path, *args: str) -> list[str]:
    """Like :func:`_git_lines`, but a failing command yields no lines.

    Only for reads where "this does not exist yet" is a legitimate state —
    currently ``ls-tree HEAD`` in a repo with no commits.
    """
    proc = _git(root, *args)
    if proc.returncode != 0:
        return []
    return [ln for ln in proc.stdout.splitlines() if ln]


def find_git_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    proc = _git(start, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise RuntimeError(f"not a git worktree: {start}")
    return Path(proc.stdout.strip()).resolve()


def scan(root: Path | None = None) -> StaleIndexReport:
    """Return deleted worktree paths and HEAD paths missing on disk."""
    git_root = find_git_root(root)
    deleted = _git_lines(git_root, "ls-files", "-d")
    # A repo with no commits has no HEAD: `ls-tree HEAD` exits non-zero with
    # "Not a valid object name HEAD". That is an empty HEAD set, not an error —
    # Aider itself tolerates it (repo.py catches ValueError and sets
    # commit = None). Raising here made --ok-exit unreachable, since the
    # exception escaped before that check.
    head_paths = _git_lines_or_empty(git_root, "ls-tree", "-r", "--name-only", "HEAD")
    missing: list[str] = []
    for rel in head_paths:
        if not (git_root / rel).exists():
            missing.append(rel)
    return StaleIndexReport(
        root=str(git_root),
        deleted_in_worktree=deleted,
        missing_from_head=missing,
    )


def format_warning(report: StaleIndexReport, *, sample: int = SAMPLE_DEFAULT) -> str:
    stale = report.stale_for_aider
    if not stale:
        return ""
    n = len(stale)
    shown = stale[: max(0, sample)]
    more = n - len(shown)
    lines = [
        f"aider-repo-map preflight: {n} path(s) missing on disk but still in "
        f"git HEAD/index (Aider maps HEAD∪index — repo-map will flood).",
        f"  root: {report.root}",
    ]
    if shown:
        lines.append("  sample:")
        lines.extend(f"    - {p}" for p in shown)
    if more > 0:
        lines.append(f"    … +{more} more" if shown else f"    ({more} path(s), sample suppressed)")
    lines.extend(
        [
            "  why staging alone is not enough: `git add -u` removes the path from",
            "  the *index*, but Aider still sees it via HEAD until you commit — or",
            "  hide ghosts with `.aiderignore`.",
            "  next (pick one):",
            "    1) stage the migration, then commit it:",
            "         # `git add -u` stages DELETIONS ONLY. For a rename",
            "         # (e.g. .md→.mdx) it leaves the NEW files untracked, and",
            "         # committing then loses them. Stage both sides:",
            "         git add -A -- <dir>/     # deletes AND new files",
            "         # (or: git add -u -- <paths…> && git add -- <new paths…>)",
            "         # then your normal /commit-prep + commit",
            "    2) interim ignore until commit (and `!.aiderignore` if `.aider*`",
            "       is gitignored):",
            "         python scripts/aider_repo_map_preflight.py --write-aiderignore --yes",
            "  repro class: network-lunar 2026-09-06 (.md→.mdx left HEAD ghosts).",
        ]
    )
    return "\n".join(lines) + "\n"


def _escape_ignore_line(path: str) -> str:
    """Escape a path for gitwildmatch (Aider's ``.aiderignore`` syntax).

    A leading ``#`` is a comment and a leading ``!`` is a negation, so both are
    backslash-escaped. ``[`` opens a character class and would silently fail to
    match the literal filename.
    """
    out = path.replace("[", "\\[")
    if out.startswith("#") or out.startswith("!"):
        out = "\\" + out
    return out


def write_aiderignore(
    report: StaleIndexReport,
    *,
    path: Path | None = None,
    yes: bool = False,
) -> Path | None:
    """Append missing HEAD paths to ``.aiderignore``. Requires ``yes=True``."""
    if not yes:
        raise ValueError("refusing to write .aiderignore without yes=True")
    stale = report.stale_for_aider
    if not stale:
        return None
    root = Path(report.root)
    ignore = path or (root / ".aiderignore")
    existing: set[str] = set()
    if ignore.is_file():
        existing = {
            ln.strip()
            for ln in ignore.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        }
    to_add = [p for p in stale if p not in existing]
    if not to_add:
        return ignore
    block = [
        "",
        "# Anchor aider_repo_map_preflight — HEAD paths missing on disk.",
        "# TEMPORARY: delete this block once the migration is committed, or these",
        "# entries keep real files out of Aider's repo-map after they come back.",
    ]
    block.extend(_escape_ignore_line(p) for p in to_add)
    with ignore.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block) + "\n")
    return ignore


def stage_deletions(report: StaleIndexReport, *, yes: bool = False) -> list[str]:
    """``git add -u`` for deleted worktree paths only. Never commits. Needs yes.

    **Stages the delete side only.** For a rename (D+A) — the .md→.mdx class
    this script exists for — the new files stay untracked, so committing right
    after this drops them. Callers must stage the add side themselves
    (``git add -A -- <dir>/``). Deliberately not done here: this helper is
    scoped to the paths the report found, and the add side is by definition
    paths the report cannot know about.
    """
    if not yes:
        raise ValueError("refusing to stage without yes=True")
    root = Path(report.root)
    deleted = report.deleted_in_worktree
    if not deleted:
        return []
    proc = _git(root, "add", "-u", "--", *deleted)
    if proc.returncode != 0:
        raise RuntimeError(f"git add -u failed: {proc.stderr.strip()}")
    return deleted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=None, help="git worktree (default: cwd)")
    ap.add_argument("--sample", type=int, default=SAMPLE_DEFAULT, help="paths to show")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument(
        "--write-aiderignore",
        action="store_true",
        help="append stale paths to .aiderignore (requires --yes)",
    )
    ap.add_argument(
        "--stage",
        action="store_true",
        help=("git add -u for deleted worktree paths ONLY (requires --yes; never "
              "commits). Does NOT stage new files: after a rename, stage the add "
              "side too (git add -A -- <dir>/) or committing will drop them"),
    )
    ap.add_argument(
        "--yes",
        action="store_true",
        help="confirm write/stage actions (required for mutating flags)",
    )
    ap.add_argument(
        "--ok-exit",
        action="store_true",
        help="exit 0 even when stale (warn-only launcher mode)",
    )
    args = ap.parse_args(argv)

    try:
        report = scan(args.root)
    except RuntimeError as exc:
        print(f"aider-repo-map preflight: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = asdict(report)
        payload["stale_for_aider"] = report.stale_for_aider
        payload["ok"] = report.ok
        print(json.dumps(payload, indent=2))
    else:
        if report.ok:
            print("aider-repo-map preflight: ok (no HEAD/index ghosts on disk)")
        else:
            sys.stdout.write(format_warning(report, sample=args.sample))

    try:
        if args.write_aiderignore:
            written = write_aiderignore(report, yes=args.yes)
            if written and not args.json:
                print(f"wrote/updated: {written}")
        if args.stage:
            staged = stage_deletions(report, yes=args.yes)
            if staged and not args.json:
                print(f"staged {len(staged)} deletion(s) (not committed)")
                print("  deletions only — if this was a rename, stage the new "
                      "files too (git add -A -- <dir>/) before committing")
    except ValueError as exc:
        print(f"aider-repo-map preflight: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"aider-repo-map preflight: {exc}", file=sys.stderr)
        return 2

    if report.ok or args.ok_exit:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
