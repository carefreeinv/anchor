"""A skill that mutates tracked files must say who commits.

`/review` shipped for months creating merge commits and staging plan-lane renames
without ever naming `/commit-prep` — invisible in this repo, because it gitignores
its whole `.plans/` tree, and painful in scaffolded projects, which track it. This
test is the reason that cannot come back quietly.

The rule it enforces is the one in `CLAUDE.md`: prep before any commit that
touches a path outside `.plans/`, and before any merge commit; a plans-only commit
takes the light path. A skill that runs git commands which *create commits* must
therefore reference `commit-prep`, or be on the exemption list below with a stated
reason.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILL_GLOBS = (".claude/commands/*.md", ".grok/skills/*/SKILL.md")

# How close a `/commit-prep` reference must sit to a mutating command.
PROXIMITY = 25

# Commands that create a commit or stage a tracked change, including the
# `git -C <path>` / `git -c k=v` forms and `gh pr merge` (which lands a merge
# commit on the remote). Reads (`git checkout`, `git status`, `git log`) do not
# qualify — and neither does `git push`, which only publishes commits that were
# already gated when they were made. `git mv` is here because it stages, not
# because it commits.
MUTATING = re.compile(
    r"git\s+(?:-[Cc]\s+\S+\s+)*(commit|merge|mv|cherry-pick|revert|rebase)\b"
    r"|gh\s+pr\s+merge\b"
)

# Skills that legitimately name a mutating command without owing a prep reference.
EXEMPT = {
    # commit-prep IS the gate; it documents what it does not do.
    "commit-prep": "is the gate itself",
}


def _skills() -> list[Path]:
    found: list[Path] = []
    for pattern in SKILL_GLOBS:
        found.extend(sorted(REPO.glob(pattern)))
    return found


def test_every_exemption_names_a_real_skill():
    # An EXEMPT entry that matches nothing is inert config that reads as coverage.
    names = {p.stem if p.stem != "SKILL" else p.parent.name for p in _skills()}
    dead = sorted(set(EXEMPT) - names)
    assert not dead, f"EXEMPT names no discovered skill: {dead}"


def test_skills_were_discovered():
    # A glob that silently matches nothing would make every assertion below vacuous.
    skills = _skills()
    assert len(skills) >= 10, [str(p) for p in skills]


@pytest.mark.parametrize("path", _skills(), ids=lambda p: p.parent.name + "/" + p.name)
def test_mutating_skill_names_commit_prep(path: Path):
    name = path.stem if path.stem != "SKILL" else path.parent.name
    if name in EXEMPT:
        pytest.skip(f"{name}: {EXEMPT[name]}")
    text = path.read_text(encoding="utf-8")
    hits = sorted({m.group(0) for m in MUTATING.finditer(text)})
    if not hits:
        return
    # A bare mention anywhere in the file is weak evidence — /deploy passes on four
    # mentions that are all exclusions. Require one within PROXIMITY lines of an
    # actual mutating command, so the reference sits where the obligation applies.
    lines = text.splitlines()
    mutating_lines = [i for i, ln in enumerate(lines) if MUTATING.search(ln)]
    prep_lines = [i for i, ln in enumerate(lines) if "commit-prep" in ln]
    assert prep_lines, (
        f"{path.relative_to(REPO)} runs {hits} but never references `/commit-prep`. "
        f"Either name the prep obligation (see CLAUDE.md's hard rule) or add the "
        f"skill to EXEMPT in this file with a reason."
    )
    near = any(abs(m - pl) <= PROXIMITY for m in mutating_lines for pl in prep_lines)
    assert near, (
        f"{path.relative_to(REPO)} mentions `/commit-prep`, but never within "
        f"{PROXIMITY} lines of {hits} — the reference does not sit where the "
        f"obligation applies. State the obligation at the command, not elsewhere."
    )


@pytest.mark.parametrize("path", _skills(), ids=lambda p: p.parent.name + "/" + p.name)
def test_no_skill_creates_a_merge_commit_without_gating_it(path: Path):
    # `git merge --no-ff` creates a commit. The hard rule gates it *before* it
    # exists, which in practice means --no-commit, prep, then commit.
    text = path.read_text(encoding="utf-8")
    if "--no-ff" not in text:
        return
    assert "--no-commit" in text, (
        f"{path.relative_to(REPO)} uses `git merge --no-ff`, which creates a commit, "
        f"without the `--no-commit` staging step that lets /commit-prep gate it "
        f"before it exists."
    )
