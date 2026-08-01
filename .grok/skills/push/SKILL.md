---
name: push
description: >
  Push the current branch to its remote via /push — confirm first, never
  force, never tags unless --tags is asked for, never merges. Use when the
  user runs /push, wants to publish the current branch, or asks to send
  commits to a remote without cutting a release.
argument-hint: "[--tags|--prep|--force-with-lease]"
disable-model-invocation: false
metadata:
  short-description: "Publish the current branch — confirm, no force, no tags"
---

# /push — publish the current branch

Publish the **current branch** to its remote. Nothing more: no tags, no
merges, no force, unless explicitly asked. Shipping a version is `/tag` +
`/release`'s job, not `/push`'s.

`$ARGUMENTS` is everything after `/push`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/push` | Confirm remote + branch, then `git push -u origin HEAD` (or the tracked remote) |
| `/push --tags` | Also push tags reachable from `HEAD` (`git push --follow-tags`), after a separate confirm listing which tags |
| `/push --prep` | Run `/commit-prep` first; **stop if red**; still does not auto-commit unless the user separately asked for a commit |
| `/push --force-with-lease` | Explicit-only; requires the user to have already asked for a force push in this conversation — never inferred from context |

## Steps

1. **Resolve branch + remote.** Current branch (`git branch --show-current`);
   remote is the branch's existing upstream if tracked, else `origin` (ask if
   neither exists and more than one remote is configured).
2. **`--prep`:** run `/commit-prep`. If it comes back red, stop and report —
   do not push a tree with failing checks. `/commit-prep` never commits by
   itself; if there are uncommitted changes the user wants pushed, they need
   to be committed first (by the user, or by `/work`'s normal feature-branch
   commit flow) — `/push` does not commit on your behalf.
3. **Risk line for protected branches.** If the current branch is
   `main`/`master`/`dev`/`develop`, print a one-line risk note (pushing
   directly to an integration/mainline branch bypasses `/review`) and require
   explicit confirmation before continuing — do not silently proceed even
   under an otherwise-non-interactive flow.
4. **Confirm.** Show the exact command, branch, and remote before running
   anything. No confirmation is skipped by default; there is no `--yes` that
   bypasses this (unlike `/deploy`) because a push is directly visible to
   collaborators the moment it lands.
5. **Push.**
   ```bash
   git push -u <remote> <branch>
   ```
   With `--tags`, first list the local tags that are reachable from `HEAD`
   and not yet on the remote, confirm that specific list, then:
   ```bash
   git push --follow-tags <remote> <branch>
   ```
6. **Report** the exact ref pushed, the remote URL/branch it landed on, and
   (if `--tags`) which tags went with it.

## Safety

- **Never force-pushes** by default. `--force` / `--force-with-lease` is
  accepted **only** when the user has explicitly asked for a force push in
  this conversation — never inferred, never a default even for the user's
  own feature branch. Warn about a force push to any branch other agents or
  humans might have already pulled.
- **Never pushes to `main`/`master`/`dev`/`develop` silently** — a risk line
  and explicit confirmation are required every time, even for an operator who
  usually runs non-interactively.
- **Never creates or pushes a version tag on its own initiative** — `--tags`
  only pushes tags that already exist locally (created via `/tag`); `/push`
  never runs `git tag`.
- **Never merges** — landing a feature branch on `dev`/`main` stays
  `/review`'s job.

## Footer

`## Result` · `## How to verify` · `## Deferred / concerns`
