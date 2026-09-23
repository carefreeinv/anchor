#!/usr/bin/env python3
"""Report per-release completion by scanning plans, never a static member list.

A **release** groups plans via a *self-declaring* pointer: each plan may carry
an optional ``- **Release:** <slug>`` header naming a
``.plans/.releases/<slug>.md`` file. That file holds only release-level
metadata (``Status``, optional ``Target``) — it never enumerates member plans,
because a release's membership grows over time (see
``.plans/.releases/*.md`` doctrine / ``.plans/README.md`` "## Releases").
Membership is always computed here by scanning every plan's ``Release:``
field; nothing stores that list twice.

    python scripts/release_progress.py --list
    v0.3.0        open    12/17 complete (5 remaining)
    v0.4.0        open     0/4  complete (4 remaining)

    python scripts/release_progress.py --status v0.3.0
    ...

A plan may point at a release slug with no matching ``.plans/.releases/<slug>.md``
file (typo, or the file was never created) — reported as ``unknown-release``,
never silently dropped and never counted toward a phantom "complete" release.

It never claims, moves, or edits a **plan**. It does write one thing: a
release file's ``Status:``, and only in the ``ready -> open`` direction, via
``reconcile_reopen`` — which runs **by default** before ``--list`` /
``--status`` / ``--json``. That pass is pure bookkeeping (a release marked
ready that gained an incomplete member is no longer ready) and takes no
prompt; pass ``--no-reconcile`` to suppress it. The opposite direction,
``open -> ready``, is never automatic: it comes from ``--mark-ready`` or the
interactive ``/work`` / ``/review`` completion prompt. ``plan_select.py``
reads this data for its tiebreak and writes nothing.

Exit codes: 0 ran OK (including an empty backlog) · 2 error (bad args, no
``.plans/``).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from plan_select import (
    parse_release_field,
    plan_slug,
    plans_root_for,
    safe_read_text,
    strip_code_fences,
)

STATUS_RE = re.compile(r"^\s*-\s*\*\*Status:\*\*\s*(\S+)", re.MULTILINE | re.IGNORECASE)
TARGET_RE = re.compile(r"^\s*-\s*\*\*Target:\*\*\s*(\S+)", re.MULTILINE | re.IGNORECASE)
TITLE_RE = re.compile(r"^#\s+Release:\s*(.+)$", re.MULTILINE)

COMPLETED_LANE = "completed"
DEFAULT_STATUS = "open"
VALID_STATUSES = frozenset({"open", "ready", "shipped"})
NONE_TOKENS = frozenset({"none", "n/a", "-", "nil", "null"})


@dataclass
class PlanRef:
    slug: str
    lane: str
    rel: str  # "<lane>/<filename>"


@dataclass
class ReleaseInfo:
    slug: str
    file_exists: bool
    status: str = DEFAULT_STATUS
    target: str | None = None
    title: str | None = None
    members: list[PlanRef] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.members)

    @property
    def completed(self) -> int:
        return sum(1 for m in self.members if m.lane == COMPLETED_LANE)

    @property
    def remaining(self) -> list[PlanRef]:
        return [m for m in self.members if m.lane != COMPLETED_LANE]

    @property
    def is_complete(self) -> bool:
        """True only for a *real* (file-backed), non-empty, fully-completed release.

        An empty member set or an undefined release file is never "complete" —
        that is "doesn't exist," not "100% done" (see module docstring / C5 in
        the plan that introduced this)."""
        return self.file_exists and self.total > 0 and self.completed == self.total


def _read_release_file(path: Path) -> tuple[str, str | None, str | None]:
    """Return (status, target, title) for one ``.plans/.releases/<slug>.md`` file."""
    raw_text, parse_error = safe_read_text(path)
    if parse_error is not None:
        return DEFAULT_STATUS, None, None
    text = strip_code_fences(raw_text)
    sm = STATUS_RE.search(text)
    status = (sm.group(1).strip().strip("`").lower() if sm else DEFAULT_STATUS)
    if status not in VALID_STATUSES:
        status = DEFAULT_STATUS
    tm = TARGET_RE.search(text)
    target = tm.group(1).strip().strip("`") if tm else None
    if target and target.lower() in NONE_TOKENS:
        target = None
    tim = TITLE_RE.search(text)
    title = tim.group(1).strip() if tim else None
    return status, target, title


def set_status(plans_root: Path, slug: str, status: str) -> bool:
    """Rewrite a release file's ``Status:`` line in place. Returns False if the
    release file doesn't exist (nothing written) or ``status`` is invalid.

    Two callers, both explicit: `/work`/`/review` call this with ``"ready"``
    after asking the operator the once-only "prepare this release?" question
    (whatever the answer — see C2), and ``reconcile_reopen`` below calls it
    with ``"open"`` when a `ready` release gained new incomplete members.
    Never a side effect of any other command.
    """
    if status not in VALID_STATUSES:
        return False
    path = plans_root / ".releases" / f"{slug}.md"
    if not path.is_file():
        return False
    raw_text, parse_error = safe_read_text(path)
    if parse_error is not None:
        return False
    # Line-based, not a whole-text regex .sub(): STATUS_RE's leading `\s*`
    # (shared with the search-only field parsers) matches across a preceding
    # blank line under MULTILINE, so a .sub() over the full text would eat
    # that blank line along with the match. Rewriting one line at a time
    # sidesteps the whole class of bug rather than tightening the shared regex.
    lines = raw_text.split("\n")
    replaced = False
    for i, line in enumerate(lines):
        if STATUS_RE.match(line):
            lines[i] = f"- **Status:** {status}"
            replaced = True
            break
    if replaced:
        new_text = "\n".join(lines)
    else:
        new_text = raw_text.rstrip("\n") + f"\n- **Status:** {status}\n"
    path.write_text(new_text, encoding="utf-8")
    return True


def scan_releases(plans_root: Path) -> dict[str, ReleaseInfo]:
    """Scan ``.plans/.releases/*.md`` (defined releases) and every plan's
    ``Release:`` header (membership), across **all** lanes.

    Returns a dict keyed by release slug. A slug referenced only by plans
    (no ``.releases/`` file) still appears here with ``file_exists=False`` —
    callers treat that as ``unknown-release``, not a silent drop.
    """
    releases: dict[str, ReleaseInfo] = {}

    releases_dir = plans_root / ".releases"
    if releases_dir.is_dir():
        for path in sorted(releases_dir.glob("*.md")):
            slug = plan_slug(path)
            status, target, title = _read_release_file(path)
            releases[slug] = ReleaseInfo(
                slug=slug, file_exists=True, status=status, target=target, title=title
            )

    if not plans_root.is_dir():
        return releases

    for lane_dir in sorted(p for p in plans_root.iterdir() if p.is_dir()):
        if lane_dir.name.startswith("."):
            continue
        for path in sorted(lane_dir.glob("*.md")):
            if path.name == "README.md":
                continue
            raw_text, parse_error = safe_read_text(path)
            if parse_error is not None:
                continue
            text = strip_code_fences(raw_text)
            release_slug = parse_release_field(text)
            if release_slug is None:
                continue
            info = releases.get(release_slug)
            if info is None:
                info = ReleaseInfo(slug=release_slug, file_exists=False)
                releases[release_slug] = info
            info.members.append(
                PlanRef(slug=plan_slug(path), lane=lane_dir.name, rel=f"{lane_dir.name}/{path.name}")
            )

    return releases


def reconcile_reopen(plans_root: Path, releases: dict[str, ReleaseInfo]) -> list[str]:
    """Flip any ``ready`` release back to ``open`` if it now has incomplete
    members again (a new plan pointed at it, or one bounced out of
    `completed/`) — the automatic half of C2's "re-opening" rule. The other
    half (asking once when a release newly reaches 100%) stays an explicit,
    interactive `/work`/`/review` step; this part is pure bookkeeping with no
    prompt, safe to run unconditionally. Returns the slugs it reopened.
    """
    reopened: list[str] = []
    for slug, info in releases.items():
        if info.file_exists and info.status == "ready" and not info.is_complete:
            if set_status(plans_root, slug, "open"):
                info.status = "open"
                reopened.append(slug)
    return reopened


def format_line(info: ReleaseInfo) -> str:
    if not info.file_exists:
        return (
            f"unknown-release: {info.slug} — {info.total} plan(s) point here but "
            f".plans/.releases/{info.slug}.md does not exist "
            f"({', '.join(m.rel for m in info.members)})"
        )
    if info.total == 0:
        return f"{info.slug:32} {info.status:8} 0/0 (no plans point here yet)"
    return (
        f"{info.slug:32} {info.status:8} {info.completed}/{info.total} complete "
        f"({len(info.remaining)} remaining)"
    )


def format_detail(info: ReleaseInfo) -> str:
    lines = [f"# {info.slug}"]
    if not info.file_exists:
        lines.append("status:  unknown-release (no .plans/.releases/<slug>.md file)")
    else:
        lines.append(f"status:  {info.status}")
        if info.target:
            lines.append(f"target:  {info.target}")
        if info.title:
            lines.append(f"title:   {info.title}")
    lines.append(f"members: {info.total} total, {info.completed} completed")
    if info.remaining:
        lines.append("remaining:")
        for m in info.remaining:
            lines.append(f"  - {m.rel}")
    elif info.total:
        lines.append("remaining: none")
    return "\n".join(lines)


def to_json(releases: dict[str, ReleaseInfo]) -> str:
    out = {}
    for slug, info in releases.items():
        out[slug] = {
            "file_exists": info.file_exists,
            "status": info.status if info.file_exists else "unknown-release",
            "target": info.target,
            "total": info.total,
            "completed": info.completed,
            "remaining": [m.rel for m in info.remaining],
            "is_complete": info.is_complete,
        }
    return json.dumps(out, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="project root containing .plans/")
    ap.add_argument("--list", action="store_true", help="list every release (defined + unknown-release groups)")
    ap.add_argument("--status", metavar="SLUG", help="detail for one release slug")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument(
        "--mark-ready",
        metavar="SLUG",
        help="write Status: ready to this release file — called by /work or "
        "/review after asking the once-only completion prompt, on any "
        "answer (see C2)",
    )
    ap.add_argument(
        "--no-reconcile",
        action="store_true",
        help="skip the automatic ready->open reopen pass (see reconcile_reopen); "
        "on by default for --list/--status/--json since it's a prompt-free "
        "correction, not a decision",
    )
    args = ap.parse_args(argv)

    plans_root = plans_root_for(Path(args.root))
    if not plans_root.is_dir():
        print(f"[release_progress] no .plans/ under {args.root}", file=sys.stderr)
        return 2

    if args.mark_ready:
        ok = set_status(plans_root, args.mark_ready, "ready")
        if not ok:
            print(f"[release_progress] cannot mark ready: no such release file: {args.mark_ready}", file=sys.stderr)
            return 2
        print(f"[release_progress] {args.mark_ready}: Status -> ready")
        return 0

    releases = scan_releases(plans_root)
    if not args.no_reconcile:
        reopened = reconcile_reopen(plans_root, releases)
        for slug in reopened:
            print(f"[release_progress] {slug}: Status ready -> open (new incomplete members)", file=sys.stderr)

    if args.status:
        info = releases.get(args.status)
        if info is None:
            print(f"[release_progress] no such release: {args.status}", file=sys.stderr)
            return 2
        if args.json:
            print(to_json({args.status: info}))
        else:
            print(format_detail(info))
        return 0

    # Default (and --list): show everything, defined releases first.
    if args.json:
        print(to_json(releases))
        return 0

    if not releases:
        print("[release_progress] no releases found (no .plans/.releases/*.md, no plan Release: headers)")
        return 0

    defined = sorted((s for s in releases.values() if s.file_exists), key=lambda s: s.slug)
    orphans = sorted((s for s in releases.values() if not s.file_exists), key=lambda s: s.slug)
    for info in defined:
        print(format_line(info))
    for info in orphans:
        print(format_line(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
