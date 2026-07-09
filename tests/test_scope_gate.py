"""Tests for scripts/scope_gate.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scope_gate import (
    ScopeError,
    check_scope,
    enforce_scope,
    parse_scope,
    path_matches,
    worktree_changes,
)

REPO = Path(__file__).resolve().parents[1]


# --- pure path matching --------------------------------------------------


def test_path_matches_exact_and_dir_prefix():
    assert path_matches("scripts/foo.py", "scripts/foo.py")
    assert path_matches("scripts/foo.py", "scripts/")  # directory subtree
    assert path_matches("scripts/foo.py", "scripts")  # plain dir prefix
    assert not path_matches("scripts/foobar.py", "scripts/foo")  # not a prefix segment
    assert not path_matches("README.md", "README")  # exact, no accidental prefix


def test_path_matches_globs():
    assert path_matches("scripts/foo.py", "scripts/*.py")
    assert not path_matches("scripts/sub/foo.py", "scripts/*.py")  # * stays in segment
    assert path_matches("scripts/sub/foo.py", "scripts/**/*.py")  # ** crosses segments
    assert path_matches("scripts/foo.py", "scripts/**/*.py")  # ** matches zero segments
    assert path_matches("a/b/c/d.txt", "**/*.txt")
    assert not path_matches("a/b/c/d.py", "**/*.txt")


# --- pure check_scope ----------------------------------------------------


def test_check_scope_in_scope_and_out_of_scope():
    v = check_scope(["scripts/scope_gate.py", "secret.py"], ["scripts/scope_gate.py"])
    assert not v.ok
    assert v.offending == ("secret.py",)
    assert "SCOPE VIOLATION" in v.message


def test_check_scope_all_in_scope_passes():
    v = check_scope(["scripts/a.py", "scripts/b.py"], ["scripts/"])
    assert v.ok
    assert v.offending == ()


def test_check_scope_allowlisted_generated_passes():
    v = check_scope(
        ["src/app.py", "poetry.lock"],
        ["src/app.py"],
        allowed_generated=["*.lock"],
    )
    assert v.ok


def test_check_scope_untracked_out_of_scope_flagged():
    # an untracked new file outside scope is still a violation
    v = check_scope(["src/app.py", "src/sneaky_new.py"], ["src/app.py"])
    assert not v.ok
    assert "src/sneaky_new.py" in v.offending


def test_check_scope_inactive_when_nothing_declared():
    v = check_scope(["anything.py"], [])
    assert v.ok  # nothing to enforce against
    assert "inactive" in v.message


# --- spec parsing --------------------------------------------------------


def test_parse_scope_reads_files_in_scope_and_allowlist():
    spec = (
        "# Task: x\n\n"
        "## Files in scope\n"
        "- `scripts/scope_gate.py`\n"
        "- `tests/test_scope_gate.py` — the unit tests\n"
        "<placeholder line to ignore>\n\n"
        "## Constraints\n"
        "- Allowed generated files: `*.lock`, snapshots/**\n\n"
        "## Out of scope\n- everything else\n"
    )
    in_scope, allowed = parse_scope(spec)
    assert in_scope == ["scripts/scope_gate.py", "tests/test_scope_gate.py"]
    assert allowed == ["*.lock", "snapshots/**"]


# --- git-backed enforcement (integration) --------------------------------


def test_worktree_changes_and_enforce(git_repo: Path):
    # in-scope tracked edit + out-of-scope untracked file
    (git_repo / "README").write_text("changed\n", encoding="utf-8")
    (git_repo / "secret.py").write_text("x = 1\n", encoding="utf-8")

    changes = worktree_changes(git_repo)
    assert "README" in changes
    assert "secret.py" in changes

    v = enforce_scope(git_repo, ["README"])
    assert not v.ok
    assert v.offending == ("secret.py",)

    v2 = enforce_scope(git_repo, ["README", "*.py"])
    assert v2.ok


def test_enforce_scope_raises_without_git(tmp_path: Path):
    import pytest

    with pytest.raises(ScopeError):
        worktree_changes(tmp_path)  # not a git repo


def test_cli_rejects_out_of_scope(git_repo: Path):
    (git_repo / "secret.py").write_text("x = 1\n", encoding="utf-8")
    spec = git_repo / "spec.md"
    spec.write_text(
        "## Files in scope\n- `README`\n", encoding="utf-8"
    )
    script = REPO / "scripts" / "scope_gate.py"
    r = subprocess.run(
        [sys.executable, str(script), "--root", str(git_repo), "--spec", str(spec)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 3, r.stdout + r.stderr
    assert "secret.py" in (r.stdout + r.stderr)
