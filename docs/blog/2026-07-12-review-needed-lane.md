---
title: A review-needed lane between "done" and "completed"
authors: [carefree]
tags: [feature, docs]
---

Agent-claimed `Done when` and human-verified done were the same event. Now they don't have to be.

<!-- truncate -->

Every `.plans/` lane up to now was either **ready to execute**, **claimed**, **parked**, or **archived** — and the move from `in-progress/` straight to `completed/` was entirely self-certified: an agent decided its own `Done when` held, moved the file, and that was that. For low-stakes work that's fine. For anything a human wants eyes on first, there was no middle step.

**`review-needed/`** is that middle step. An agent that believes a plan's `Done when` holds can now `git mv` it from `in-progress/` to `review-needed/` instead of `completed/` — same as today's move, just a different destination when sign-off is wanted. From there:

- A **human** moves it on to `completed/` when satisfied.
- A **human** can send it back to `in-progress/` if changes are needed — the same agent (or another) picks it back up.
- A **human** can release/return it to `bugs/`/`features/` like any other parked work.

The one hard rule: **agents must never perform the `review-needed/` → `completed/` move themselves.** That's not a style preference — it's the entire reason the lane exists. Every doc surface that describes the agent move rule (`/work` for Claude and Grok, `.plans/README.md`, the doctrine and fleet-workers docs) states this as an explicit "never," not just an omission from the allowed-moves table.

`review-needed/` is never auto-picked or auto-executed by bare `/work`, the same as `ambiguous/`/`blocked/` — and it now counts as **open** work for `Depends on` checks, so a plan waiting on one sitting in `review-needed/` correctly treats it as unfinished rather than done.

Fresh scaffolds get `.plans/review-needed/` automatically; existing projects pick it up on `anchor --upgrade`.
