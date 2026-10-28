---
title: Autonomous finish archives on the branch and opens a PR after critic ACCEPT
authors: [carefree]
tags: [feature, doctrine, plans, review, workflow]
---

Cloud-running agents no longer park finished work in `review-needed/` and wait.
After a fresh-context critic rates **ACCEPT**, they move the plan to
`completed/` **on `feature/<slug>`** and open a pull request against
integration. A human still merges that PR.

<!-- truncate -->

There are **two finish workflows**. They are not the same path with a flag
toggled.

**Human-assisted** (a person is supervising `/work` / `/review`): work → critic
→ (REVISE → work)* → the human decides. Default parking is still
`review-needed/`. `/review` Approve merges locally then archives. The
culmination question **merge to `dev` now** still exists. This session never
auto-opens a PR.

**Autonomous / cloud** (`work_once.py`, fleet workers, coordinator MCP): work →
critic → (REVISE → work)* → **ACCEPT**. Only then: `in-progress/` →
`completed/` on the feature branch, push (no force), `gh pr create` targeting
`dev`/`develop`. **Never merge.** **REVISE** never archives and never opens a
PR. Three critic cycles, ESCALATE, or two failed fixes on the same finding
stop with no PR.

The critic is the same `/review` §7 spawn (`templates/review.md` verdict
`ACCEPT | REVISE | ESCALATE`; **APPROVED** means ACCEPT). The executor does
not ACCEPT its own work. Moving to `completed/` on the feature branch is the
tail of that ACCEPT, immediately before the PR — not a self-certified merge.
`pending_merges.py` already treats `feature/<slug>` plus a plan under
`.plans/completed/` as **completed work awaiting merge**.

Interactive `/push` still confirms. The autonomous PR push is an authorized
exception to that confirm (still never force, still never mainline).
Untracked `.plans/` (this repo, `*.local.md`) still opens the product-code PR
and says “lane move (untracked)”.
