---
title: "anchor work, review, and draft are the default loop"
authors: [carefree]
tags: [feature, tooling]
---

With `anchor` on PATH, the three verbs pick and run: **work** executes the top
ready plan, **review** critics the top `review-needed/` plan, **draft** takes a
brief and asks the planner for a full file.

<!-- truncate -->

`--list` still lists. `anchor work --no-run` still claims only. Empty
`review-needed/` with integration ahead of mainline still exits 2 and names
`anchor review --promote`. Drafts stay in `drafts/` as `*.local.md` unless
`--shared`. Survey and merge stay on a TTY.

Headless critic and planner calls are allowed. Approve is not.
