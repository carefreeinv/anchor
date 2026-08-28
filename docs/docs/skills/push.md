---
sidebar_position: 3.91
sidebar_label: /push · publish the branch
---

# `/push`

**Best used:** when the current branch is ready to publish and nothing more —
no tags, no merges, no force. See [Skills overview](/skills/overview).

`/push` is deliberately thin. It confirms the exact command before running
anything, and it never does anything beyond pushing the current branch:
cutting a version is [`/tag`](/skills/tag)'s job, and landing a feature branch
on integration is [`/review`](/skills/review)'s.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/push` | Confirm remote + branch, then `git push -u` |
| `/push --tags` | Also push tags reachable from `HEAD`, after a separate confirm listing which ones |
| `/push --prep` | Run `/commit-prep` first; stop if red; still does not auto-commit |
| `/push --force-with-lease` | Explicit-only — requires the user to have already asked for a force push in this conversation |

## Safety

- **Never force-pushes** by default, on any branch — including the user's own
  feature branch.
- **Never pushes to `main`/`master`/`dev`/`develop` silently** — a risk line
  and explicit confirmation are required every time.
- **Never creates a tag** — `--tags` only pushes tags that already exist
  locally (made with `/tag`).
- **Never merges** — landing work on integration stays `/review`'s job.

## Scaffolded?

Yes — dual-use Claude command + Grok skill (`scripts/anchor.py` platform lists).

Full contract: source `.claude/commands/push.md` / `.grok/skills/push/SKILL.md`.
