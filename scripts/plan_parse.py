#!/usr/bin/env python3
"""Mechanical (no-LLM) plan parsing + triage primitives, shared by ``plan_select.py``,
``plan_fit.py``, and daemon/fleet-worker entrypoints.

Why this exists: judging a plan's header fields — and whether a worker should
take/skip/reject it — never needs a model. It is a deterministic read of the
file. Reserving models for **execution**, not triage, saves cost and latency on
every fleet-worker poll. This module is the parsing layer; ``plan_select.py``
keeps the richer fit-classification (tier/name/effort/specialty) built on top of
it, so nothing here duplicates that logic.

``strip_code_fences`` is the one structural (CommonMark-**aware**, not a full
CommonMark implementation) fix over naive regex-over-whole-file scanning: a plan
that quotes an example header inside a fenced code block (this repo's own
``anchor/templates/plan.md`` does exactly that) must not have that example parsed
as the plan's own field. A maintained CommonMark library was considered per the
plan's own Constraints (stdlib-first is the explicitly named fallback in its
Risks table) but rejected here: ``scripts/`` is designed to be copied standalone
into other projects, and every dependency added here is one every consumer project
must also install. A fence-aware line scan gets the real-world benefit (robust
against quoted examples) without adding one.

## Triage policy (accept / skip / reject)

A worker triaging one already-parsed plan record answers exactly one of three:

| Action | When |
|--------|------|
| **reject** | unreadable · missing Goal · human Assignee · unmet deps (unless ``ignore_deps``) · underqualified |
| **skip** | overqualified · lease held by another agent |
| **take** | good/unknown fit, deps met, agent-assignable |

This is a **superset** of ``plan_fit.py``'s existing take/skip split — that CLI's
public output stays a binary take/skip (its established shape, unchanged here);
``reject`` is the new distinction this module adds for daemons that want to tell
"never eligible" apart from "eligible for someone else."
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

GOAL_RE = re.compile(
    r"^##\s+Goal\s*$([\s\S]*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE
)

# ```lang ... ``` or ~~~lang ... ~~~, either fence length-3-or-more, matched
# non-greedily across lines. Good enough for the fences plans actually use —
# this is not a full CommonMark fence-matching implementation (nested/mismatched
# fence lengths, tildes vs backticks mixed mid-document, etc. are not modeled).
_FENCE_RE = re.compile(r"^([`~]{3,}).*?$\n[\s\S]*?^\1.*?$\n?", re.MULTILINE)


def strip_code_fences(text: str) -> str:
    """Blank out fenced code block bodies, preserving line count and structure.

    Header/section regexes run on the result so a quoted example plan header
    inside a fence (a doc walkthrough, a template, a "here's what NOT to do")
    can never be mistaken for the file's own field. Blanking (not deleting)
    keeps every other regex's line-based ``^``/``$`` anchors and match
    positions meaningful.
    """

    def _blank(m: re.Match) -> str:
        return "\n" * m.group(0).count("\n")

    return _FENCE_RE.sub(_blank, text)


def has_goal_section(text: str) -> bool:
    """Whether a non-empty ``## Goal`` section exists (fence-aware).

    A plan with no goal is not a smaller version of a plan — it is not
    triageable at all, mechanically or otherwise, which is why it is a hard
    *reject* rather than a soft *skip* in the policy table above.
    """
    m = GOAL_RE.search(strip_code_fences(text))
    return bool(m and m.group(1).strip())


def safe_read_text(path: Path) -> tuple[str | None, str | None]:
    """Read a plan file without ever raising — daemons must not crash-loop on
    one bad file. Returns ``(text, None)`` on success, ``(None, reason)`` on
    failure (missing file, permission error, bad encoding, ...)."""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
        return None, f"not valid UTF-8: {exc}"
    except OSError as exc:
        return None, f"{exc.__class__.__name__}: {exc}"


class TriageAction(str, Enum):
    TAKE = "take"
    SKIP = "skip"
    REJECT = "reject"


@dataclass(frozen=True)
class TriageVerdict:
    action: TriageAction
    reason: str


class _TriageableRecord(Protocol):
    """Structural shape ``triage_plan`` needs — deliberately not an import of
    ``plan_select.PlanRecord`` (which needs this module for parsing): plan_parse
    stays the lower layer, plan_select the higher one, so a duck-typed Protocol
    here is what keeps the dependency one-directional."""

    parse_error: str | None
    has_goal: bool
    agent_assignable: bool
    assignee: str | None
    deps_met: bool
    deps_unmet: tuple[str, ...]
    fit: object  # a str-valued Enum (or plain str); compared by .value below
    preferred: str | None
    owner: str | None


def triage_plan(
    rec: _TriageableRecord,
    worker,
    *,
    ignore_deps: bool = False,
    agent_id: str | None = None,
) -> TriageVerdict:
    """Accept/skip/reject one already-parsed plan record. Pure — no I/O, no LLM.

    ``worker`` is a ``plan_select.Worker`` (or anything with ``.tier``/``.name``);
    not type-imported for the same layering reason as ``_TriageableRecord``.
    """
    if rec.parse_error:
        return TriageVerdict(TriageAction.REJECT, f"unreadable: {rec.parse_error}")
    if not rec.has_goal:
        return TriageVerdict(TriageAction.REJECT, "missing ## Goal section")
    if not rec.agent_assignable:
        return TriageVerdict(
            TriageAction.REJECT,
            f"assigned to {rec.assignee or 'a human'} (agents don't complete this)",
        )
    if not rec.deps_met and not ignore_deps:
        return TriageVerdict(TriageAction.REJECT, "deps UNMET: " + ", ".join(rec.deps_unmet))
    fit_value = getattr(rec.fit, "value", rec.fit)
    pref = rec.preferred or "(none)"
    if fit_value == "underqualified":
        return TriageVerdict(
            TriageAction.REJECT, f"underqualified (Preferred: {pref}; you: {worker.tier})"
        )
    if fit_value == "overqualified":
        return TriageVerdict(
            TriageAction.SKIP, f"overqualified (Preferred: {pref}; you: {worker.tier})"
        )
    if rec.owner and agent_id and rec.owner != agent_id:
        return TriageVerdict(TriageAction.SKIP, f"lease held by {rec.owner}")
    return TriageVerdict(TriageAction.TAKE, f"{fit_value} (Preferred: {pref})")
