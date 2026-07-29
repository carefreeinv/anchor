---
title: "/deploy now flags an unpromoted dev branch before shipping"
authors: [carefree]
tags: [feature, fix, tooling]
---

`/deploy` publishes from a project's deploy branch (usually `main`). If `dev`
has commits not yet promoted there, deploying silently shipped whatever
`main` happened to have — even if newer, already-reviewed work was sitting
one merge away. `/deploy` now checks for that gap and asks first.

<!-- truncate -->

## The gap

`/review` Approve merges a feature branch into `dev`; a separate **Promote**
step lands `dev` on `main`. Nothing connected that second step to `/deploy` —
an operator could run `/deploy` right after a `/review` Approve and ship the
previous state of `main`, with the just-reviewed work sitting unpublished on
`dev` the whole time.

## What changed

Early in the pipeline, right after the tree/branch gate, `/deploy` now
compares `dev` (or `develop`) against the branch it's about to publish:

```bash
git rev-list --count <deploy-branch>..dev
```

No integration branch, or nothing ahead → silent, no change in behavior. A
non-zero count reports the gap (commit count + short log) and asks:

| Option | Meaning |
|--------|---------|
| **Run `/review` first** | Stop; promote `dev` → deploy branch, then re-run `/deploy` |
| **Deploy as-is** | Proceed; `dev`'s unpromoted work stays unpublished |
| **Cancel** | Stop, no deploy |

Under `--yes`, it defaults to **deploy as-is** rather than blocking on a
question nothing can answer in a non-interactive run.

## Still never merges

`/deploy`'s existing boundary is unchanged: it does not commit, merge, or
promote branches itself. This check only **surfaces** the gap — landing
`dev` is still exclusively `/review`'s job. Nothing new was granted to
`/deploy`'s outward-facing capability, just a heads-up before it uses the
one it already had.
