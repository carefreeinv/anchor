"""Tests for scripts/aider_repo_map_preflight.py (network-lunar-style HEAD ghosts)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import aider_repo_map_preflight as preflight
import pytest


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "keep.txt").write_text("keep\n", encoding="utf-8")
    (root / "site").mkdir()
    (root / "site" / "docs").mkdir(parents=True)
    # network-lunar-style: module docs as .md that will "migrate" to .mdx
    for name in ("index.md", "alpha.md", "beta.md"):
        (root / "site" / "docs" / name).write_text(f"# {name}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    return root


def test_scan_clean_repo(tmp_path):
    root = _init_repo(tmp_path)
    report = preflight.scan(root)
    assert report.ok
    assert report.stale_for_aider == []


def test_scan_detects_worktree_and_head_ghosts(tmp_path):
    root = _init_repo(tmp_path)
    # Migrate on disk: delete .md, add .mdx (HEAD still has .md)
    for name in ("index.md", "alpha.md", "beta.md"):
        (root / "site" / "docs" / name).unlink()
        (root / "site" / "docs" / name.replace(".md", ".mdx")).write_text(
            f"# {name}x\n", encoding="utf-8"
        )

    report = preflight.scan(root)
    assert not report.ok
    assert set(report.deleted_in_worktree) == {
        "site/docs/index.md",
        "site/docs/alpha.md",
        "site/docs/beta.md",
    }
    assert set(report.missing_from_head) >= set(report.deleted_in_worktree)
    warn = preflight.format_warning(report, sample=2)
    assert "3 path(s)" in warn or "path(s) missing" in warn
    assert "HEAD∪index" in warn
    assert "network-lunar" in warn
    assert "git add -u" in warn


def test_stage_alone_leaves_head_ghosts(tmp_path):
    """Document Aider reality: git add -u does not clear HEAD-side ghosts."""
    root = _init_repo(tmp_path)
    (root / "site" / "docs" / "index.md").unlink()

    before = preflight.scan(root)
    assert "site/docs/index.md" in before.deleted_in_worktree

    staged = preflight.stage_deletions(before, yes=True)
    assert staged == ["site/docs/index.md"]

    after = preflight.scan(root)
    assert after.deleted_in_worktree == []
    assert "site/docs/index.md" in after.missing_from_head
    assert not after.ok


def test_write_aiderignore_requires_yes(tmp_path):
    root = _init_repo(tmp_path)
    (root / "site" / "docs" / "index.md").unlink()
    report = preflight.scan(root)
    with pytest.raises(ValueError, match="yes"):
        preflight.write_aiderignore(report, yes=False)


def test_write_aiderignore_hides_ghosts(tmp_path):
    root = _init_repo(tmp_path)
    (root / "site" / "docs" / "index.md").unlink()
    report = preflight.scan(root)
    path = preflight.write_aiderignore(report, yes=True)
    assert path is not None and path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "site/docs/index.md" in text
    # Idempotent second write
    preflight.write_aiderignore(preflight.scan(root), yes=True)
    assert path.read_text(encoding="utf-8").count("site/docs/index.md") == 1


def test_cli_json_and_exit_codes(tmp_path, monkeypatch, capsys):
    root = _init_repo(tmp_path)
    monkeypatch.chdir(root)
    assert preflight.main(["--json"]) == 0

    (root / "site" / "docs" / "alpha.md").unlink()
    assert preflight.main([]) == 1
    out = capsys.readouterr().out
    assert "aider-repo-map preflight" in out

    assert preflight.main(["--ok-exit"]) == 0


def _bare_repo(tmp_path):
    """An empty git repo — no files, no commit. Distinct from this module's
    existing `_init_repo`, which scaffolds and commits a site/docs tree."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    return tmp_path


def test_scan_tolerates_repo_with_no_commits(tmp_path):
    """A fresh `git init` has no HEAD; that is an empty HEAD set, not an error.

    Regression for the review finding: `scan()` ran `git ls-tree -r HEAD`
    unconditionally and raised RuntimeError with a raw
    `fatal: Not a valid object name HEAD`, escaping before --ok-exit could
    soften it. Aider itself tolerates this (repo.py catches ValueError).
    """
    root = _bare_repo(tmp_path)
    (root / "a.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.md"], check=True)
    report = preflight.scan(root)          # must not raise
    assert report.missing_from_head == []


def test_stage_deletions_stages_only_deletes_on_rename(tmp_path):
    """Pins the documented limitation that made the shipped checklist lossy.

    `--stage` stages the delete side of a rename only. The new file stays
    untracked, so an operator who commits straight after loses it. The fix is
    documentation (help text, success output, brief checklist) — this test
    exists so the behaviour cannot silently change without the docs changing.
    """
    root = _bare_repo(tmp_path)
    d = root / "d"
    d.mkdir()
    (d / "a.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    (d / "a.md").unlink()
    (d / "a.mdx").write_text("x", encoding="utf-8")

    staged = preflight.stage_deletions(preflight.scan(root), yes=True)
    assert staged == ["d/a.md"]
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True, text=True, check=True).stdout
    assert "D  d/a.md" in status
    # The add side is NOT staged. Note git collapses it to the *directory*
    # ("?? d/"), not the filename — so an operator skimming `git status` after
    # --stage sees one terse untracked-dir line, which is exactly why the
    # shipped checklist lost files.
    assert "?? d/" in status
    assert "A  d/a.mdx" not in status


def test_aiderignore_escapes_special_leading_characters(tmp_path):
    """`#`, `!` and `[` are gitwildmatch metacharacters, not literals."""
    report = preflight.StaleIndexReport(
        root=str(tmp_path),
        deleted_in_worktree=["#hash.md", "!bang.md", "a[1].md"],
        missing_from_head=[],
    )
    out = preflight.write_aiderignore(report, path=tmp_path / ".aiderignore", yes=True)
    body = out.read_text(encoding="utf-8")
    assert "\\#hash.md" in body
    assert "\\!bang.md" in body
    assert "a\\[1].md" in body
    assert "TEMPORARY" in body          # the block says to remove itself


def test_sample_zero_omits_the_sample_header(tmp_path):
    """`--sample 0` printed a bare `sample:` header followed by `… +N more`."""
    report = preflight.StaleIndexReport(
        root=str(tmp_path), deleted_in_worktree=["a.md", "b.md"], missing_from_head=[])
    out = preflight.format_warning(report, sample=0)
    assert "sample:" not in out
    assert "2 path(s), sample suppressed" in out
