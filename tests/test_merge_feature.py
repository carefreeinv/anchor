"""The scoped-merge gate: refusing is always safe, landing must be earned.

Every refusal path here routes the work back to /review rather than landing
something unreviewed, so these tests are mostly about *not* merging.
"""
import subprocess
from pathlib import Path

import pytest
from merge_feature import (
    EXIT_CONFLICT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_SCOPE,
    evaluate_gate,
    main,
    read_touched,
    run,
)


def _git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                       text=True, check=True)
    return p.stdout.strip()


def _commit(root: Path, name: str, text: str, message: str) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(git_repo: Path) -> Path:
    """main + dev, and a feature branch with one in-scope commit on app/x.py."""
    _git(git_repo, "branch", "dev")
    _git(git_repo, "checkout", "-b", "feature/my-plan", "dev")
    _commit(git_repo, "app/x.py", "x = 1\n", "feature work")
    return git_repo


TOUCHED = ("app/",)


# --- pure gate ----------------------------------------------------------------


def _gate(**overrides):
    kwargs = dict(slug="my-plan", branch="feature/my-plan", target="dev", head="abc",
                  expect_head=None, dirty=(), changed=("app/x.py",), touched=TOUCHED)
    kwargs.update(overrides)
    return evaluate_gate(**kwargs)


def test_gate_passes_on_clean_in_scope_branch():
    verdict = _gate()
    assert verdict.ok and verdict.code == EXIT_OK


def test_gate_refuses_when_target_is_mainline():
    """The one refusal that must fire before anything else is checked."""
    verdict = _gate(target="main", dirty=("junk.py",))

    assert not verdict.ok
    assert verdict.reason == "target-is-mainline"
    assert verdict.code == EXIT_PRECONDITION
    assert "/review" in verdict.message


def test_gate_refuses_when_branch_head_moved_since_the_run():
    verdict = _gate(head="deadbeef", expect_head="abc123")

    assert verdict.reason == "provenance"
    assert verdict.code == EXIT_PRECONDITION


def test_gate_refuses_dirty_tree_and_names_the_paths():
    verdict = _gate(dirty=("notes.txt",))

    assert verdict.reason == "dirty-tree"
    assert verdict.offending == ("notes.txt",)


def test_gate_refuses_out_of_scope_change_and_names_the_path():
    verdict = _gate(changed=("app/x.py", "deploy/prod.yaml"))

    assert verdict.reason == "scope"
    assert verdict.code == EXIT_SCOPE
    assert verdict.offending == ("deploy/prod.yaml",)


def test_gate_refuses_on_conflicts():
    verdict = _gate(conflicts=("app/x.py",), ff_possible=False)

    assert verdict.reason == "conflict"
    assert verdict.code == EXIT_CONFLICT


def test_gate_reports_how_it_would_land():
    assert "fast-forward" in _gate().message
    assert "no-ff" in _gate(ff_possible=False).message


# --- end to end ---------------------------------------------------------------


def test_fast_forward_merge_lands_on_dev(repo):
    verdict, new_head = run(repo, "my-plan", TOUCHED)

    assert verdict.ok
    assert new_head == _git(repo, "rev-parse", "feature/my-plan")
    assert _git(repo, "rev-parse", "dev") == new_head
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"  # restored


def test_non_ff_clean_merge_creates_a_merge_commit(repo):
    """dev moved on an unrelated file — still clean, so it lands as a merge commit."""
    _git(repo, "checkout", "dev")
    _commit(repo, "app/other.py", "y = 2\n", "dev moved")
    _git(repo, "checkout", "feature/my-plan")

    verdict, new_head = run(repo, "my-plan", TOUCHED)

    assert verdict.ok
    assert "no-ff" in verdict.message
    parents = _git(repo, "rev-list", "--parents", "-n", "1", "dev").split()
    assert len(parents) == 3  # commit + two parents = a real merge commit


def test_conflict_aborts_and_leaves_dev_untouched(repo):
    _git(repo, "checkout", "dev")
    dev_before = _commit(repo, "app/x.py", "conflicting\n", "dev touched the same file")
    _git(repo, "checkout", "feature/my-plan")

    verdict, new_head = run(repo, "my-plan", TOUCHED)

    assert verdict.code == EXIT_CONFLICT
    assert new_head is None
    assert _git(repo, "rev-parse", "dev") == dev_before  # nothing landed
    assert _git(repo, "status", "--porcelain") == ""     # no merge left in progress
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"


def test_out_of_scope_file_refuses_with_exit_3_naming_the_path(repo):
    _commit(repo, "deploy/prod.yaml", "replicas: 99\n", "snuck in a deploy change")

    verdict, new_head = run(repo, "my-plan", TOUCHED)

    assert verdict.code == EXIT_SCOPE
    assert "deploy/prod.yaml" in verdict.offending
    assert new_head is None
    assert _git(repo, "rev-parse", "dev") != _git(repo, "rev-parse", "feature/my-plan")


def test_dirty_tree_refuses_with_exit_4(repo):
    (repo / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")

    verdict, _ = run(repo, "my-plan", TOUCHED)

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "dirty-tree"


def test_head_moved_since_the_run_refuses_with_exit_4(repo):
    stale = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "app/x.py", "x = 2\n", "someone else pushed to the branch")

    verdict, _ = run(repo, "my-plan", TOUCHED, expect_head=stale)

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "provenance"


def test_target_resolving_to_mainline_is_refused(repo):
    verdict, _ = run(repo, "my-plan", TOUCHED, target="main")

    assert verdict.reason == "target-is-mainline"
    assert _git(repo, "rev-parse", "main") != _git(repo, "rev-parse", "feature/my-plan")


def test_missing_branch_refuses(repo):
    verdict, _ = run(repo, "no-such-plan", TOUCHED)

    assert verdict.reason == "no-branch"
    assert verdict.code == EXIT_PRECONDITION


def test_dry_run_mutates_nothing(repo):
    dev_before = _git(repo, "rev-parse", "dev")
    head_before = _git(repo, "rev-parse", "HEAD")

    verdict, new_head = run(repo, "my-plan", TOUCHED, dry_run=True)

    assert verdict.ok  # would merge...
    assert new_head is None  # ...but did not
    assert _git(repo, "rev-parse", "dev") == dev_before
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert _git(repo, "status", "--porcelain") == ""


def test_dry_run_probes_a_non_ff_merge_without_leaving_state(repo):
    _git(repo, "checkout", "dev")
    dev_before = _commit(repo, "app/other.py", "y = 2\n", "dev moved")
    _git(repo, "checkout", "feature/my-plan")

    verdict, _ = run(repo, "my-plan", TOUCHED, dry_run=True)

    assert verdict.ok
    assert _git(repo, "rev-parse", "dev") == dev_before
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"


# --- CLI ----------------------------------------------------------------------


def test_read_touched_strips_bullets_backticks_and_comments(tmp_path):
    f = tmp_path / "touched.txt"
    f.write_text("# what this run touched\n- `app/`\nscripts/x.py\n\n", encoding="utf-8")

    assert read_touched(str(f)) == ("app/", "scripts/x.py")


def test_cli_dry_run_exits_zero_and_merges_nothing(repo, tmp_path, capsys):
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    dev_before = _git(repo, "rev-parse", "dev")

    code = main(["--root", str(repo), "--slug", "my-plan",
                 "--touched", str(touched), "--dry-run"])

    assert code == EXIT_OK
    assert "dry run" in capsys.readouterr().out
    assert _git(repo, "rev-parse", "dev") == dev_before


def test_cli_scope_violation_exits_three(repo, tmp_path, capsys):
    _commit(repo, "deploy/prod.yaml", "replicas: 99\n", "out of scope")
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(touched)])

    assert code == EXIT_SCOPE
    assert "deploy/prod.yaml" in capsys.readouterr().out
