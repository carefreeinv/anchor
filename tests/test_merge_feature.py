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
    mf.abort_staged(repo, original="feature/my-plan")

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
