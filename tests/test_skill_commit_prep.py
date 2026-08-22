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
SKILL_GLOBS = (
    ".claude/commands/*.md",
    ".grok/skills/*/SKILL.md",
    # The per-platform briefs and the docs mirrors state the same rule. They
    # drifted from the skills twice before this test existed, and a stale copy
    # is what a consumer project actually reads.
    "platforms/*/CLAUDE.md",
    "platforms/*/GROK.md",
    "platforms/*/CHAT.md",
    "docs/docs/skills/*.md",
    # The platform mirrors shipped the pre-scoped rule while every other copy
    # had moved on, and nothing read them. The CHANGELOG already claimed this
    # test covered "the platform briefs and the docs mirrors" — it did not.
    "docs/docs/platforms/*.md",
)

# How close a `/commit-prep` reference must sit to a mutating command.
PROXIMITY = 25

# Commands that create a commit or stage a tracked change, including the
# `git -C <path>` / `git -c k=v` forms and `gh pr merge` (which lands a merge
# commit on the remote). Reads (`git checkout`, `git status`, `git log`) do not
# qualify — and neither does `git push`, which only publishes commits that were
# already gated when they were made. `git add` and `git mv` are here because they
# stage, not because they commit.
#
# Not detected: a skill that delegates the commit to a subagent or another tool
# without naming a git command. Nothing textual distinguishes that from prose, so
# it stays a review concern rather than a false sense of coverage here.
MUTATING = re.compile(
    # `-C <path>` / `-c k=v` may repeat and may omit the space after the flag.
    r"git\s+(?:-[Cc]\s*\S+\s+)*(commit|merge|add|mv|cherry-pick|revert|rebase)\b"
    r"|gh\s+pr\s+merge\b"
)

# Forms that match MUTATING but create no commit, so they carry no prep
# obligation: undo paths, and the fast-forward that only moves a ref to content
# which was already prepped on the branch it came from.
NO_COMMIT_CREATED = re.compile(
    r"--abort\b|--ff-only\b|--continue\b|--no-commit\b|merge-base\b"
)

# Shell clause separators (not `||`, which is itself a no-op-on-failure guard,
# not a second command worth splitting into). A compressed one-liner like
# `git merge --no-ff --no-commit X && git add -A && git commit -m "..."` reads
# as one line but is three commands — checking NO_COMMIT_CREATED against the
# whole line would let the guarded first clause hide the unguarded `git commit`
# two clauses later.
CLAUSE_SPLIT = re.compile(r"&&|;|\|(?!\|)")

# The hard rule is scoped by commit *content*: a commit whose paths are entirely
# under `.plans/` takes the light path and owes no prep reference. Lane moves are
# the overwhelming majority of git commands in these documents, and demanding a
# prep reference beside each one would teach exactly the habit the light path
# exists to prevent. Lane directory names count as `.plans/` context because the
# skills routinely write the short form (`review-needed/` → `completed/`).
# A *mention* of a command carries no obligation; an *instruction* does. The
# difference is arguments: "you cannot run `git mv` yourself" and "human pastes /
# runs `git mv`" name the command with nothing to act on, while every command an
# agent actually copies out of these documents has a path or a flag after it.
# This deliberately trades some prose coverage for a signal that is not noise —
# the gap that motivated this test was in a fenced block, which still counts.
MENTION_ONLY = re.compile(
    r"(?:commit|merge|add|mv|cherry-pick|revert|rebase)\s*(?:`|$|[,.)]|\s*/\s*`)"
)

LANES = "drafts|bugs|features|in-progress|review-needed|completed|ambiguous|blocked"
PLANS_ONLY = re.compile(rf"\.plans/|\.leases/|\b(?:{LANES})/")
PLANS_CONTEXT = 2  # lines either side — these sentences wrap

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
    def _is_mention(ln: str) -> bool:
        """True when every mutating hit on the line is argument-less prose.

        Looks just past the end of each match: a closing backtick, end of line,
        or sentence punctuation means the command was named, not given.
        """
        return all(
            MENTION_ONLY.search(ln[m.start():m.end() + 2])
            for m in MUTATING.finditer(ln)
        )

    def _plans_only(i: int) -> bool:
        lo, hi = max(0, i - PLANS_CONTEXT), min(len(lines), i + PLANS_CONTEXT + 1)
        return any(PLANS_ONLY.search(ln) for ln in lines[lo:hi])

    def _creates_commit(ln: str) -> bool:
        """A line creates or stages a commit if any of its clauses do.

        Evaluated per clause (see CLAUSE_SPLIT): a guarded `--no-commit` merge
        earlier in a compressed one-liner must not exempt an unguarded `git
        commit` later in the same line.
        """
        return any(
            MUTATING.search(c) and not NO_COMMIT_CREATED.search(c)
            and not _is_mention(c)
            for c in CLAUSE_SPLIT.split(ln)
        )

    mutating_lines = [
        i for i, ln in enumerate(lines)
        if _creates_commit(ln)
        and not _plans_only(i)
    ]
    if not mutating_lines:
        return
    prep_lines = [i for i, ln in enumerate(lines) if "commit-prep" in ln]
    assert prep_lines, (
        f"{path.relative_to(REPO)} runs {hits} but never references `/commit-prep`. "
        f"Either name the prep obligation (see CLAUDE.md's hard rule) or add the "
        f"skill to EXEMPT in this file with a reason."
    )
    # Per command, not per file. A single reference next to the first commit used
    # to satisfy the whole document, leaving every later commit-creating command
    # unguarded — which is exactly how the merge path shipped ungated.
    orphans = [
        (m + 1, lines[m].strip())
        for m in mutating_lines
        if not any(abs(m - pl) <= PROXIMITY for pl in prep_lines)
    ]
    assert not orphans, (
        f"{path.relative_to(REPO)}: {len(orphans)} commit-creating command(s) sit "
        f"more than {PROXIMITY} lines from any `/commit-prep` reference — the "
        f"obligation is not stated where it applies:\n"
        + "\n".join(f"  line {n}: {t}" for n, t in orphans[:8])
    )


MERGE_NO_FF_LINE = re.compile(r"git\s+(?:-[Cc]\s*\S+\s+)*merge\b.*--no-ff\b")
NO_COMMIT_WINDOW = 2  # lines either side — a trailing comment or a wrapped fence


@pytest.mark.parametrize("path", _skills(), ids=lambda p: p.parent.name + "/" + p.name)
def test_no_skill_creates_a_merge_commit_without_gating_it(path: Path):
    # `git merge --no-ff` (without `--no-commit`) creates a commit outright. The
    # hard rule gates it *before* it exists — but checking "does `--no-commit`
    # appear anywhere in the file" lets one gated occurrence cover an ungated one
    # elsewhere in the same document, which is exactly how a second, ungated merge
    # rode along unnoticed. Check each `--no-ff` occurrence on its own.
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    offenders = [
        (i + 1, lines[i].strip())
        for i, ln in enumerate(lines)
        if MERGE_NO_FF_LINE.search(ln)
        and not any(
            "--no-commit" in lines[j]
            for j in range(max(0, i - NO_COMMIT_WINDOW),
                            min(len(lines), i + NO_COMMIT_WINDOW + 1))
        )
    ]
    assert not offenders, (
        f"{path.relative_to(REPO)}: {len(offenders)} `git merge --no-ff` "
        f"occurrence(s) create a commit without a `--no-commit` staging step "
        f"within {NO_COMMIT_WINDOW} lines that lets /commit-prep gate it before "
        f"it exists:\n" + "\n".join(f"  line {n}: {t}" for n, t in offenders[:8])
    )
