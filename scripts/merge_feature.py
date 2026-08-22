#!/usr/bin/env python3
"""Land a finished ``feature/<slug>`` on the integration branch — but only when a
mechanical gate proves the branch is exactly what the caller thinks it is.

This is the machinery behind ``/work``'s end-of-run **"merge to dev now"** answer.
The normal path remains ``/review``: an AI critic plus a human survey. This path
trades the critic for a much narrower mandate — the operator watched the work
happen, so the gate's job is to prove nothing *else* rode along:

1. **Provenance** — the branch head is the commit the caller just made.
2. **Clean tree** — nothing staged, unstaged, or untracked.
3. **File scope** — every path named **anywhere in the range history**
   (``base..head``, not just the net tree-to-tree diff) is inside the caller's
   declared touched set (evaluated with ``scope_gate.check_scope``, one glob
   implementation). A path added and then deleted still counts — net two-dot
   ``git diff`` cannot see it, but the blob would still land in history.
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
violation, 4 precondition failed, 5 merge conflict, 6 merge staged (not committed;
run --commit-staged or --abort-staged after /commit-prep).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scope_gate import check_scope, clean_entry

EXIT_OK = 0
EXIT_GIT = 2
EXIT_SCOPE = 3
EXIT_PRECONDITION = 4
EXIT_CONFLICT = 5
# A non-ff merge is staged, not committed: /commit-prep owes a pass over the merged
# tree before it becomes a commit. Deliberately NOT 0 — a caller that treats this
# as success reports a merge that did not happen.
EXIT_STAGED = 6

INTEGRATION_ORDER = ("dev", "develop")
MAINLINE = ("main", "master")


class GitError(RuntimeError):
    """git itself failed (not a repo, command error) — distinct from a refusal."""


class StagedMergeInvalid(GitError):
    """The recorded staged-merge state no longer matches reality.

    A stale state file (operator hand-aborted the merge, an interrupted run, a
    second invocation) must not make ``commit_staged`` ``git add -A`` whatever
    happens to be lying around and commit it as though it were the recorded merge.
    """


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
    work_root: str = "",
    changed: tuple[str, ...],
    touched: tuple[str, ...],
    conflicts: tuple[str, ...] = (),
    ff_possible: bool = True,
    target_worktree: str | None = None,
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
    if target not in INTEGRATION_ORDER:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="target-not-integration",
            message=(
                f"refuse: '{target}' is not an integration branch. This path lands on "
                f"{' or '.join(INTEGRATION_ORDER)} only — anything else is a merge the "
                f"operator did not authorize by answering /work's question."
            ),
        )
    if not expect_head:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="provenance-missing",
            message=(
                "refuse: --expect-head is required. Provenance is a must-hold condition, "
                "not an optional extra: without the SHA this run committed there is no "
                "way to tell the branch has not moved since."
            ),
        )
    if head != expect_head:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="provenance",
            message=(
                f"refuse: {branch} is at {head[:12]}, not the commit this run made "
                f"({expect_head[:12]}). Something else moved the branch — that is exactly "
                f"when a human review is warranted."
            ),
        )
    if dirty:
        where = f" in {work_root}" if work_root else ""
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="dirty-tree",
            message=f"refuse: {len(dirty)} uncommitted path(s){where}.",
            offending=dirty,
        )

    # check_scope treats an empty scope as "gate inactive" — correct for its own
    # CLI (specs predating ## Files in scope), wrong here: /work always has a
    # touched set, so an empty one means the caller lost it. Refuse rather than
    # silently pass every path.
    if not [entry for entry in touched if entry.strip()]:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="no-touched-set",
            message=(
                "refuse: the touched set is empty, so there is nothing to check the "
                "branch against. An empty set disables the scope check instead of "
                "satisfying it — pass the paths this run declared it touched."
            ),
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
    # Placed after the content checks on purpose: "your branch carries a file you
    # never declared" is worth learning before "run this somewhere else", and in
    # Anchor's own topology this condition is otherwise always the first refusal.
    if target_worktree:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="target-checked-out-elsewhere",
            message=(
                f"refuse: '{target}' is checked out at {target_worktree}, so the merge "
                f"cannot run here. Re-run with --root {target_worktree} (or "
                f"`git worktree prune` if that path no longer exists)."
            ),
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

    An explicit ``--target`` is *resolved through git* (``rev-parse
    --abbrev-ref``) before it is trusted, so a ref spelling like
    ``refs/heads/main`` cannot slip past a name comparison against ``MAINLINE``.
    Whether the resolved name is actually allowed is :func:`evaluate_gate`'s
    call, not this function's.

    Never creates a branch: creation belongs to ``worktree_for_agent.py`` at claim
    time, and a merge path that invents its own target is a merge path that can
    surprise you about where the code went.
    """
    if explicit:
        p = _git(root, "rev-parse", "--abbrev-ref", explicit, check=False)
        resolved = p.stdout.strip() if p.returncode == 0 else ""
        return resolved or explicit
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
    """Union of every path named on any commit in ``base..head``.

    **Not** a net tree-to-tree ``git diff base..head --name-only``: that view is
    blind to a path that is added *and* deleted within the range, so a branch
    could smuggle a blob into the merge target's history without the scope check
    ever naming the path. ``git log --name-only --pretty=format:`` is the
    per-commit union that closes that hole.

    ``--no-renames`` is also load-bearing: with rename detection on,
    ``git mv secrets/creds.yml app/creds.yml`` reports only the destination, so a
    branch can delete a file from an undeclared directory and pass a scope check
    that never sees the path it removed. With ``--no-renames``, both sides appear.

    Paths are de-duplicated while preserving first-seen order.
    """
    out = _git(
        root,
        "log",
        "--name-only",
        "--pretty=format:",
        "--no-renames",
        f"{base}..{head}",
    ).stdout
    seen: set[str] = set()
    paths: list[str] = []
    for line in out.splitlines():
        p = line.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        paths.append(p)
    return tuple(paths)

def worktree_for_branch(root: Path, branch: str) -> str | None:
    """Path of the worktree that has ``branch`` checked out, if any.

    One lookup serving two questions the gate has to answer separately: *where is
    the work* (the feature branch's tree, which is what "clean tree" must mean) and
    *is the target blocked* (git refuses to check out a branch live in a second
    worktree). Answering both from ``--root`` was the bug: on the topology this tool
    itself recommends, they are different directories.
    """
    try:
        text = _git(root, "worktree", "list", "--porcelain").stdout
    except GitError:
        return None
    path = ""
    for line in text.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            if line[len("branch "):].strip().removeprefix("refs/heads/") == branch:
                return path
    return None


def toplevel(root: Path) -> Path:
    """The worktree root containing ``root``.

    Every other call goes through ``git -C``, which works from any subdirectory;
    comparing a raw ``--root`` against worktree paths does not, and false-refused
    whenever an operator passed a subdirectory.
    """
    out = _git(root, "rev-parse", "--show-toplevel", check=False).stdout.strip()
    return Path(out) if out else root.resolve()


def target_worktree(root: Path, target: str) -> str | None:
    """Another worktree holding ``target`` — i.e. one that is not where we are."""
    path = worktree_for_branch(root, target)
    if path is None:
        return None
    try:
        return None if Path(path).resolve() == toplevel(root).resolve() else path
    except OSError:
        return path


def merge_base(root: Path, a: str, b: str) -> str:
    return _git(root, "merge-base", a, b).stdout.strip()


def is_ancestor(root: Path, maybe_ancestor: str, ref: str) -> bool:
    return _git(root, "merge-base", "--is-ancestor", maybe_ancestor, ref,
                check=False).returncode == 0


def _restore_point(root: Path) -> str:
    """What to check out again afterwards — a branch name, or a SHA if detached.

    ``rev-parse --abbrev-ref HEAD`` answers the literal string ``HEAD`` on a
    detached head, and checking *that* out would strand the tree at the target's
    tip instead of where it started.
    """
    name = current_branch(root)
    return head_sha(root, "HEAD") if name == "HEAD" else name


def probe_conflicts(root: Path, target: str, branch: str) -> tuple[str, ...]:
    """Conflicting paths for a non-fast-forward merge, leaving the tree as found.

    Uses the real merge machinery (``--no-commit --no-ff`` then ``--abort``) rather
    than a prediction: this git is older than ``merge-tree --write-tree``, and a
    wrong guess here would either block a clean merge or promise one that fails
    halfway. Always restores the original branch.
    """
    original = _restore_point(root)
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


STAGED = "STAGED"


def land(root: Path, branch: str, target: str, *, title: str = "") -> str:
    """Merge ``branch`` into ``target``; return the target's new HEAD, or ``STAGED``.

    Mirrors /review §11's semantics exactly so the two authorization paths cannot
    drift into different merge behavior — including the prep obligation:

    * **Fast-forward** creates no commit and cannot conflict, so its content is the
      branch tip that was already prepped. It lands here and returns the new HEAD.
    * **Non-fast-forward creates a merge commit**, and the merged tree is state
      neither branch was prepped in. This function will not commit it. It leaves the
      merge **staged** (``--no-commit``) and returns :data:`STAGED`; the caller runs
      ``/commit-prep`` against the merged tree and then calls :func:`commit_staged`
      or :func:`abort_staged`. Prep is a skill, so only a caller can run it — this
      module stays git plumbing.

    The target branch is left checked out when a merge is staged, because an
    unfinished merge cannot survive a checkout. Never pushes.
    """
    original = _restore_point(root)
    restore = True
    try:
        _git(root, "checkout", target)
        if _git(root, "merge", "--ff-only", branch, check=False).returncode == 0:
            return head_sha(root, "HEAD")
        p = _git(root, "merge", "--no-ff", "--no-commit", branch, check=False)
        if p.returncode != 0:
            _git(root, "merge", "--abort", check=False)
            raise GitError(f"merge conflicted: {p.stdout.strip()} {p.stderr.strip()}")
        restore = False  # a staged merge must stay on the target branch
        # Record the SHA actually merged, not just the branch name. A name is a
        # mutable pointer: the branch legitimately advances when a red prep is
        # fixed with a commit on it, and comparing against the name then reads a
        # moved branch as "a different merge" and refuses the operator's own
        # escape hatch.
        _write_staged_state(root, branch, target, original, title,
                            merge_head(root))
        return STAGED
    finally:
        if restore:
            _git(root, "checkout", original, check=False)


STAGED_STATE = "merge-feature-staged.json"


def _git_dir(root: Path) -> Path:
    """The real git directory for ``root``, resolving linked-worktree indirection.

    In a linked worktree ``<root>/.git`` is a **file** pointing elsewhere, not a
    directory — ``root / ".git" / STAGED_STATE`` raises ``NotADirectoryError``
    there, which is exactly the topology ``/work`` recommends
    (``var/worktrees/<agent-id>/``). ``--absolute-git-dir`` resolves correctly for
    both a plain repo and a linked worktree, and gives each worktree its own state
    file, which is right: a staged merge is specific to the tree that staged it.
    """
    return Path(_git(root, "rev-parse", "--absolute-git-dir").stdout.strip())


def _state_path(root: Path) -> Path:
    return _git_dir(root) / STAGED_STATE


def _write_staged_state(root: Path, branch: str, target: str, original: str,
                        title: str, merged_sha: str) -> None:
    """Record what a staged merge needs in order to be finished.

    `land()` computes the restore point internally, so without this a second CLI
    invocation could not know which branch to return to — and would silently leave
    the tree parked on the integration branch.

    ``merged_sha`` is the commit that was actually merged. The finishers compare
    ``MERGE_HEAD`` against **it**, never against what ``branch`` resolves to now:
    the branch is expected to move (fixing a red prep means committing on it), and
    an identity check against a moving pointer refuses the very recovery path it
    was added to protect.
    """
    import json

    _state_path(root).write_text(json.dumps(
        {"branch": branch, "target": target, "original": original, "title": title,
         "merged_sha": merged_sha}
    ), encoding="utf-8")


def read_staged_state(root: Path) -> dict | None:
    """The pending staged merge for this repo, or None.

    A record that is unreadable, not an object, or missing the fields the
    finishers index is treated as **no usable record** rather than returned
    half-formed: ``state["branch"]`` on a malformed file would raise ``KeyError``
    and surface as a traceback and exit 1, outside the documented exit set. The
    caller reports "no staged merge recorded", and ``merge_head`` is what tells
    the operator whether a real merge is nonetheless sitting in the tree.
    """
    import json

    path = _state_path(root)
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or not all(
            isinstance(state.get(k), str) and state.get(k)
            for k in ("branch", "target", "merged_sha")):
        return None
    return state


def clear_staged_state(root: Path) -> None:
    _state_path(root).unlink(missing_ok=True)


def check_root_ready(root: Path, target: str, *, ff: bool,
                     dry_run: bool) -> MergeVerdict | None:
    """Refuse when ``--root`` is not a fit place to stage a merge. None means OK.

    Separate from :func:`evaluate_gate`'s ``dirty`` check, which follows the
    *feature branch's* worktree — the tree that did the work — and so says nothing
    about the checkout the merge actually lands in.
    """
    if merge_head(root):
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="root-mid-merge",
            message=(
                f"refuse: {root} already has a merge in progress. Finishing this run "
                f"would destroy it — the conflict probe aborts whatever merge it "
                f"finds. Resolve that merge first (--commit-staged / --abort-staged, "
                f"or git merge --abort)."
            ),
        )
    if read_staged_state(root) is not None:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="root-has-staged-state",
            message=(
                f"refuse: {root} has an unfinished staged merge on record. Finish it "
                f"(--commit-staged after a green /commit-prep, or --abort-staged) "
                f"before staging another."
            ),
        )
    # Untracked files here would be swept into the merge commit by commit_staged's
    # `git add -A`, which exists to capture /commit-prep's own output and cannot
    # tell that apart from whatever was already lying around.
    #
    # Only the staging path can do that. A fast-forward creates no commit and never
    # reaches commit_staged, and --dry-run merges nothing at all — refusing either
    # because the integration checkout has a scratch file would break /work's
    # documented preview step and contradict "the fast-forward path is unchanged".
    # The two arms above still apply everywhere: an in-progress merge or an
    # unfinished record means this checkout is mid-operation however we got here.
    if ff or dry_run:
        return None
    stray = dirty_paths(root)
    if stray:
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="root-not-clean",
            message=(
                f"refuse: {root} has {len(stray)} uncommitted path(s), and it is the "
                f"checkout '{target}' is merged into. Anything here is swept into the "
                f"merge commit when the staged merge is committed — commit, stash or "
                f"remove them first."
            ),
            offending=stray,
        )
    return None


def merge_head(root: Path) -> str:
    """The commit being merged in, or "" when no merge is in progress."""
    p = _git(root, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def _verify_staged_merge(root: Path, branch: str, target: str,
                         merged_sha: str) -> None:
    """Refuse to touch a merge that is not actually what the state file claims.

    Three distinct ways the record and reality part company, all reproduced:

    * **No ``MERGE_HEAD``.** A stale or hand-aborted state would have
      ``commit_staged`` ``git add -A`` and commit whatever is lying around
      (scratch files, an unrelated edit) as a **single-parent** commit reported
      as a merge that never happened.
    * **Wrong target.** A stale state left after the operator switched branches
      would commit onto whatever HEAD is now, not the recorded target.
    * **Wrong merge.** ``MERGE_HEAD`` existing is not the same as it being *our*
      merge. A stale record plus any other staged merge on the same target —
      an operator's hand-run ``git merge --no-ff --no-commit``, or another
      agent's — would otherwise be committed under this plan's name, having
      passed none of the scope, provenance or ``--expect-head`` checks. That is
      exactly the "reports a merge it did not make" class :data:`EXIT_STAGED`
      exists to prevent, so identity is checked, not just presence.
    """
    staged = merge_head(root)
    if not staged:
        raise StagedMergeInvalid(
            "no merge in progress (MERGE_HEAD missing) — the staged-merge state is "
            "stale; run --abort-staged to clear it, or resolve manually"
        )
    current = current_branch(root)
    if current != target:
        raise StagedMergeInvalid(
            f"HEAD is on {current!r}, not the recorded target {target!r} — refusing "
            f"to commit onto the wrong branch; run --abort-staged to clear the stale "
            f"state, or checkout {target!r} first"
        )
    if staged != merged_sha:
        raise StagedMergeInvalid(
            f"the staged merge is of {staged[:12]}, not the recorded {merged_sha[:12]} "
            f"from {branch!r} — this is a different merge than the one recorded, and it "
            f"has passed none of this tool's checks. Resolve it yourself "
            f"(git commit / git merge --abort), then re-run the merge."
        )


def commit_staged(root: Path, branch: str, target: str, merged_sha: str, *,
                  title: str = "", original: str = "") -> str:
    """Commit a merge staged by :func:`land`, after ``/commit-prep`` came back green.

    Stages **everything** first: prep edits the *working tree* (CHANGELOG entry, test
    fixes, a new blog file), and a bare ``git commit`` during a merge commits only
    the index — silently dropping prep's own output from the merge commit and
    leaving it dirty in the tree.
    """
    _verify_staged_merge(root, branch, target, merged_sha)
    try:
        msg = f"Merge {branch}" + (f": {title}" if title else "")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", msg)
        sha = head_sha(root, "HEAD")
        clear_staged_state(root)
        return sha
    finally:
        if original:
            _git(root, "checkout", original, check=False)


ABORTED = "aborted"
CLEARED = "cleared"


def abort_staged(root: Path, branch: str, target: str, merged_sha: str, *,
                 original: str = "") -> str:
    """Undo a merge staged by :func:`land`, after ``/commit-prep`` came back red.

    ``git merge --abort`` **refuses** when a file involved in the merge has unstaged
    modifications — which is exactly what prep's fix-the-tests gate produces — so
    fall back to a hard reset. Either way nothing was committed, and prep's *tracked*
    edits are discarded along with the merge — but ``reset --hard`` does not remove
    **untracked** files, so a blog post or other new file prep created survives on
    disk (``?? path`` in ``git status``) even though the merge did not land.

    That reset is destructive, so it only ever runs against a merge that is
    genuinely in progress on the recorded target:

    * **No ``MERGE_HEAD``** — the operator aborted by hand, or an earlier run already
      finished. There is nothing to undo, so the stale record is cleared and **no
      tree is touched**; resetting here would destroy whatever unrelated work the
      operator has since put in the tree. Returns :data:`CLEARED`.
    * **A merge in progress on a different branch than recorded, or of a different
      commit than recorded** — refuse. Aborting a merge this state file does not
      describe throws away someone else's staged work: the record existing is not
      evidence that the merge in front of us is ours.
    * Otherwise the real abort runs, and returns :data:`ABORTED`.
    """
    staged = merge_head(root)
    if not staged:
        # Clearing the record is safe and is the operator's escape hatch out of a
        # stale state file — which is exactly what commit_staged's refusal tells
        # them to run. A reset on this path would be destroying, not undoing.
        clear_staged_state(root)
        return CLEARED
    current = current_branch(root)
    if current != target:
        raise StagedMergeInvalid(
            f"a merge is in progress on {current!r}, not the recorded target "
            f"{target!r} — refusing to reset a tree this staged-merge record "
            f"does not describe; resolve that merge where it is"
        )
    if staged != merged_sha:
        raise StagedMergeInvalid(
            f"the staged merge is of {staged[:12]}, not the recorded {merged_sha[:12]} "
            f"from {branch!r} — aborting it would throw away a merge this record does "
            f"not describe. Resolve that merge where it is."
        )
    if _git(root, "merge", "--abort", check=False).returncode != 0:
        _git(root, "reset", "--hard", "HEAD", check=False)
    clear_staged_state(root)
    if original:
        _git(root, "checkout", original, check=False)
    return ABORTED


def read_touched(source: str) -> tuple[str, ...]:
    """One path or glob per line, from a file or stdin (``-``)."""
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        # scope_gate.clean_entry strips exactly one leading bullet plus backticks
        # and trailing notes. Reused rather than re-derived: a naive lstrip("-* ")
        # eats the leading glob of "*.md" and "**/tests/*.py".
        entry = clean_entry(line)
        if entry:
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
    if target and resolved not in local_branches(root):
        return MergeVerdict(
            ok=False, code=EXIT_PRECONDITION, reason="no-such-target",
            message=f"refuse: --target '{target}' does not name a local branch.",
        ), None
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
    if expect_head:
        # Resolve before comparing: an abbreviated SHA otherwise fails closed with a
        # message that truncates both sides to the same 12 characters and reads as a
        # contradiction ("is at X, not the commit this run made (X)").
        p = _git(root, "rev-parse", expect_head, check=False)
        if p.returncode == 0:
            expect_head = p.stdout.strip()
    natural_base = merge_base(root, resolved, branch)
    if base:
        # A caller-supplied base narrows the diff the scope check sees, so an
        # unvalidated one is a way to make that check vacuous — `--base <head>`
        # yields an empty change set and everything "passes". It must be an
        # ancestor of the branch head *and* no newer than the real merge-base.
        # natural_base is by definition an ancestor of head, so this single check
        # implies the head-side one too.
        if not is_ancestor(root, base, natural_base):
            return MergeVerdict(
                ok=False, code=EXIT_PRECONDITION, reason="bad-base",
                message=(
                    f"refuse: --base {base[:12]} is not an ancestor of both {branch} and "
                    f"the merge-base with {resolved} ({natural_base[:12]}). A base inside "
                    f"the range hides the commits before it from the scope check."
                ),
            ), None
    merge_from = base or natural_base
    ff = is_ancestor(root, resolved, branch)
    # Clean-tree means the tree that did the work, which on the topology this tool
    # recommends (--root = the integration checkout) is a different directory.
    work_root = worktree_for_branch(root, branch) or str(toplevel(root))
    dirty = dirty_paths(Path(work_root))
    changed = changed_files(root, merge_from, head)
    blocking_worktree = target_worktree(root, resolved)

    # The dirty check above deliberately follows the *feature branch's* worktree.
    # `--root` itself still has to be fit to merge into, and nothing checked that:
    #
    #  * A merge already staged here would be destroyed by `probe_conflicts`, whose
    #    `git merge --abort` does not know it is unwinding someone else's work. Both
    #    skills tell every agent to point `--root` at the same shared checkout, so
    #    two agents landing near-simultaneously is the ordinary fleet case.
    #  * Untracked files sitting here before the merge get swept into the merge
    #    commit by `commit_staged`'s `git add -A` — a stray `.env.local` or build
    #    output landing on the integration branch. /review warns humans about
    #    exactly this; the tool that automates the step must not be blind to it.
    # A conflict probe checks out branches; refuse first on anything cheaper so a
    # dirty tree is never disturbed by a probe it was going to fail anyway.
    verdict = evaluate_gate(
        slug=slug, branch=branch, target=resolved, head=head, expect_head=expect_head,
        dirty=dirty, changed=changed, touched=touched, ff_possible=ff,
        target_worktree=blocking_worktree, work_root=work_root,
    )
    if not verdict.ok:
        return verdict, None

    # Runs after the gate above so the more specific refusals (provenance, scope,
    # the feature worktree being dirty) keep their reasons, and before the probe,
    # which is the thing that would do damage.
    root_verdict = check_root_ready(root, resolved, ff=ff, dry_run=dry_run)
    if root_verdict is not None:
        return root_verdict, None

    conflicts = () if ff else probe_conflicts(root, resolved, branch)
    verdict = evaluate_gate(
        slug=slug, branch=branch, target=resolved, head=head, expect_head=expect_head,
        dirty=dirty, changed=changed, touched=touched, conflicts=conflicts, ff_possible=ff,
        target_worktree=blocking_worktree, work_root=work_root,
    )
    if not verdict.ok or dry_run:
        return verdict, None
    return verdict, land(root, branch, resolved, title=title)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Gate and land feature/<slug> on the integration branch (never mainline).",
    )
    ap.add_argument("--root", default=".", help="repo or worktree root (default: cwd)")
    ap.add_argument("--slug", help="plan slug; branch is feature/<slug> "
                    "(not needed with --commit-staged/--abort-staged)")
    ap.add_argument("--branch", help="override the branch name (default: feature/<slug>)")
    ap.add_argument("--touched",
                    help="file with one touched path/glob per line, or '-' for stdin")
    ap.add_argument("--base", help="merge-base recorded at claim time (default: computed)")
    ap.add_argument("--expect-head",
                    help="SHA this run committed; refuses if the branch moved since")
    ap.add_argument("--target", help="integration branch (default: dev, else develop)")
    ap.add_argument("--title", default="", help="plan title for the merge commit message")
    ap.add_argument("--commit-staged", action="store_true",
                    help="finish a merge left STAGED by an earlier run, after "
                         "/commit-prep came back GREEN on the merged tree")
    ap.add_argument("--abort-staged", action="store_true",
                    help="undo a merge left STAGED by an earlier run, after "
                         "/commit-prep came back RED (prep's edits go with it)")
    ap.add_argument("--dry-run", action="store_true",
                    help="evaluate the gate and report; merge nothing")
    args = ap.parse_args(argv)
    root = Path(args.root)

    if args.commit_staged and args.abort_staged:
        # Silently running the commit path when both were passed is the worst of
        # the three options: it picks the destructive-if-wrong one on an operator
        # who plainly did not mean it.
        print("merge-feature: --commit-staged and --abort-staged are mutually "
              "exclusive; pass exactly one.", file=sys.stderr)
        return EXIT_PRECONDITION

    if args.commit_staged or args.abort_staged:
        if args.dry_run:
            # Neither finisher has a dry run, and silently ignoring the flag would
            # let a caller believe it had previewed a destructive step.
            print("merge-feature: --dry-run is not supported with "
                  "--commit-staged/--abort-staged; they finish a merge that is "
                  "already staged.", file=sys.stderr)
            return EXIT_PRECONDITION
        try:
            # Inside the try: reading the state resolves the repo's real git dir,
            # so a --root that is not a git repo raises GitError here rather than
            # reaching the caller as a traceback and exit 1, outside the
            # documented exit-code set.
            state = read_staged_state(root)
            if state is None:
                # An unusable record and a merge sitting in the tree is the one
                # combination where "no staged merge recorded" is actively
                # misleading: the operator is mid-merge with no route out of it
                # through this tool, and must be told so rather than left to
                # rediscover it from a later refusal.
                staged = merge_head(root)
                if staged:
                    print(
                        f"merge-feature: a merge of {staged[:12]} is in progress in "
                        f"{root}, but its staged-merge record is missing or unusable, "
                        f"so this tool cannot finish it. Resolve it directly — "
                        f"`git commit` to keep it, or `git merge --abort` to drop it — "
                        f"then re-run the merge.", file=sys.stderr)
                else:
                    print("merge-feature: no staged merge recorded for this repo.",
                          file=sys.stderr)
                return EXIT_PRECONDITION
            if args.commit_staged:
                sha = commit_staged(root, state["branch"], state["target"],
                                    state["merged_sha"],
                                    title=state.get("title", ""),
                                    original=state.get("original", ""))
                print(f"merged; {state['target']} is now {sha[:12]}.")
            elif abort_staged(root, state["branch"], state["target"],
                              state["merged_sha"],
                              original=state.get("original", "")) == CLEARED:
                print(f"no merge in progress; cleared the stale staged-merge record "
                      f"for {state['target']}. Nothing was reset and no tree was "
                      f"touched.")
            else:
                print(f"aborted; {state['target']} unchanged, nothing committed. "
                      f"/commit-prep's tracked edits were discarded with the merge "
                      f"(untracked files it created, e.g. a new blog post, survive "
                      f"on disk — check `git status`).")
        except StagedMergeInvalid as exc:
            print(f"merge-feature: {exc}", file=sys.stderr)
            return EXIT_PRECONDITION
        except GitError as exc:
            print(f"merge-feature: {exc}", file=sys.stderr)
            return EXIT_GIT
        return EXIT_OK

    missing = [n for n, v in (("--slug", args.slug), ("--touched", args.touched),
                              ("--expect-head", args.expect_head)) if not v]
    if missing:
        # Required for a merge, meaningless for the two finishers above (which
        # return before this). argparse cannot express that, so it lives here.
        print(f"merge-feature: missing required argument(s): {', '.join(missing)}",
              file=sys.stderr)
        return EXIT_PRECONDITION

    try:
        touched = read_touched(args.touched)
    except (OSError, UnicodeDecodeError) as exc:
        # Unreadable or non-text --touched file: the caller's precondition, not
        # git's fault, and exit 1 from a traceback is outside the documented set.
        print(f"merge-feature: cannot read --touched: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION

    try:
        verdict, new_head = run(
            Path(args.root), args.slug, touched,
            base=args.base, expect_head=args.expect_head, target=args.target,
            branch=args.branch, dry_run=args.dry_run, title=args.title,
        )
        landed_on = resolve_target(Path(args.root), args.target)
    except GitError as exc:
        print(f"merge-feature: {exc}", file=sys.stderr)
        return EXIT_GIT

    print(verdict.report())
    if verdict.ok and args.dry_run:
        print("dry run: nothing merged.")
    elif verdict.ok and new_head == STAGED:
        # NOT "merged" and NOT exit 0. The merge is staged and uncommitted; a
        # caller that reads this as success reports a merge that did not happen.
        print(
            f"STAGED: {landed_on} has the merge staged, NOT committed.\n"
            f"  Run /commit-prep against the merged tree, then finish it:\n"
            f"    green -> python scripts/merge_feature.py --root {args.root} --commit-staged\n"
            f"    red   -> python scripts/merge_feature.py --root {args.root} --abort-staged"
        )
        return EXIT_STAGED
    elif verdict.ok:
        print(f"merged; {landed_on} is now {new_head[:12]}.")
    return verdict.code


if __name__ == "__main__":
    sys.exit(main())
