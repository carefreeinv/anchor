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
SYNC_MAP: dict[str, str] = {
    "anchor/ANCHOR.md": "docs/docs/doctrine.md",
    "anchor/model-fitness.md": "docs/docs/model-fitness.md",
    "anchor/capacity-routing.md": "docs/docs/capacity-routing.md",
    "platforms/claude-code/CLAUDE.md": "docs/docs/platforms/claude-code.md",
    "platforms/grok-build/GROK.md": "docs/docs/platforms/grok-build.md",
    "platforms/nvidia-nim/NEMOTRON.md": "docs/docs/platforms/nvidia-nim.md",
    "platforms/local-models/README.md": "docs/docs/platforms/local-models.md",
    "platforms/chat/CHAT.md": "docs/docs/platforms/chat.md",
}

SYNC_COMMENT_RE = re.compile(r"<!--\s*synced-from:\s*(\S+)\s*@\s*([0-9a-f]{40})\s*-->")


def git_blob_hash(rel_path: str) -> str:
    result = subprocess.run(["git", "hash-object", rel_path], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=5, check=True)
    return result.stdout.strip()


def read_recorded_hash(docs_path: Path) -> tuple[str, str] | None:
    """Return (recorded_source, recorded_hash) from the docs page's sync comment, or None."""
    match = SYNC_COMMENT_RE.search(docs_path.read_text(encoding="utf-8"))
    return (match.group(1), match.group(2)) if match else None


def check() -> list[str]:
    """Return a list of human-readable problems; empty means everything is in sync."""
    problems: list[str] = []
    for source_rel, docs_rel in SYNC_MAP.items():
        docs_path = REPO_ROOT / docs_rel
        if not docs_path.exists():
            problems.append(f"{docs_rel}: file does not exist (expected to mirror {source_rel})")
            continue
        recorded = read_recorded_hash(docs_path)
        if recorded is None:
            problems.append(f"{docs_rel}: missing 'synced-from' comment (expected one for {source_rel})")
            continue
        recorded_source, recorded_hash = recorded
        if recorded_source != source_rel:
            problems.append(f"{docs_rel}: synced-from points at '{recorded_source}', expected '{source_rel}'")
            continue
        current_hash = git_blob_hash(source_rel)
        if current_hash != recorded_hash:
            problems.append(
                f"{docs_rel}: stale — synced from {source_rel} @ {recorded_hash[:12]}, "
                f"source is now @ {current_hash[:12]}. Review the docs page, then re-stamp."
            )
    return problems


def stamp() -> None:
    for source_rel, docs_rel in SYNC_MAP.items():
        docs_path = REPO_ROOT / docs_rel
        current_hash = git_blob_hash(source_rel)
        text = docs_path.read_text(encoding="utf-8")
        new_comment = f"<!-- synced-from: {source_rel} @ {current_hash} -->"
        if SYNC_COMMENT_RE.search(text):
            text = SYNC_COMMENT_RE.sub(new_comment, text, count=1)
        else:
            text = f"{new_comment}\n{text}"
        docs_path.write_text(text, encoding="utf-8")
        print(f"stamped {docs_rel} @ {current_hash[:12]}")


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
