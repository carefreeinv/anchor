#!/usr/bin/env python3
"""Flag docs pages that mirror a repo file (per CLAUDE.md: "Docs pages mirror repo
files — update both when changing doctrine") whose source has changed since the
docs page was last reviewed.

Each mirrored docs page carries a `<!-- synced-from: <source path> @ <git blob hash> -->`
comment near the top. This script recomputes the source's current git blob hash and
compares it to the recorded one. A mismatch doesn't mean the docs page is wrong — it
means nobody has confirmed it's still right since the source last changed. Fix by
reviewing the docs page and updating the hash in its comment (this script can do
that for you with --stamp once you've actually reviewed the content).

**It compares hashes, not content.** A green run says "every mirror was re-read
since its source last moved" — never "every mirror matches its source". Re-stamping
makes it green whether or not you reviewed anything, so `--stamp` records an
assertion you are making, not a check being performed. Do not cite a green run as
evidence that a page and its source agree.

Usage:
  python scripts/check_docs_sync.py            # report; exit 1 if anything is stale
  python scripts/check_docs_sync.py --stamp    # after reviewing, refresh all recorded hashes
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# source (repo-relative) -> docs page (repo-relative) that mirrors it.
# source (repo-relative) -> docs page, or a TUPLE of sources -> docs page when a
# page mirrors several files. A multi-source page goes stale when **any** of its
# sources moves, and records one `synced-from:` comment per source.
SYNC_MAP: dict[object, str] = {
    "anchor/ANCHOR.md": "docs/docs/doctrine.md",
    "anchor/model-fitness.md": "docs/docs/model-fitness.md",
    "anchor/capacity-routing.md": "docs/docs/capacity-routing.md",
    "platforms/claude-code/CLAUDE.md": "docs/docs/platforms/claude-code.md",
    "platforms/grok-build/GROK.md": "docs/docs/platforms/grok-build.md",
    "platforms/nvidia-nim/NEMOTRON.md": "docs/docs/platforms/nvidia-nim.md",
    "platforms/local-models/README.md": "docs/docs/platforms/local-models.md",
    "platforms/chat/CHAT.md": "docs/docs/platforms/chat.md",
    # The install command on this page is copied from all three server READMEs.
    # Registering only one would give partial coverage that reads as complete —
    # and an unbounded `pip install "mcp[cli]"` drifting back in is exactly the
    # bug this page was corrected for.
    (
        "mcp/model-fleet/README.md",
        "mcp/anchor-prompts/README.md",
        "mcp/project-orchestrator/README.md",
    ): "docs/docs/tooling/mcp-servers.md",
}


def _sources(key: object) -> tuple[str, ...]:
    """Normalize a SYNC_MAP key to a tuple of source paths."""
    return (key,) if isinstance(key, str) else tuple(key)

SYNC_COMMENT_RE = re.compile(r"<!--\s*synced-from:\s*(\S+)\s*@\s*([0-9a-f]{40})\s*-->")


def git_blob_hash(rel_path: str) -> str:
    result = subprocess.run(["git", "hash-object", rel_path], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=5, check=True)
    return result.stdout.strip()


def read_recorded_hashes(docs_path: Path) -> list[tuple[str, str]]:
    """Every (source, hash) pair recorded in the page's sync comments.

    A page mirroring one file has one comment; a page mirroring several has one
    per source, so a change to any of them can be detected independently.
    """
    text = docs_path.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2)) for m in SYNC_COMMENT_RE.finditer(text)]


def check() -> list[str]:
    """Return a list of human-readable problems; empty means everything is in sync."""
    problems: list[str] = []
    for key, docs_rel in SYNC_MAP.items():
        sources = _sources(key)
        docs_path = REPO_ROOT / docs_rel
        if not docs_path.exists():
            problems.append(
                f"{docs_rel}: file does not exist (expected to mirror {', '.join(sources)})")
            continue
        recorded = dict(read_recorded_hashes(docs_path))
        if not recorded:
            problems.append(
                f"{docs_rel}: missing 'synced-from' comment "
                f"(expected one per source: {', '.join(sources)})")
            continue
        for source_rel in sources:
            if source_rel not in recorded:
                problems.append(
                    f"{docs_rel}: no synced-from line for '{source_rel}'. "
                    f"Review the docs page, then re-stamp.")
                continue
            current_hash = git_blob_hash(source_rel)
            if current_hash != recorded[source_rel]:
                problems.append(
                    f"{docs_rel}: stale — synced from {source_rel} @ "
                    f"{recorded[source_rel][:12]}, source is now @ {current_hash[:12]}. "
                    f"Review the docs page, then re-stamp."
                )
        for extra in sorted(set(recorded) - set(sources)):
            problems.append(
                f"{docs_rel}: synced-from names '{extra}', which SYNC_MAP does not "
                f"list as a source of this page.")
    return problems


FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def stamp() -> None:
    """Rewrite each page's synced-from block, leaving the rest of the file alone.

    The block goes **after** any frontmatter, which is where these pages already
    carry it — normalizing it to the top would churn every mirrored page for no
    reason and put HTML above a `---` fence.
    """
    for key, docs_rel in SYNC_MAP.items():
        sources = _sources(key)
        docs_path = REPO_ROOT / docs_rel
        text = docs_path.read_text(encoding="utf-8")
        # Drop the old block (and the blank line it left behind), wherever it sat.
        text = re.sub(rf"(?:{SYNC_COMMENT_RE.pattern}\n?)+\n?", "", text, count=1)
        block = "\n".join(
            f"<!-- synced-from: {src} @ {git_blob_hash(src)} -->" for src in sources)
        fm = FRONTMATTER_RE.match(text)
        if fm:
            text = f"{fm.group(0)}\n{block}\n\n{text[fm.end():].lstrip(chr(10))}"
        else:
            text = f"{block}\n\n{text.lstrip(chr(10))}"
        docs_path.write_text(text, encoding="utf-8")
        print(f"stamped {docs_rel} @ {len(sources)} source(s)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stamp", action="store_true",
                    help="after reviewing the docs pages, refresh all recorded hashes")
    args = ap.parse_args()

    if args.stamp:
        stamp()
        return

    problems = check()
    if not problems:
        print(f"OK — {len(SYNC_MAP)} docs page(s) in sync with their source.")
        return
    print(f"{len(problems)} docs page(s) need review:\n", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
