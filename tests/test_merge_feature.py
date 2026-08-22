"""The scoped-merge gate: refusing is always safe, landing must be earned.

Every refusal path here routes the work back to /review rather than landing
something unreviewed, so these tests are mostly about *not* merging.
"""
import json
import subprocess
from pathlib import Path

import pytest
from merge_feature import (
    EXIT_CONFLICT,
    EXIT_GIT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_SCOPE,
    EXIT_STAGED,
    changed_files,
    evaluate_gate,
    main,
    read_staged_state,
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


def _head(root: Path, ref: str = "feature/my-plan") -> str:
    return _git(root, "rev-parse", ref)


# --- pure gate ----------------------------------------------------------------


def _gate(**overrides):
    kwargs = dict(slug="my-plan", branch="feature/my-plan", target="dev", head="abc",
                  expect_head="abc", dirty=(), changed=("app/x.py",), touched=TOUCHED)
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
    verdict, new_head = run(repo, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.ok
    assert new_head == _git(repo, "rev-parse", "feature/my-plan")
    assert _git(repo, "rev-parse", "dev") == new_head
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"  # restored


def test_non_ff_merge_is_staged_not_committed(repo):
    """dev moved on an unrelated file — clean, but a merge COMMIT needs prep first.

    The merged tree is state neither branch was prepped in, so `land` stops with the
    merge staged and hands control back. Committing here would be exactly the
    unprepped merge commit the hard rule forbids.
    """
    from merge_feature import STAGED

    _git(repo, "checkout", "dev")
    _commit(repo, "app/other.py", "y = 2\n", "dev moved")
    # Captured *after* dev moves: the divergence is what forces the non-ff path,
    # and the assertion below is that a staged merge leaves dev where it is now.
    dev_before = _git(repo, "rev-parse", "dev")
    _git(repo, "checkout", "feature/my-plan")

    verdict, result = run(repo, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.ok
    assert "no-ff" in verdict.message
    assert result == STAGED
    assert _git(repo, "rev-parse", "dev") == dev_before      # no commit created
    assert (Path(repo) / ".git" / "MERGE_HEAD").exists()     # merge really is staged
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "dev"  # stays on target


def test_commit_staged_includes_preps_working_tree_edits(repo):
    """A bare `git commit` during a merge commits only the index, dropping prep's own
    output. commit_staged stages everything first."""
    import merge_feature as mf

    _git(repo, "checkout", "dev")
    _commit(repo, "app/other.py", "y = 2\n", "dev moved")
    _git(repo, "checkout", "feature/my-plan")

    assert mf.land(repo, "feature/my-plan", "dev") == mf.STAGED
    (Path(repo) / "CHANGELOG.md").write_text("prep added this", encoding="utf-8")
    new_head = mf.commit_staged(repo, "feature/my-plan", "dev",
                                read_staged_state(repo)["merged_sha"],
                                original="feature/my-plan")

    assert _git(repo, "rev-parse", "dev") == new_head
    # `git show --stat` on a merge prints a condensed combined diff, so assert
    # against the committed tree instead of the diff rendering.
    # commit_staged restores the original branch, so inspect `dev`, not HEAD.
    tree = _git(repo, "ls-tree", "-r", "--name-only", "dev")
    assert "CHANGELOG.md" in tree                       # prep's own edit landed
    assert "app/other.py" in tree                       # and so did dev's side
    assert _git(repo, "status", "--short") == ""        # tree left clean
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"


def test_abort_staged_recovers_even_when_merge_abort_refuses(repo):
    """`git merge --abort` refuses once prep has edited a file involved in the merge —
    exactly what its fix-the-tests gate does. abort_staged falls back to a reset."""
    import merge_feature as mf

    _git(repo, "checkout", "dev")
    _commit(repo, "app/other.py", "y = 2\n", "dev moved")
    dev_before = _git(repo, "rev-parse", "dev")
    _git(repo, "checkout", "feature/my-plan")

    assert mf.land(repo, "feature/my-plan", "dev") == mf.STAGED
    (Path(repo) / "app" / "x.py").write_text("prep touched a merged file\n",
                                             encoding="utf-8")
    merged = read_staged_state(repo)["merged_sha"]
    mf.abort_staged(repo, "feature/my-plan", "dev", merged, original="feature/my-plan")

    assert _git(repo, "rev-parse", "dev") == dev_before          # nothing committed
    assert not (Path(repo) / ".git" / "MERGE_HEAD").exists()     # merge state cleared
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"


def test_conflict_aborts_and_leaves_dev_untouched(repo):
    _git(repo, "checkout", "dev")
    dev_before = _commit(repo, "app/x.py", "conflicting\n", "dev touched the same file")
    _git(repo, "checkout", "feature/my-plan")

    verdict, new_head = run(repo, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.code == EXIT_CONFLICT
    assert new_head is None
    assert _git(repo, "rev-parse", "dev") == dev_before  # nothing landed
    assert _git(repo, "status", "--porcelain") == ""     # no merge left in progress
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"


def test_out_of_scope_file_refuses_with_exit_3_naming_the_path(repo):
    _commit(repo, "deploy/prod.yaml", "replicas: 99\n", "snuck in a deploy change")

    verdict, new_head = run(repo, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.code == EXIT_SCOPE
    assert "deploy/prod.yaml" in verdict.offending
    assert new_head is None
    assert _git(repo, "rev-parse", "dev") != _git(repo, "rev-parse", "feature/my-plan")


def test_dirty_tree_refuses_with_exit_4(repo):
    (repo / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")

    verdict, _ = run(repo, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "dirty-tree"


def test_head_moved_since_the_run_refuses_with_exit_4(repo):
    stale = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "app/x.py", "x = 2\n", "someone else pushed to the branch")

    verdict, _ = run(repo, "my-plan", TOUCHED, expect_head=stale)

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "provenance"


def test_target_resolving_to_mainline_is_refused(repo):
    verdict, _ = run(repo, "my-plan", TOUCHED, target="main", expect_head=_head(repo))

    assert verdict.reason == "target-is-mainline"
    assert _git(repo, "rev-parse", "main") != _git(repo, "rev-parse", "feature/my-plan")


def test_missing_branch_refuses(repo):
    verdict, _ = run(repo, "no-such-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.reason == "no-branch"
    assert verdict.code == EXIT_PRECONDITION


def test_dry_run_mutates_nothing(repo):
    dev_before = _git(repo, "rev-parse", "dev")
    head_before = _git(repo, "rev-parse", "HEAD")

    verdict, new_head = run(repo, "my-plan", TOUCHED, dry_run=True, expect_head=_head(repo))

    assert verdict.ok  # would merge...
    assert new_head is None  # ...but did not
    assert _git(repo, "rev-parse", "dev") == dev_before
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert _git(repo, "status", "--porcelain") == ""


def test_dry_run_probes_a_non_ff_merge_without_leaving_state(repo):
    _git(repo, "checkout", "dev")
    dev_before = _commit(repo, "app/other.py", "y = 2\n", "dev moved")
    _git(repo, "checkout", "feature/my-plan")

    verdict, _ = run(repo, "my-plan", TOUCHED, dry_run=True, expect_head=_head(repo))

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

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(touched),
                 "--expect-head", _head(repo), "--dry-run"])

    assert code == EXIT_OK
    assert "dry run" in capsys.readouterr().out
    assert _git(repo, "rev-parse", "dev") == dev_before


def test_cli_scope_violation_exits_three(repo, tmp_path, capsys):
    _commit(repo, "deploy/prod.yaml", "replicas: 99\n", "out of scope")
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(touched),
                 "--expect-head", _head(repo)])

    assert code == EXIT_SCOPE
    assert "deploy/prod.yaml" in capsys.readouterr().out


# --- the ways a scope check can pass vacuously ---------------------------------
# Each of these was a reproduced bypass: an undeclared change landing on dev with
# exit 0. The scope check is only as strong as the facts it is handed.


def test_empty_touched_set_refuses_instead_of_disabling_the_gate(repo):
    """check_scope treats "no scope" as inactive; here that must be a refusal."""
    _commit(repo, "deploy/prod.yaml", "replicas: 99\n", "undeclared change")

    verdict, new_head = run(repo, "my-plan", (), expect_head=_head(repo))

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "no-touched-set"
    assert new_head is None
    assert _git(repo, "rev-parse", "dev") != _git(repo, "rev-parse", "feature/my-plan")


def test_comment_only_touched_file_reads_as_empty(tmp_path):
    f = tmp_path / "touched.txt"
    f.write_text("# what this run touched\n\n", encoding="utf-8")

    assert read_touched(str(f)) == ()


def test_rename_out_of_scope_is_caught_via_its_deleted_source(repo):
    """A rename's source path must not vanish behind git's rename detection."""
    (repo / "secrets").mkdir()
    (repo / "secrets" / "creds.yml").write_text("token: hunter2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add secrets")
    _git(repo, "checkout", "dev")
    _git(repo, "merge", "--ff-only", "feature/my-plan")
    _git(repo, "checkout", "feature/my-plan")
    _git(repo, "mv", "secrets/creds.yml", "app/creds.yml")
    _git(repo, "commit", "-m", "move creds into app/")

    verdict, new_head = run(repo, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.code == EXIT_SCOPE
    assert "secrets/creds.yml" in verdict.offending  # the deletion is visible
    assert new_head is None


def test_add_then_delete_out_of_scope_path_is_caught(repo):
    """Net two-dot diff is empty for the path; history union must still see it."""
    _commit(repo, "secrets/creds.yml", "token: hunter2\n", "add secret")
    # second commit removes it — git diff base..head --name-only is empty for it
    _git(repo, "rm", "secrets/creds.yml")
    _git(repo, "commit", "-m", "remove secret again")
    base = _git(repo, "rev-parse", "dev")
    head = _head(repo)
    net = _git(repo, "diff", "--no-renames", "--name-only", f"{base}..{head}")
    assert "secrets/creds.yml" not in net.splitlines()
    assert "secrets/creds.yml" in changed_files(repo, base, head)

    verdict, new_head = run(repo, "my-plan", TOUCHED, expect_head=head)

    assert verdict.code == EXIT_SCOPE
    assert "secrets/creds.yml" in verdict.offending
    assert new_head is None


def test_add_then_delete_in_scope_path_still_passes_scope(repo):
    """History names the path; if it is inside --touched, the scope check allows it."""
    _commit(repo, "app/tmp.flag", "1\n", "add in-scope temp")
    _git(repo, "rm", "app/tmp.flag")
    _git(repo, "commit", "-m", "drop temp")
    head = _head(repo)

    verdict, new_head = run(repo, "my-plan", TOUCHED, expect_head=head, dry_run=True)

    assert verdict.ok
    assert new_head is None  # dry-run


def test_base_inside_the_range_is_refused(repo):
    """--base <branch head> would empty the diff and pass everything."""
    _commit(repo, "deploy/prod.yaml", "replicas: 99\n", "undeclared change")
    head = _head(repo)

    verdict, new_head = run(repo, "my-plan", TOUCHED, base=head, expect_head=head)

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "bad-base"
    assert new_head is None


def test_a_legitimate_base_is_still_accepted(repo):
    verdict, _ = run(repo, "my-plan", TOUCHED, base=_git(repo, "rev-parse", "dev"),
                     expect_head=_head(repo), dry_run=True)

    assert verdict.ok


def test_missing_expect_head_refuses(repo):
    """Provenance is a must-hold condition, not an optional extra."""
    verdict, new_head = run(repo, "my-plan", TOUCHED)

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "provenance-missing"
    assert new_head is None


def test_cli_requires_expect_head(repo, tmp_path):
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")

    # --expect-head is only mandatory on the merge route (the --commit-staged /
    # --abort-staged finishers resume a merge and have no use for it), so this is
    # a checked refusal rather than an argparse SystemExit. What matters is that
    # it still refuses and still merges nothing.
    dev_before = _git(repo, "rev-parse", "dev")
    assert main(["--root", str(repo), "--slug", "my-plan",
                 "--touched", str(touched)]) == EXIT_PRECONDITION
    assert _git(repo, "rev-parse", "dev") == dev_before


# --- the target may only ever be integration -----------------------------------


def test_non_integration_target_is_refused(repo):
    _git(repo, "branch", "release", "dev")
    release_before = _git(repo, "rev-parse", "release")

    verdict, new_head = run(repo, "my-plan", TOUCHED, target="release",
                            expect_head=_head(repo))

    assert verdict.reason == "target-not-integration"
    assert new_head is None
    assert _git(repo, "rev-parse", "release") == release_before  # untouched


def test_fully_qualified_mainline_ref_cannot_evade_the_guard(repo):
    """'refs/heads/main' must resolve to 'main' before the mainline compare."""
    verdict, new_head = run(repo, "my-plan", TOUCHED, target="refs/heads/main",
                            expect_head=_head(repo))

    assert verdict.reason == "target-is-mainline"
    assert new_head is None


def test_target_checked_out_in_another_worktree_refuses_before_the_gate_passes(
    repo, tmp_path
):
    """The Anchor topology: /work in a worktree, dev checked out in the main repo."""
    other = tmp_path / "elsewhere"
    _git(repo, "worktree", "add", str(other), "dev")

    verdict, new_head = run(repo, "my-plan", TOUCHED, expect_head=_head(repo),
                            dry_run=True)

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "target-checked-out-elsewhere"
    assert "elsewhere" in verdict.message  # names where, and how to fix it
    assert new_head is None


# --- entry parsing keeps globs intact ------------------------------------------


def test_read_touched_unwraps_markdown_bold(tmp_path):
    f = tmp_path / "touched.txt"
    f.write_text("**app/secret.py**\n- **scripts/**\n**/*.py\n", encoding="utf-8")

    assert read_touched(str(f)) == ("app/secret.py", "scripts/", "**/*.py")


def test_read_touched_preserves_leading_globs(tmp_path):
    f = tmp_path / "touched.txt"
    f.write_text("*.md\n**/tests/*.py\n- `app/`\n", encoding="utf-8")

    assert read_touched(str(f)) == ("*.md", "**/tests/*.py", "app/")


def test_unreadable_touched_file_is_a_precondition_failure_not_a_git_error(repo):
    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", "/nope/missing.txt",
                 "--expect-head", _head(repo)])

    assert code == EXIT_PRECONDITION


# --- clean tree means the tree that did the work -------------------------------
# The gate's own remedy for a busy target ("re-run with --root <the dev checkout>")
# used to move the dirty check onto the wrong tree, so the documented guarantee was
# false on exactly the path the docs prescribe.


def test_dirty_feature_worktree_is_caught_when_root_is_the_integration_checkout(
    repo, tmp_path
):
    dev_tree = tmp_path / "dev-checkout"
    _git(repo, "worktree", "add", str(dev_tree), "dev")
    (repo / "app" / "x.py").write_text("x = 999  # uncommitted\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")

    verdict, new_head = run(dev_tree, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "dirty-tree"
    assert str(repo) in verdict.message          # names which tree it checked
    assert new_head is None
    assert _git(repo, "rev-parse", "dev") != _head(repo)


def test_clean_feature_worktree_still_merges_from_the_integration_checkout(
    repo, tmp_path
):
    dev_tree = tmp_path / "dev-checkout"
    _git(repo, "worktree", "add", str(dev_tree), "dev")

    verdict, new_head = run(dev_tree, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.ok
    assert _git(repo, "rev-parse", "dev") == new_head


def test_subdirectory_root_does_not_false_refuse(repo):
    """Every other call uses `git -C`, which works from a subdirectory."""
    verdict, _ = run(repo / "app", "my-plan", TOUCHED, expect_head=_head(repo),
                     dry_run=True)

    assert verdict.ok


def test_scope_violation_is_reported_before_run_it_elsewhere(repo, tmp_path):
    """Content problems outrank 'run this somewhere else'."""
    _commit(repo, "deploy/prod.yaml", "replicas: 99\n", "undeclared change")
    dev_tree = tmp_path / "dev-checkout"
    _git(repo, "worktree", "add", str(dev_tree), "dev")

    verdict, _ = run(repo, "my-plan", TOUCHED, expect_head=_head(repo))

    assert verdict.code == EXIT_SCOPE
    assert "deploy/prod.yaml" in verdict.offending


def test_abbreviated_expect_head_is_resolved_before_comparing(repo):
    verdict, _ = run(repo, "my-plan", TOUCHED, expect_head=_head(repo)[:8],
                     dry_run=True)

    assert verdict.ok  # not a self-contradicting provenance refusal


def test_unresolvable_target_is_a_precondition_not_a_git_error(repo):
    verdict, _ = run(repo, "my-plan", TOUCHED, target="origin/dev",
                     expect_head=_head(repo))

    assert verdict.code == EXIT_PRECONDITION
    assert verdict.reason == "no-such-target"


def test_binary_touched_file_exits_four_not_one(repo, tmp_path):
    blob = tmp_path / "touched.bin"
    blob.write_bytes(b"\xff\xfe\x00binary\x00")

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(blob),
                 "--expect-head", _head(repo)])

    assert code == EXIT_PRECONDITION


# --- a staged merge is not a merge (B7) ---------------------------------------
#
# `land()` returns STAGED when the merge cannot fast-forward: the merge is in the
# index, uncommitted, waiting for /commit-prep to run against the merged tree.
# The CLI used to print "merged; dev is now STAGED." and exit 0 — reporting a
# merge that had not happened, to a caller with no route to finish or undo it.


def _diverge(root: Path) -> str:
    """Put a commit on dev so the feature branch can no longer fast-forward."""
    _git(root, "checkout", "dev")
    _commit(root, "docs/note.md", "dev side\n", "dev-side work")
    _git(root, "checkout", "feature/my-plan")
    return _head(root, "dev")


def _merge_argv(root: Path, touched: Path) -> list[str]:
    return ["--root", str(root), "--slug", "my-plan", "--touched", str(touched),
            "--expect-head", _head(root), "--target", "dev"]


@pytest.fixture
def staged(repo: Path, tmp_path: Path, capsys):
    """A repo parked mid-merge, exactly as a non-ff `land()` leaves it.

    The output is read here and handed back: a test body's own `capsys` starts
    after fixture setup and would see nothing.
    """
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    dev_before = _diverge(repo)
    code = main(_merge_argv(repo, touched))
    return repo, code, dev_before, capsys.readouterr().out


def test_staged_merge_does_not_report_success(staged):
    _repo, code, _dev_before, out = staged
    assert code == EXIT_STAGED, "a staged merge must not exit 0"
    assert code != EXIT_OK
    assert "STAGED:" in out and "NOT committed" in out
    # The old message read "merged; dev is now STAGED." — the word must not
    # appear as a claim that the merge landed.
    assert "merged; dev is now" not in out


def test_staged_merge_tells_the_caller_how_to_finish_it(staged):
    *_rest, out = staged
    assert "--commit-staged" in out
    assert "--abort-staged" in out
    assert "/commit-prep" in out


def test_commit_staged_includes_preps_own_edits_in_the_merge_commit(staged):
    repo, _code, _dev_before, _out = staged
    # /commit-prep updates the CHANGELOG against the merged tree.
    (repo / "CHANGELOG.md").write_text("- entry\n", encoding="utf-8")
    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_OK

    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"
    files = _git(repo, "show", "dev", "--stat", "--format=")
    assert "CHANGELOG.md" in files, "prep's edits were dropped by the merge commit"
    assert _git(repo, "status", "--porcelain") == ""


def test_abort_staged_restores_dev_even_after_prep_touched_a_merged_file(staged):
    repo, _code, dev_before, _out = staged
    # The B2 case: bare `git merge --abort` exits 128 once a merged file has
    # unstaged modifications, so the abort path needs the reset fallback.
    (repo / "app/x.py").write_text("x = 1\nprep edit\n", encoding="utf-8")
    assert main(["--root", str(repo), "--abort-staged"]) == EXIT_OK

    assert _git(repo, "rev-parse", "dev") == dev_before, "dev moved on a red prep"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature/my-plan"
    assert _git(repo, "status", "--porcelain") == ""


def test_finishers_clear_the_staged_state(staged):
    repo, _code, _dev_before, _out = staged
    assert read_staged_state(repo) is not None
    main(["--root", str(repo), "--abort-staged"])
    assert read_staged_state(repo) is None
    # A second finisher call has nothing to finish and must say so, not crash.
    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_PRECONDITION


def test_finishers_do_not_require_the_merge_arguments(repo):
    # --slug/--touched/--expect-head describe a merge; the finishers resume one.
    # argparse used to make them mandatory on every route.
    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_PRECONDITION


def test_a_fast_forward_merge_still_reports_a_real_sha(repo, tmp_path):
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    assert main(_merge_argv(repo, touched)) == EXIT_OK
    assert read_staged_state(repo) is None


# --- hostile state: the six tests above are all happy-path (B1/B2/B3) --------
#
# A stale state file (operator hand-aborted, an interrupted run, a corrupted
# record) or a linked worktree must not make `--commit-staged` `git add -A` and
# commit whatever is lying around, or land on the wrong branch, or crash outright.


def test_commit_staged_refuses_after_a_hand_aborted_merge(staged):
    # The operator (or a previous, unfinished run) aborted the merge directly,
    # bypassing --abort-staged — MERGE_HEAD is gone but the JSON record survives.
    repo, _code, dev_before, _out = staged
    _git(repo, "merge", "--abort")
    assert not (repo / ".git" / "MERGE_HEAD").exists()
    assert read_staged_state(repo) is not None, "the stale record is still there"

    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_PRECONDITION
    assert _git(repo, "rev-parse", "dev") == dev_before, "nothing should have landed"
    assert _git(repo, "status", "--porcelain") == ""


def test_commit_staged_refuses_when_the_state_file_names_the_wrong_branch(staged):
    # A corrupted or stale record whose "target" no longer matches the branch
    # actually mid-merge (e.g. two staged merges in a row, the second record
    # overwriting the first before it was finished). MERGE_HEAD is genuinely
    # present, so this is not the hand-aborted case above.
    repo, _code, dev_before, _out = staged
    state_path = repo / ".git" / "merge-feature-staged.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["target"] == "dev"
    state["target"] = "main"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_PRECONDITION
    assert _git(repo, "rev-parse", "dev") == dev_before, "dev must not move"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "dev", (
        "refusing must not itself switch branches"
    )
    main_log = _git(repo, "log", "--oneline", "main")
    assert "Merge" not in main_log, "must not have committed onto the named branch"


def test_abort_staged_does_not_reset_a_tree_it_no_longer_describes(staged):
    """The mirror of the commit_staged guard, and the more destructive half.

    `git merge --abort` fails when there is no merge, and the fallback is
    `git reset --hard` — which against a stale record destroys whatever unrelated
    uncommitted work the operator has since put in the tree, then reports success.
    """
    repo, _code, dev_before, _out = staged
    _git(repo, "merge", "--abort")           # operator aborts by hand
    assert read_staged_state(repo) is not None, "the record is now stale"

    (repo / "docs/note.md").write_text("dev side\nprecious uncommitted work\n",
                                       encoding="utf-8")
    assert main(["--root", str(repo), "--abort-staged"]) == EXIT_OK

    assert "precious" in (repo / "docs/note.md").read_text(encoding="utf-8"), (
        "abort_staged reset a tree its stale record did not describe, destroying "
        "the operator's unrelated uncommitted work"
    )
    assert _git(repo, "rev-parse", "dev") == dev_before
    # The record is gone, so this is also the escape hatch commit_staged's
    # refusal points the operator at.
    assert read_staged_state(repo) is None


def test_abort_staged_refuses_a_merge_in_progress_on_another_branch(staged):
    repo, _code, _dev_before, _out = staged
    state_path = repo / ".git" / "merge-feature-staged.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["target"] = "main"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert main(["--root", str(repo), "--abort-staged"]) == EXIT_PRECONDITION
    assert (repo / ".git" / "MERGE_HEAD").exists(), "the real merge must survive"
    assert read_staged_state(repo) is not None


def test_finishers_report_a_non_repo_root_within_the_documented_exit_codes(tmp_path):
    """`--root` that is not a git repo must not surface as a traceback.

    Resolving the state file shells out to git (it has to, to find a linked
    worktree's real git dir), so this path can raise where pure path arithmetic
    could not. Exit 1 from a traceback is outside the set every doc documents.
    """
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    for flag in ("--commit-staged", "--abort-staged"):
        assert main(["--root", str(plain), flag]) == EXIT_GIT


def test_state_path_works_inside_a_linked_worktree(repo, tmp_path):
    # B1: `<root>/.git` is a FILE in a linked worktree, not a directory —
    # `var/worktrees/<agent-id>/` is the topology `/work` itself recommends, so
    # this is a regression in Anchor's own recommended setup, not an edge case.
    _git(repo, "checkout", "main")
    worktree = tmp_path / "linked-worktree"
    _git(repo, "worktree", "add", str(worktree), "dev")
    assert (worktree / ".git").is_file(), "a linked worktree's .git must be a file"

    feature_head = _head(repo)
    _commit(worktree, "docs/note.md", "dev side\n", "dev-side work")

    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    code = main(["--root", str(worktree), "--slug", "my-plan", "--touched", str(touched),
                 "--expect-head", feature_head, "--target", "dev"])
    assert code == EXIT_STAGED

    assert read_staged_state(worktree) is not None
    # The state lives under the worktree's own git dir, not the main repo's.
    assert not (repo / ".git" / "merge-feature-staged.json").exists()

    assert main(["--root", str(worktree), "--commit-staged"]) == EXIT_OK
    subject = _git(worktree, "log", "-1", "--format=%s", "dev")
    assert subject.startswith("Merge feature/my-plan")
    assert _git(worktree, "status", "--porcelain") == ""


# -- the record must describe the merge in front of us (F1/F2/F3) -------------
#
# MERGE_HEAD existing is not evidence the staged merge is OURS, and --root's own
# state was never checked at all. Each test below reproduces a defect that a
# fully green suite previously allowed.


def _stage_a_foreign_merge(repo: Path) -> str:
    """Stage a merge of feature/other onto dev by hand, as an operator would."""
    _git(repo, "checkout", "-b", "feature/other", "dev")
    _commit(repo, "other/y.py", "y = 2\n", "unrelated work")
    other = _head(repo, "feature/other")
    _git(repo, "checkout", "dev")
    subprocess.run(["git", "-C", str(repo), "merge", "--no-ff", "--no-commit",
                    "feature/other"], capture_output=True, text=True)
    return other


def test_commit_staged_refuses_a_merge_of_a_different_branch(staged):
    # F1: stale record for feature/my-plan + a hand-staged merge of feature/other
    # used to commit feature/other's content under my-plan's name, exit 0 --
    # bypassing the scope gate, provenance and --expect-head entirely.
    repo, _code, dev_before, _out = staged
    _git(repo, "merge", "--abort")
    assert read_staged_state(repo) is not None, "record is stale but still present"
    foreign = _stage_a_foreign_merge(repo)
    assert _head(repo, "MERGE_HEAD") == foreign

    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_PRECONDITION
    assert _git(repo, "rev-parse", "dev") == dev_before, "committed a foreign merge"
    assert _head(repo, "MERGE_HEAD") == foreign, "someone else's merge was disturbed"


def test_abort_staged_refuses_to_throw_away_a_different_merge(staged):
    # F1 mirror arm: --abort-staged is what the stale-state refusal tells the
    # operator to run, so it must not abort a merge the record does not describe.
    repo, _code, _dev_before, _out = staged
    _git(repo, "merge", "--abort")
    foreign = _stage_a_foreign_merge(repo)

    assert main(["--root", str(repo), "--abort-staged"]) == EXIT_PRECONDITION
    assert _head(repo, "MERGE_HEAD") == foreign, "aborted someone else's merge"
    assert read_staged_state(repo) is not None


def _split_topology(repo: Path, tmp_path: Path) -> Path:
    """The topology `/work` prescribes, and the only one where F2/F3 bite.

    `--root` is the integration checkout; the feature branch lives in its own
    linked worktree. That split is the whole point: `evaluate_gate`'s dirty check
    follows the *feature* worktree, so `--root`'s own state goes unexamined. In a
    single checkout the two coincide and the pre-existing check already catches
    everything — a test written that way passes with the fix reverted.
    """
    _git(repo, "checkout", "dev")
    wt = tmp_path / "agent-worktree"
    _git(repo, "worktree", "add", str(wt), "feature/my-plan")
    return wt


def test_merge_refuses_when_root_already_has_a_staged_merge(repo, tmp_path):
    # F3: probe_conflicts runs `git merge` then `git merge --abort`, which would
    # unwind a merge already staged in --root. Both skills point every agent at
    # the same shared checkout, so this is the ordinary fleet case.
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    _diverge(repo)
    head = _head(repo)
    _split_topology(repo, tmp_path)
    _stage_a_foreign_merge(repo)
    foreign_merge_head = _head(repo, "MERGE_HEAD")

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(touched),
                 "--expect-head", head, "--target", "dev"])

    assert code == EXIT_PRECONDITION
    assert _head(repo, "MERGE_HEAD") == foreign_merge_head, (
        "the in-progress merge in --root was destroyed by the conflict probe"
    )


def test_merge_refuses_when_root_has_untracked_files(repo, tmp_path):
    # F2: commit_staged's `git add -A` cannot tell /commit-prep's output from
    # whatever was already lying around, so a stray .env.local or build artifact
    # sitting in the integration checkout lands in the merge commit.
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    _diverge(repo)
    head = _head(repo)
    _split_topology(repo, tmp_path)
    (repo / ".env.local").write_text("SECRET=hunter2\n", encoding="utf-8")

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(touched),
                 "--expect-head", head, "--target", "dev"])

    assert code == EXIT_PRECONDITION
    assert read_staged_state(repo) is None, "staged a merge into an unclean root"
    assert (repo / ".env.local").exists(), "must not have touched the stray file"


def test_malformed_state_record_stays_inside_the_documented_exit_codes(staged):
    # F8: a record that parses but lacks `branch`/`target` used to raise KeyError
    # -> traceback, exit 1, outside the set every doc documents.
    repo, _code, _dev_before, _out = staged
    state_path = repo / ".git" / "merge-feature-staged.json"
    state_path.write_text(json.dumps({"target": "dev"}), encoding="utf-8")  # no branch

    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_PRECONDITION
    assert main(["--root", str(repo), "--abort-staged"]) == EXIT_PRECONDITION


def test_both_finisher_flags_together_are_refused(staged):
    # F9: this used to silently run the commit path -- the destructive-if-wrong
    # one -- for an operator who plainly did not mean either specifically.
    repo, _code, dev_before, _out = staged
    assert main(["--root", str(repo), "--commit-staged", "--abort-staged"]) == \
        EXIT_PRECONDITION
    assert _git(repo, "rev-parse", "dev") == dev_before
    assert read_staged_state(repo) is not None, "nothing should have been finished"


def test_dry_run_is_refused_on_the_finishers_rather_than_ignored(staged):
    # F9: silently ignoring --dry-run lets a caller believe it previewed a
    # destructive step that in fact ran.
    repo, _code, dev_before, _out = staged
    assert main(["--root", str(repo), "--commit-staged", "--dry-run"]) == \
        EXIT_PRECONDITION
    assert _git(repo, "rev-parse", "dev") == dev_before
    assert read_staged_state(repo) is not None


# -- the record names a COMMIT, not a moving branch pointer -------------------


def test_abort_staged_still_works_after_the_branch_advances(staged):
    """The red-prep recovery path: fixing the failure means committing on the
    feature branch, so the branch legitimately moves while the merge sits staged.
    Identity must be against the merged commit, not against whatever the branch
    name resolves to now, or this refuses the operator's own escape hatch.
    """
    repo, _code, dev_before, _out = staged
    wt = repo.parent / "advance-wt"
    _git(repo, "worktree", "add", str(wt), "feature/my-plan")
    _commit(wt, "app/fix.py", "fixed = True\n", "fix what prep caught")
    assert _head(repo) != read_staged_state(repo)["merged_sha"], "branch moved"

    assert main(["--root", str(repo), "--abort-staged"]) == EXIT_OK
    assert _git(repo, "rev-parse", "dev") == dev_before
    assert read_staged_state(repo) is None


def test_commit_staged_still_works_after_the_branch_advances(staged):
    repo, _code, _dev_before, _out = staged
    wt = repo.parent / "advance-wt2"
    _git(repo, "worktree", "add", str(wt), "feature/my-plan")
    _commit(wt, "app/fix.py", "fixed = True\n", "fix what prep caught")

    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_OK
    # The merge that landed is the one that was staged, not the branch's new tip.
    assert len(_git(repo, "rev-list", "--parents", "-1", "dev").split()) == 3


def test_abort_staged_refuses_a_foreign_merge_when_the_branch_is_gone(staged):
    """NEW-3: skipping the identity check when the recorded branch no longer
    resolves put the data-loss path back one branch-deletion away."""
    repo, _code, _dev_before, _out = staged
    _git(repo, "merge", "--abort")
    foreign = _stage_a_foreign_merge(repo)
    _git(repo, "branch", "-D", "feature/my-plan")

    assert main(["--root", str(repo), "--abort-staged"]) == EXIT_PRECONDITION
    assert _head(repo, "MERGE_HEAD") == foreign, "destroyed a foreign staged merge"


# -- check_root_ready must not over-reach (NEW-1) or under-test (NEW-5) -------


def test_fast_forward_is_unaffected_by_a_stray_file_in_root(repo, tmp_path):
    """A fast-forward creates no commit and never reaches commit_staged, so there
    is nothing for `git add -A` to sweep. Refusing here would break the documented
    "the fast-forward path is unchanged" contract."""
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    head = _head(repo)
    _split_topology(repo, tmp_path)
    (repo / ".env.local").write_text("SECRET=hunter2\n", encoding="utf-8")

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(touched),
                 "--expect-head", head, "--target", "dev"])

    assert code == EXIT_OK
    assert _git(repo, "rev-parse", "dev") == head
    assert (repo / ".env.local").exists()


def test_dry_run_refuses_rather_than_reset_hard_over_uncommitted_work(repo, tmp_path):
    """--dry-run "merges nothing", but a non-ff run still PROBES with a real
    `git merge` that ends in `git reset --hard` — which cannot tell the operator's
    uncommitted edits from merge residue. Keying the clean-tree arm on `dry_run`
    let the preview destroy tracked work in the integration checkout.

    An *untracked* file survives `reset --hard`, so a test that plants one passes
    whether or not the hole is open. This plants a modified tracked file.
    """
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    _diverge(repo)
    head = _head(repo)
    _split_topology(repo, tmp_path)
    precious = repo / "README"
    precious.write_text("hi\nPRECIOUS UNCOMMITTED WORK\n", encoding="utf-8")

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(touched),
                 "--expect-head", head, "--target", "dev", "--dry-run"])

    assert code == EXIT_PRECONDITION
    assert "PRECIOUS" in precious.read_text(encoding="utf-8"), (
        "the conflict probe's reset --hard destroyed uncommitted work during a "
        "run documented as merging nothing"
    )


def test_fast_forward_dry_run_still_previews_with_a_stray_file(repo, tmp_path):
    """The ff path runs no probe and creates no commit, so it stays permissive —
    this is what keeps /work's documented preview usable."""
    touched = tmp_path / "touched.txt"
    touched.write_text("app/\n", encoding="utf-8")
    head = _head(repo)
    _split_topology(repo, tmp_path)
    (repo / ".env.local").write_text("SECRET=hunter2\n", encoding="utf-8")

    code = main(["--root", str(repo), "--slug", "my-plan", "--touched", str(touched),
                 "--expect-head", head, "--target", "dev", "--dry-run"])

    assert code == EXIT_OK, "the documented preview step must still run"
    assert read_staged_state(repo) is None
    assert (repo / ".env.local").exists()


def test_unusable_record_with_a_live_merge_names_the_merge(staged, capsys):
    """NEW-4 had no coverage: collapsing back to "no staged merge recorded" left
    the operator mid-merge with no route out and no mention of it."""
    repo, _code, _dev_before, _out = staged
    state_path = repo / ".git" / "merge-feature-staged.json"
    state_path.write_text(json.dumps({"branch": "feature/my-plan", "target": "dev"}),
                          encoding="utf-8")   # merged_sha stripped

    assert main(["--root", str(repo), "--commit-staged"]) == EXIT_PRECONDITION
    err = capsys.readouterr().err
    assert "in progress" in err and "git merge --abort" in err, err


def test_root_mid_merge_is_refused_for_being_mid_merge_not_merely_dirty(repo, tmp_path):
    """NEW-5: a staged merge also makes the root dirty, so asserting only on the
    exit code let this guard pass for the wrong reason. Pin the reason."""
    import merge_feature as mf

    _diverge(repo)
    _split_topology(repo, tmp_path)
    _stage_a_foreign_merge(repo)

    verdict = mf.check_root_ready(repo, "dev", ff=False)
    assert verdict is not None and verdict.reason == "root-mid-merge"


def test_root_with_an_unfinished_record_is_refused(repo, tmp_path):
    """NEW-5: the staged-record arm had no coverage at all."""
    import merge_feature as mf

    _diverge(repo)
    _split_topology(repo, tmp_path)
    assert mf.land(repo, "feature/my-plan", "dev") == mf.STAGED
    _git(repo, "merge", "--abort")          # record survives, tree is clean again

    verdict = mf.check_root_ready(repo, "dev", ff=False)
    assert verdict is not None and verdict.reason == "root-has-staged-state"
