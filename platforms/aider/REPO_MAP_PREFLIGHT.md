# Aider repo-map preflight (stale git index / HEAD ghosts)

**Full `AIDER.md` platform brief** is owned by the `aider-platform-and-scaffold`
workstream. This page is the **shipped** preflight for a failure mode that hits
before that brief lands.

## Failure mode

When tracked files are **deleted on disk** but still listed in **git HEAD**
(classic: migrate `site/docs/modules/*.md` → `*.mdx` and leave the `.md` paths
in history), Aider’s repo-map walks approximately **`HEAD` ∪ index** and prints
one warning per ghost path:

```text
Repo-map can't include /…/site/docs/modules/index.md
Has it been deleted from the file system but not from git?
```

Live class (2026-09-06, **network-lunar**): dozens of identical lines drowned
“tell me about this project.”

**Important:** `git add -u` alone does **not** stop the flood. Staged deletions
leave the path in the HEAD set until you **commit** the migration or hide the
paths with **`.aiderignore`**.

## Preflight

From the Anchor checkout or a scaffolded project’s `.anchor/scripts/`:

```bash
python scripts/aider_repo_map_preflight.py
# warn without failing a launcher:
python scripts/aider_repo_map_preflight.py --ok-exit
# interim hide (confirm required):
python scripts/aider_repo_map_preflight.py --write-aiderignore --yes
# prep commit of deletions only (never auto-commits):
python scripts/aider_repo_map_preflight.py --stage --yes
```

If your `.gitignore` uses a broad `.aider*` rule, allow the ignore file itself:

```gitignore
!.aiderignore
```

## Operator checklist after `.md` → `.mdx` (or similar)

1. Run the preflight — expect one block with a count + sample, not N Aider lines.
2. Stage scoped deletes (`git add -u -- path/…` or `--stage --yes`).
3. Either **commit** the migration (durable) **or** write `.aiderignore` lines
   for HEAD ghosts until that commit.
4. Then start Aider.

Never let unattended preflight commit for you.
