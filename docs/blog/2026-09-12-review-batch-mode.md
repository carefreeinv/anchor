---
title: "/review --batch: work a queue faster, without a faster gate"
authors: [carefree]
tags: [feature, review]
---

`/review` has always reviewed exactly one plan per invocation — deliberately.
A backlog of several `review-needed/` plans still meant re-typing `/review`
between each one. `--batch [N]` removes that friction without touching the
one thing that actually matters: every plan still gets its own critic pass
and its own required sign-off.

<!-- truncate -->

## What doesn't change

Each item in a batch runs the *exact same* pipeline a solo `/review` runs:
checkout, evidence, a fresh-context AI critic with no memory of sibling
items, present, survey, follow-ups, merge, lane move. The survey is never
skipped and never inferred from earlier items — "the last two were Approve"
is not a reason to stop asking. Promotion review (the empty-queue `dev` →
`main` gate) is untouched; `--batch` never applies there.

## What's new

```bash
/review --batch          # up to 3 top-priority plans
/review --batch 5        # explicit cap
```

Before the first survey question, `/review` shows the whole batch — what's
in, and what got excluded and why. A plan is excluded (falls back to
single-item review) when it:

- carries a `## Handoff` **hold** note,
- has a large diff (more than 8 files, or ±300 lines net), or
- shares a touched path with another candidate in the same batch — the same
  conflict check `/work --batch`'s `batch_dispatch.py` already computes for
  parallel *execution*, reused here rather than reimplemented for review.

`--batch` refuses to combine with `--skip-ai` — skipping the fresh-context
critic across several plans at once is exactly the rubber-stamp risk this
mode exists to avoid.
