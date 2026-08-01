#!/usr/bin/env python3
"""Structured handoff: how a task that outgrew one context window becomes a
planned continuation instead of a context-rot failure.

An executor approaching its declared `## Budget` ceiling emits the handoff
template (`anchor/templates/handoff.md`) rather than a partial result. This
module is the machine side of that contract:

* :func:`looks_like_handoff` — cheap detection, so the orchestrator can tell a
  handoff from a normal task result before it applies the output-footer check.
* :func:`parse_handoff` — strict parse into :class:`Handoff`. Remaining work that
  is not dispatchable (no ``Verify by``) is an error, not a shrug: a vague
  "finish the rest" item is exactly what makes a continuation fail.
* :func:`build_continuation` — the next window's task text: original task, minus
  what is done, plus the handoff as provided context. Scope may only shrink.

The model's handoff is an *input*. Whether a handoff happens at all, and how many
are allowed, is the orchestrator's call (`scripts/orchestrate.py`) — never the
executor's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from scope_gate import path_matches

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Done",
    "Remaining",
    "Decisions made",
    "Files touched",
    "Open concerns",
)

_HEADING_RE = re.compile(r"^##\s+(?P<name>[^\n#][^\n]*?)\s*$", re.MULTILINE)
_SUBSPEC_RE = re.compile(r"^###\s+(?P<title>[^\n]+?)\s*$", re.MULTILINE)
_FIELD_RE = re.compile(r"^\s*[-*]\s*(?P<key>[A-Za-z][A-Za-z ]*?)\s*:\s*(?P<value>.+?)\s*$",
                       re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<text>.+?)\s*$", re.MULTILINE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class HandoffError(ValueError):
    """A handoff that cannot be dispatched as written.

    Carries an operator-facing message that doubles as the corrective instruction
    sent back to the executor for its one retry.
    """


@dataclass(frozen=True)
class RemainingItem:
    """One ready-to-dispatch sub-spec from a handoff's ``## Remaining`` section."""

    title: str
    goal: str
    files: tuple[str, ...]
    verify_by: str
    notes: str = ""

    def as_spec(self) -> str:
        lines = [f"### {self.title}", f"- Goal: {self.goal}"]
        if self.files:
            lines.append(f"- Files in scope: {', '.join(self.files)}")
        lines.append(f"- Verify by: `{self.verify_by}`")
        if self.notes:
            lines.append(f"- Notes: {self.notes}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Handoff:
    """A parsed handoff artifact."""

    done: tuple[str, ...]
    remaining: tuple[RemainingItem, ...]
    decisions: tuple[str, ...]
    files_touched: tuple[str, ...]
    concerns: tuple[str, ...]
    raw: str

    @property
    def scope(self) -> tuple[str, ...]:
        """Every path the remaining sub-specs claim, de-duplicated in first-seen order."""
        seen: dict[str, None] = {}
        for item in self.remaining:
            for path in item.files:
                seen.setdefault(path, None)
        return tuple(seen)


def _strip_comments(text: str) -> str:
    """Drop HTML comments — the template's own guidance must not parse as content."""
    return _COMMENT_RE.sub("", text)


def _sections(text: str) -> dict[str, str]:
    """Split markdown into ``{heading: body}``, keyed case-insensitively."""
    out: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(text))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[match.group("name").strip().lower()] = text[match.end():end]
    return out


def _bullets(body: str) -> tuple[str, ...]:
    """Bullet lines of a section, placeholders and blanks included but stripped."""
    return tuple(m.group("text") for m in _BULLET_RE.finditer(body) if m.group("text").strip())


def _fields(body: str) -> dict[str, str]:
    return {m.group("key").strip().lower(): m.group("value").strip()
            for m in _FIELD_RE.finditer(body)}


def _split_paths(value: str) -> tuple[str, ...]:
    parts = [p.strip().strip("`") for p in re.split(r"[,\s]+", value) if p.strip()]
    return tuple(p for p in parts if p)


def looks_like_handoff(text: str) -> bool:
    """True when ``text`` carries every required handoff heading.

    Deliberately structural rather than clever: the orchestrator needs a cheap,
    total answer before it decides whether to apply the normal result-footer
    check, and a near-miss should fail this test so it is retried as a format
    error rather than half-parsed as a continuation.
    """
    present = _sections(_strip_comments(text))
    return all(name.lower() in present for name in REQUIRED_SECTIONS)


def _parse_remaining(body: str) -> tuple[RemainingItem, ...]:
    heads = list(_SUBSPEC_RE.finditer(body))
    if not heads:
        raise HandoffError(
            "HANDOFF: '## Remaining' has no '### <title>' sub-specs. Each remaining "
            "item must be a standalone sub-spec with Goal / Files in scope / Verify by. "
            "If nothing remains, do not emit a handoff — finish with the normal "
            "'## Result' footer instead."
        )
    items: list[RemainingItem] = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        title = head.group("title").strip()
        fields = _fields(body[head.end():end])
        verify = fields.get("verify by", "").strip().strip("`")
        if not verify:
            raise HandoffError(
                f"HANDOFF: remaining item {title!r} has no 'Verify by:' line. A "
                f"continuation cannot be dispatched without the command that proves "
                f"it done — re-emit the handoff with a Verify by line per remaining item."
            )
        items.append(RemainingItem(
            title=title,
            goal=fields.get("goal", "").strip(),
            files=_split_paths(fields.get("files in scope", "")),
            verify_by=verify,
            notes=fields.get("notes", "").strip(),
        ))
    return tuple(items)


def parse_handoff(text: str) -> Handoff:
    """Parse a handoff artifact, or raise :class:`HandoffError` saying what is wrong."""
    stripped = _strip_comments(text)
    sections = _sections(stripped)
    missing = [name for name in REQUIRED_SECTIONS if name.lower() not in sections]
    if missing:
        raise HandoffError(
            "HANDOFF: missing required section(s): "
            + ", ".join(f"'## {name}'" for name in missing)
            + ". Emit every section of anchor/templates/handoff.md, in order."
        )
    return Handoff(
        done=_bullets(sections["done"]),
        remaining=_parse_remaining(sections["remaining"]),
        decisions=_bullets(sections["decisions made"]),
        files_touched=_bullets(sections["files touched"]),
        concerns=_bullets(sections["open concerns"]),
        raw=text,
    )


def check_scope_shrinks(handoff: Handoff, in_scope: tuple[str, ...]) -> None:
    """Raise when a continuation would claim a path the original spec never allowed.

    Compaction is a place scope creep can hide: an executor that "discovers" it
    also needs `deploy/` can smuggle that in as a remaining item, and the fresh
    continuation has no memory of the original boundary. Widening scope stays the
    planner's call, so this is an error rather than a warning.
    """
    if not in_scope:
        return  # no declared scope to shrink from — nothing to check against
    offending = [p for p in handoff.scope
                 if not any(path_matches(p, pattern) for pattern in in_scope)]
    if offending:
        raise HandoffError(
            "HANDOFF: remaining work claims path(s) outside the original spec's "
            f"'## Files in scope': {', '.join(offending)}. Scope may only shrink across "
            "a continuation — send the widening back to the planner instead."
        )


def accumulate(previous: Handoff | None, latest: Handoff) -> Handoff:
    """Fold an earlier handoff's history into the newest one.

    Only ``remaining`` comes from the latest handoff — history is cumulative, so a
    third window still knows what the first one finished and decided. Without this,
    each continuation would only see the window immediately behind it and could
    happily redo the one before that.
    """
    if previous is None:
        return latest

    def merged(*groups: tuple[str, ...]) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for group in groups:
            for line in group:
                seen.setdefault(line, None)
        return tuple(seen)

    return Handoff(
        done=merged(previous.done, latest.done),
        remaining=latest.remaining,
        decisions=merged(previous.decisions, latest.decisions),
        files_touched=merged(previous.files_touched, latest.files_touched),
        concerns=merged(previous.concerns, latest.concerns),
        raw=latest.raw,
    )


def build_continuation(task: str, handoff: Handoff, *, window: int,
                       in_scope: tuple[str, ...] = ()) -> str:
    """Build the next window's task text from the original task plus the handoff.

    The continuation is the original task **minus** completed steps, **plus** the
    handoff as provided context. Done work and recorded decisions are stated as
    off-limits: the failure mode of a fresh context is not forgetting what is
    left, it is cheerfully redoing or reversing what is already finished.
    """
    check_scope_shrinks(handoff, in_scope)

    def block(title: str, lines: tuple[str, ...], empty: str) -> str:
        body = "\n".join(f"- {line}" for line in lines) if lines else f"- {empty}"
        return f"{title}\n{body}"

    parts = [
        f"CONTINUATION (window {window}) of this task:\n{task}",
        block("ALREADY DONE in earlier windows — do NOT redo:", handoff.done, "nothing recorded"),
        block("DECISIONS ALREADY MADE — do NOT reverse:", handoff.decisions, "none recorded"),
        block("FILES ALREADY TOUCHED — read before editing:", handoff.files_touched,
              "none recorded"),
        block("OPEN CONCERNS carried forward:", handoff.concerns, "none recorded"),
        "YOUR TASK — the remaining sub-specs ONLY:\n"
        + "\n\n".join(item.as_spec() for item in handoff.remaining),
        "Scope may only shrink: touch nothing outside the files listed above. If the "
        "remaining work still does not fit one window, emit another handoff — do not "
        "truncate and do not claim success you cannot verify.",
    ]
    return "\n\n".join(parts)
