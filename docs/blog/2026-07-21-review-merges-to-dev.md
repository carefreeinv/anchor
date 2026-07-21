---
title: /review lands features on dev — and can promote dev to main
authors: [carefree]
tags: [feature, tooling, skills]
---

Signing off a plan used to archive it and leave the branch for later. Now Approve *is* the integrate step.

<!-- truncate -->

**`/review` Approve** still runs the AI critic and human survey. What changed is the finish:

1. Merge `feature/<slug>` into the integration branch (`dev`, else `develop`; create `dev` from mainline if needed).
2. Only then move the plan `review-needed/` → `completed/`.
3. On merge conflict: abort, leave the plan in `review-needed/`, report the files — no silent partial land.

When the queue is empty and `dev` is ahead of `main`, bare `/review` (or `/review --promote`) runs a **promotion review**: log + shortstat for `main..dev`, optional AI pass, survey **Promote to main** / Skip. Promote merges integration into mainline. One decision per invocation — plan Approve never auto-chains into promotion.

Guards stay tight: survey is the only merge authorization, never force-push, push to `origin` only with confirm or `--push` after local success. **`/work` still never merges**; executors commit on the feature branch and finish to `review-needed/` as before.

`scripts/pending_merges.py` remains the advisory safety net for branches that somehow never landed.
