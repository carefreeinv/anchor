---
description: Detect this repo's version-tag scheme and show/suggest/create the next tag — never pushes
---

# /tag — version marks

Detect, suggest, or create a **local annotated git tag**. `/tag` never pushes
anything (tags or branches) and is not a release: it only marks a version at
the current (or a named) commit. Shipping a release — including deciding
what merges before the tag — is `/release`'s job.

`$ARGUMENTS` is everything after `/tag`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/tag` / `/tag --status` | Detect existing tag scheme; show latest tag; suggest next version |
| `/tag --suggest` | Same as `--status` but print **only** the suggested next version (patch bump) |
| `/tag --suggest patch\|minor\|major` | Print only the next version at that bump level |
| `/tag vX.Y.Z` | Create a local annotated tag `vX.Y.Z` at `HEAD`, after confirm |
| `/tag --create vX.Y.Z [--at <ref>] [--message "…"]` | Same, explicit form; `--at` tags a ref other than `HEAD` |
| `/tag --allow-dirty` | Combine with a create form to tag despite an unclean working tree (still confirmed; risk line printed) |

## Steps

### 1. Detect the existing scheme

```bash
git tag --list | sort -V
```

- **Empty** → no scheme yet. Default to **annotated semver with a `v` prefix**
  (`v0.1.0`), aligned with any version found in a package manifest
  (`pyproject.toml` `version = "…"`, `package.json` `"version"`, `Cargo.toml`,
  etc.) if one exists and looks like the right seed; otherwise start at
  `v0.1.0`.
- **Non-empty** → classify the most recent tags:
  - `v` + semver (`v1.4.2`) — the common case
  - bare semver (`1.4.2`, no `v`)
  - calver (`2026.07.31`, `26.07`, or similar date-shaped tags)
  - anything else → report the raw pattern and ask once rather than guessing
- **Never invent a second scheme** when one is already in use. If tags exist,
  match their exact shape (prefix, zero-padding, segment count) — don't
  "improve" it mid-project.

### 2. Determine latest + suggest next

- Latest = highest by the scheme's own ordering (semver: `sort -V` last
  entry, or `git describe --tags --abbrev=0` from `HEAD` for the latest
  reachable tag). Calver: lexicographic/date order is usually sufficient.
- Suggested next version:
  - Default bump is **patch** unless the user asked for `minor`/`major` via
    `--suggest <level>`.
  - Cross-check against a package manifest version if present — if the
    manifest is already ahead of the latest tag, prefer the manifest's
    version as the suggestion (someone already bumped it) rather than
    patch-incrementing the old tag.
  - Calver: next = today's date in the detected format (no "bump level").

### 3. `--status` / bare `/tag` output

Print: detected scheme, latest tag (with commit + date), how many commits
`HEAD` is ahead of it (`git rev-list <tag>..HEAD --count`), and the suggested
next version. Read-only — stop here.

### 4. `--suggest [level]` output

Print **only** the next version string (no table, no explanation) — this
form is meant to be pasted or captured by another skill/script.

### 5. Create (`/tag vX.Y.Z` or `--create`)

1. **Validate the version string** matches the detected (or newly chosen)
   scheme; refuse silently-mismatched formats (e.g. `1.2.3` when every
   existing tag is `vX.Y.Z`) — ask instead of guessing which one wins.
2. **Refuse a dirty working tree** (`git status --short` non-empty) unless
   `--allow-dirty` was passed — tags should mark a reproducible commit.
   `--allow-dirty` still prints a one-line risk note before confirming.
3. **Refuse an existing tag name** — never move or force-overwrite a tag
   (`git tag -f` is out of scope for this skill; a human re-tagging a
   published version does that manually and deliberately).
4. **Confirm** before creating: show the exact tag name, target ref (default
   `HEAD`, or `--at <ref>`), and the annotation message (default: `Release
   vX.Y.Z`, or `--message` override).
5. Create the tag:
   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z" [<ref>]
   ```
6. Report the created tag and remind the user it is **local only** —
   `git push origin vX.Y.Z` (or `--tags`) is a separate, explicit step this
   skill does not take. `/release` handles pushing tags as part of a
   deliberate ship.

## Safety

- **Never pushes** — local tag only, every invocation.
- **Never force-tags** — an existing tag name is a hard stop, not a prompt.
- Dirty tree blocks tag creation by default.
- Confirms before every write; `--status`/`--suggest` are read-only and
  never prompt.

## Footer

`## Result` · `## How to verify` · `## Deferred / concerns`
