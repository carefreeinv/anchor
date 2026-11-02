"""Apply unified diffs from an executor chat reply into a worktree.

Stdlib only. Never shells out to ``patch``. Ambiguous, overlapping, or
role-forbidden paths fail closed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from roles import EXECUTOR, can_write

EDIT_FORMAT = (
    "EDIT FORMAT: after thinking, before the footer, include either a unified "
    "diff or a whole-file fence for every file you change.\n"
    "Unified diff:\n"
    "--- a/path/to/file\n"
    "+++ b/path/to/file\n"
    "@@ -1,2 +1,3 @@\n"
    " context\n"
    "-old line\n"
    "+new line\n"
    "Whole file (preferred if you cannot emit @@ hunks):\n"
    "```path/to/file.py\n"
    "full new contents\n"
    "```\n"
    "or: File: path/to/file.py  then a ```python fence with the full body.\n"
    "New files use --- /dev/null or a fence for a path that does not exist. "
    "Still end with ## Result / ## How to verify / ## Deferred / concerns."
)


class ApplyError(ValueError):
    """Rejected patch: parse error, overlap, path escape, or role deny."""


class NoApplyableHunks(ApplyError):
    """Reply contained no unified-diff hunks."""


@dataclass
class Hunk:
    old_start: int  # 1-based
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]  # including leading ' '/'+'/'-'/'\\'


@dataclass
class FilePatch:
    path: str  # relative posix path
    is_new: bool
    is_delete: bool
    hunks: list[Hunk] = field(default_factory=list)
    whole_body: str | None = None  # set → replace/create entire file


_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
)
_FENCE_RE = re.compile(r"^```(?:diff|patch|udiff)?\s*$", re.I)


def _strip_fences(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        out.append(line)
    return "\n".join(out)


def _norm_path(raw: str) -> str:
    s = raw.strip()
    if s.startswith("a/") or s.startswith("b/"):
        s = s[2:]
    s = s.replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s.lstrip("/")


def extract_patches(text: str) -> list[FilePatch]:
    """Parse ``---``/``+++`` unified diffs. Overlapping files are an error."""
    body = _strip_fences(text)
    lines = body.splitlines()
    patches: list[FilePatch] = []
    seen: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("--- "):
            i += 1
            continue
        old_raw = line[4:].split("\t", 1)[0].strip()
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            raise ApplyError("unified diff --- line is not followed by +++")
        new_raw = lines[i + 1][4:].split("\t", 1)[0].strip()
        i += 2
        is_new = old_raw in ("/dev/null", "a/dev/null")
        is_delete = new_raw in ("/dev/null", "b/dev/null")
        path = _norm_path(new_raw if not is_delete else old_raw)
        if not path or path == "dev/null":
            raise ApplyError("unified diff has empty path")
        if path in seen:
            raise ApplyError(f"overlapping patches for {path}")
        seen.add(path)
        hunks: list[Hunk] = []
        while i < len(lines) and lines[i].startswith("@@ "):
            m = _HUNK_RE.match(lines[i])
            if not m:
                raise ApplyError(f"malformed hunk header: {lines[i]!r}")
            old_start = int(m.group(1))
            old_count = int(m.group(2) if m.group(2) is not None else "1")
            new_start = int(m.group(3))
            new_count = int(m.group(4) if m.group(4) is not None else "1")
            i += 1
            hlines: list[str] = []
            while i < len(lines):
                hl = lines[i]
                if hl.startswith("--- ") or hl.startswith("@@ "):
                    break
                if hl.startswith("\\"):  # "\ No newline at end of file"
                    hlines.append(hl)
                    i += 1
                    continue
                if hl.startswith((" ", "+", "-")):
                    hlines.append(hl)
                    i += 1
                    continue
                break
            hunks.append(
                Hunk(old_start, old_count, new_start, new_count, hlines)
            )
        if not hunks and not is_new and not is_delete:
            raise ApplyError(f"no hunks for {path}")
        patches.append(FilePatch(path, is_new, is_delete, hunks))
    return patches


_FENCE_OPEN_RE = re.compile(r"^```([^\s`]+)?\s*$")
_FILE_HEADER_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:File|FILE|path|Path)\s*:\s+(\S+)\s*$",
)
_PATHISH = re.compile(r"^[\w./+-]+\.[\w.+-]+$")
_LANG_TAGS = frozenset(
    {
        "python", "py", "diff", "patch", "udiff", "text", "txt", "md",
        "markdown", "json", "yaml", "yml", "toml", "bash", "sh", "js",
        "ts", "tsx", "rs", "go", "c", "cpp", "java", "html", "css",
        "ini", "cfg", "xml", "sql", "rb", "php", "swift", "kt",
    }
)


def extract_file_blocks(text: str) -> list[FilePatch]:
    """Parse fenced whole-file bodies. Overlapping paths are an error."""
    patches, _residual = _extract_file_blocks(text)
    return patches


def _extract_file_blocks(text: str) -> tuple[list[FilePatch], str]:
    """Return (patches, residual text with those fences removed).

    Residual is what ``extract_patches`` may scan: a fenced ``notes.md`` whose
    body quotes ``--- a/other`` must not become a second patch.
    """
    lines = text.splitlines()
    keep = [True] * len(lines)
    by_path: dict[str, FilePatch] = {}
    pending_header: str | None = None
    pending_header_i: int | None = None
    i = 0
    while i < len(lines):
        hdr = _FILE_HEADER_RE.match(lines[i].strip())
        if hdr:
            pending_header = _norm_path(hdr.group(1).strip("`"))
            pending_header_i = i
            i += 1
            continue
        m = _FENCE_OPEN_RE.match(lines[i].strip())
        if not m:
            if lines[i].strip() == "" and pending_header:
                i += 1
                continue
            pending_header = None
            pending_header_i = None
            i += 1
            continue
        tag = (m.group(1) or "").strip()
        path: str | None = None
        header_i = pending_header_i
        if pending_header:
            path = pending_header
        elif tag and tag.lower() not in _LANG_TAGS:
            path = _norm_path(tag)
        pending_header = None
        pending_header_i = None
        fence_open = i
        i += 1
        body_lines: list[str] = []
        closed = False
        while i < len(lines):
            if lines[i].strip() == "```":
                closed = True
                i += 1
                break
            body_lines.append(lines[i])
            i += 1
        if not closed or path is None:
            continue
        if not path or path == "dev/null":
            raise ApplyError("file block has empty path")
        if path in by_path:
            raise ApplyError(f"overlapping patches for {path}")
        body = "\n".join(body_lines)
        if not body.strip():
            # consume the empty fence so it is not scanned as a diff
            for j in range(
                header_i if header_i is not None else fence_open, i
            ):
                keep[j] = False
            continue
        if not body.endswith("\n"):
            body += "\n"
        by_path[path] = FilePatch(
            path, is_new=False, is_delete=False, hunks=[], whole_body=body
        )
        start_mask = header_i if header_i is not None else fence_open
        for j in range(start_mask, i):
            keep[j] = False
    residual = "\n".join(ln for k, ln in zip(keep, lines) if k)
    return list(by_path.values()), residual


def _resolve(worktree: Path, rel: str) -> Path:
    if rel.startswith("/") or rel.startswith("..") or "/../" in f"/{rel}/":
        raise ApplyError(f"path escapes worktree: {rel}")
    wt = worktree.resolve()
    dest = (wt / rel).resolve()
    try:
        dest.relative_to(wt)
    except ValueError as exc:
        raise ApplyError(f"path escapes worktree: {rel}") from exc
    return dest


def _apply_hunks(
    original: list[str], hunks: list[Hunk], path: str, *, new_file: bool = False
) -> list[str]:
    """Apply hunks; ``original`` is lines *without* trailing ``\\n`` stripped —
    each element includes its newline if present except we use splitlines(True).
    """
    # Work on newline-preserving lines.
    lines = list(original)
    # Convert to no-nl list for indexing, remember whether file ended with nl.
    ended_nl = (not lines and new_file) or (bool(lines) and lines[-1].endswith("\n"))
    body = [ln[:-1] if ln.endswith("\n") else ln for ln in lines]

    ordered = sorted(hunks, key=lambda h: h.old_start, reverse=True)
    starts: list[int] = []
    for h in hunks:
        old_end = h.old_start + max(h.old_count, 0)
        for s, e in starts:
            if not (old_end <= s or h.old_start >= e):
                raise ApplyError(f"overlapping hunks in {path}")
        starts.append((h.old_start, old_end))

    for h in ordered:
        start = h.old_start - 1  # 0-based; 0 means insert at top for new file
        if h.old_count == 0:
            start = h.old_start  # GNU: -0,0 or -1,0 insert before line
            if h.old_start == 0:
                start = 0
            else:
                start = h.old_start  # insert after this many existing lines? 
                # unified: @@ -0,0 +1,1 @@ for new file; @@ -3,0 +4,1 @@ insert after line 3
                start = h.old_start
        old_slice = body[start : start + h.old_count] if h.old_count else []
        expected: list[str] = []
        replacement: list[str] = []
        for hl in h.lines:
            if hl.startswith("\\"):
                continue
            tag, rest = hl[0], hl[1:]
            if tag == " ":
                expected.append(rest)
                replacement.append(rest)
            elif tag == "-":
                expected.append(rest)
            elif tag == "+":
                replacement.append(rest)
            else:
                raise ApplyError(f"bad hunk line in {path}: {hl!r}")
        if h.old_count == 0:
            insert_at = h.old_start  # after this 1-based line; 0 => 0
            if insert_at < 0 or insert_at > len(body):
                raise ApplyError(f"hunk offset out of range in {path}")
            body[insert_at:insert_at] = replacement
            continue
        if start < 0 or start + h.old_count > len(body):
            raise ApplyError(f"hunk offset out of range in {path}")
        actual = body[start : start + h.old_count]
        if actual != expected:
            raise ApplyError(
                f"hunk context mismatch in {path}: expected {expected!r} got {actual!r}"
            )
        body[start : start + h.old_count] = replacement

    if not body:
        return []
    out = [ln + "\n" for ln in body]
    if not ended_nl and out:
        out[-1] = out[-1].rstrip("\n")
    return out


def apply_reply(
    text: str,
    worktree: Path,
    *,
    extra_deny: tuple[str, ...] = (),
) -> list[str]:
    """Write patches from ``text`` under ``worktree``. Returns relative paths."""
    blocks, residual = _extract_file_blocks(text)
    patches = extract_patches(residual)
    if patches and blocks:
        overlap = {p.path for p in patches} & {b.path for b in blocks}
        if overlap:
            raise ApplyError(f"overlapping patches for {sorted(overlap)[0]}")
        patches = list(patches) + list(blocks)
    elif not patches:
        patches = blocks
    if not patches:
        raise NoApplyableHunks("no applyable hunks in executor reply")
    written: list[str] = []
    for p in patches:
        rel = p.path.replace("\\", "/")
        if rel == ".plans" or rel.startswith(".plans/"):
            raise ApplyError(f"executor may not write {p.path}")
        if not can_write(EXECUTOR, p.path, extra_deny=extra_deny):
            raise ApplyError(f"executor may not write {p.path}")
        dest = _resolve(worktree, p.path)
        if p.whole_body is not None:
            if "\0" in p.whole_body:
                raise ApplyError(f"binary body refused for {p.path}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(p.whole_body, encoding="utf-8")
            written.append(p.path)
            continue
        if p.is_delete:
            if dest.exists():
                dest.unlink()
            written.append(p.path)
            continue
        if p.is_new:
            if dest.exists():
                raise ApplyError(f"refusing to overwrite existing {p.path}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            new_lines = _apply_hunks([], p.hunks, p.path, new_file=True)
            dest.write_text("".join(new_lines), encoding="utf-8")
            written.append(p.path)
            continue
        if not dest.is_file():
            raise ApplyError(f"missing file {p.path}")
        original = dest.read_text(encoding="utf-8").splitlines(keepends=True)
        dest.write_text("".join(_apply_hunks(original, p.hunks, p.path)), encoding="utf-8")
        written.append(p.path)
    return written
