---
title: Aider drones get a skills roster
authors: [carefree]
tags: [feature, skills, tooling]
---

Yesterday's Aider platform scaffold shipped `AIDER.md` — a brief that teaches
a drone session to run `/work` and nothing else. It didn't say much about
*why* nothing else: an operator typing `/draft` or `/review` at a drone just
got a one-line redirect buried in prose. `anchor --platform aider` now also
writes a small `skills-index.md` that makes that roster explicit.

<!-- truncate -->

## One skill, one roster

`platforms/aider/skills-index.md` ships alongside `AIDER.md` (both loaded via
`.aider.conf.yml`'s `read:` list) and lists, in one table, the only skill a
drone runs — `/work`, with its optional slug and `--list` form — followed by
every other Anchor command (`/draft`, `/review`, `/audit`, `/optimize`, …)
marked queen-bee-only. If a ready plan's own Steps call for a narrow slice of
one of those (a test run, a one-line CHANGELOG entry), the index says to do
that narrow thing rather than pull in the full skill.

`AIDER.md` itself didn't need to change: it already carries a condensed
`/work` procedure inline rather than pointing at the canonical skill file,
because Aider's small local models have no way to fetch a file into context
on demand — the procedure has to already be sitting in the chat. The index is
a companion, not a replacement.

## What ships

```yaml
read:
  - AIDER.md
  - platforms/aider/skills-index.md
```

is now the default `.aider.conf.yml.example` for `anchor --platform aider`.
Existing Aider scaffolds pick it up on the next `anchor --platform aider`
re-scaffold.
