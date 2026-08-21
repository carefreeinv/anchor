"""The light-path commands the skills ship must actually run.

`/review` shipped `git commit -- .plans/ -m "..."` for a while. It is not a typo
git tolerates: everything after `--` is a **pathspec**, so `-m` and the message
became filenames, and the command committed nothing while looking like it worked.
Reading the line did not catch it twice. Running it does.

These tests extract the command from the shipped skill text and execute it against
a throwaway repo, so the assertion is about the documentation, not about a copy of
it maintained here.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Every document that ships the plans-only lane-move commit.
LIGHT_PATH_DOCS = (
    ".claude/commands/review.md",
    ".grok/skills/review/SKILL.md",
)

# The commit line inside a fenced block: `git commit ...` mentioning .plans/
COMMIT_LINE = re.compile(r"^git commit .*\.plans/.*$", re.MULTILINE)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _shipped_commit_commands(rel: str) -> list[str]:
    text = (REPO / rel).read_text(encoding="utf-8")
    return [m.group(0).strip() for m in COMMIT_LINE.finditer(text)]


def _fill_placeholders(command: str) -> list[str]:
    """Turn the documented template into a runnable argv.

    Only the angle-bracket placeholders are substituted; the flags, their order,
    and the pathspec are left exactly as shipped, because those are what is
    under test.
    """
    import shlex

    concrete = (command
                .replace("<slug>", "my-plan")
                .replace("<lane>", "completed")
                .replace("<choice>", "Approve"))
    assert "<" not in concrete, f"unsubstituted placeholder in: {concrete}"
    return shlex.split(concrete)


@pytest.fixture
def plans_repo(git_repo: Path) -> Path:
    """A repo that TRACKS .plans/, the way a scaffolded project does."""
    lane = git_repo / ".plans" / "review-needed"
    lane.mkdir(parents=True)
    (lane / "my-plan.md").write_text("# my plan\n", encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "seed plans")
    return git_repo


@pytest.mark.parametrize("rel", LIGHT_PATH_DOCS)
def test_the_light_path_command_is_present_and_singular(rel: str):
    commands = _shipped_commit_commands(rel)
    assert commands, f"{rel} ships no plans-only commit command to test"


@pytest.mark.parametrize("rel", LIGHT_PATH_DOCS)
def test_shipped_light_path_command_actually_commits(plans_repo: Path, rel: str):
    # Perform the lane move the command is documented to record.
    src = plans_repo / ".plans/review-needed/my-plan.md"
    dst = plans_repo / ".plans/completed/my-plan.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    _git(plans_repo, "mv", str(src.relative_to(plans_repo)),
         str(dst.relative_to(plans_repo)))

    before = _git(plans_repo, "rev-parse", "HEAD").stdout.strip()
    for command in _shipped_commit_commands(rel):
        argv = _fill_placeholders(command)
        assert argv[:2] == ["git", "commit"]
        result = _git(plans_repo, *argv[1:])
        assert result.returncode == 0, (
            f"{rel} ships a command that fails:\n  {command}\n"
            f"  stderr: {result.stderr.strip()}"
        )

    after = _git(plans_repo, "rev-parse", "HEAD").stdout.strip()
    assert after != before, (
        f"{rel}'s light-path command ran successfully but created NO commit. "
        f"This is the `git commit -- <path> -m <msg>` failure mode: everything "
        f"after `--` is a pathspec, so the message flag is swallowed."
    )

    # The lane move is what landed, under the documented message.
    files = _git(plans_repo, "show", "--stat", "--format=", "HEAD").stdout
    assert ".plans/" in files
    subject = _git(plans_repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject.startswith("Plans:"), f"unexpected subject: {subject!r}"


@pytest.mark.parametrize("rel", LIGHT_PATH_DOCS)
def test_shipped_command_leaves_unrelated_staged_work_alone(plans_repo: Path, rel: str):
    # The `-- .plans/` pathspec is the reason this holds; without it the command
    # would sweep an unrelated staged file into an ungated commit.
    src = plans_repo / ".plans/review-needed/my-plan.md"
    dst = plans_repo / ".plans/completed/my-plan.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    _git(plans_repo, "mv", str(src.relative_to(plans_repo)),
         str(dst.relative_to(plans_repo)))

    (plans_repo / "app.py").write_text("import os\n", encoding="utf-8")
    _git(plans_repo, "add", "app.py")

    for command in _shipped_commit_commands(rel):
        _git(plans_repo, *_fill_placeholders(command)[1:])

    committed = _git(plans_repo, "show", "--stat", "--format=", "HEAD").stdout
    assert "app.py" not in committed, (
        f"{rel}'s light-path command swept an unrelated staged file into a "
        f"plans-only commit — the `-- .plans/` pathspec is missing or misplaced."
    )
    assert "app.py" in _git(plans_repo, "diff", "--cached", "--name-only").stdout
