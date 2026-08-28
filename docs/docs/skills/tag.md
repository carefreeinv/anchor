---
sidebar_position: 3.9
sidebar_label: /tag · version marks
---

# `/tag`

**Best used:** when you need a local, annotated version tag — checking what
scheme a repo already uses, what the next version should be, or cutting the
tag itself. See [Skills overview](/skills/overview).

`/tag` only marks a commit with a version. It never pushes a tag or branch,
and it is not a release: deciding what merges before a version ships is
[`/release`](/skills/overview)'s job, not `/tag`'s.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/tag` / `/tag --status` | Detect existing tag scheme; show latest tag; suggest next version |
| `/tag --suggest` | Print **only** the suggested next version (patch bump) |
| `/tag --suggest patch\|minor\|major` | Print only the next version at that bump level |
| `/tag vX.Y.Z` | Create a local annotated tag at `HEAD`, after confirm |
| `/tag --create vX.Y.Z [--at <ref>] [--message "…"]` | Explicit form; `--at` tags a ref other than `HEAD` |
| `/tag --allow-dirty` | Tag despite an unclean working tree (still confirmed; risk line printed) |

## Scheme detection

`/tag` reads `git tag --list` and classifies what's already there — `v`-prefixed
semver, bare semver, calver, or something else — and **never invents a second
scheme** once one is in use. With no tags yet, it defaults to annotated semver
with a `v` prefix (`v0.1.0`), seeded from a package manifest version
(`pyproject.toml`, `package.json`, `Cargo.toml`) when one looks right.

## Safety

- **Never pushes** — local tag only, every invocation.
- **Never force-tags** — an existing tag name is a hard stop, not a prompt.
- Dirty working tree blocks tag creation by default (`--allow-dirty` overrides,
  with a printed risk line).
- `--status` / `--suggest` are read-only and never prompt.

## Scaffolded?

Yes — dual-use Claude command + Grok skill (`scripts/anchor.py` platform lists).

Full contract: source `.claude/commands/tag.md` / `.grok/skills/tag/SKILL.md`.
