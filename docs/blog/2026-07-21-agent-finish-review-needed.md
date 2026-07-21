---
title: Agents finish to review-needed — always
authors: [carefree]
tags: [feature, plans, review, workflow]
---

Agent completion is no longer a self-certify archive. When **Done when** holds,
`/work` always moves the plan to **`review-needed/`**. Humans archive with
**`/review`**.

<!-- truncate -->

The `review-needed/` lane and MCP `plans_complete` already sent work to human
sign-off. Interactive `/work` still offered a shortcut: agents could
`git mv` straight to `completed/`, and only *optionally* use `review-needed/`.
That gap meant finished work never showed up for human review.

**Now:** agent finish path is **only** `in-progress/` → `review-needed/`.
Moving `in-progress/` → `completed/` is forbidden for agents. The human runs
**`/review`** (AI critic + survey): Approve → `completed/`, Needs Work →
`bugs|features/`, Skip leaves the queue.

Same rule on Claude and Grok skills, `.plans/README`, scaffold, platforms, and
docs — aligned with the project-orchestrator MCP.
