---
title: Plans get release grouping
authors: [carefree]
tags: [feature, plans, work, review]
---

A large `.plans/` backlog has no notion of which pieces of work ship
together. `/work` picks the highest-priority plan and nothing else, and
there's no signal for "this cluster of plans is done — go ship it." Plans can
now point at a named **release**, and `/work`/`/review` notice when one is
fully done.

<!-- truncate -->

## Plans point at releases, not the other way around

A plan may carry an optional header:

```markdown
- **Release:** local-inference-optimizations
```

`.plans/.releases/local-inference-optimizations.md` holds only release-level
metadata — a `Status` (`open` / `ready` / `shipped`) and an optional
`Target` version — and **never** a list of member plans. Membership is
always computed by scanning every plan's `Release:` field. The design went
through two iterations before landing here: a release file enumerating
member slugs (mirroring the existing `.plans/.leases/` convention) seemed
natural at first, but a release's membership grows continuously as new plans
join it, and a static list drifts out of sync the moment that happens. A
self-declaring pointer never needs a second file edited.

## A soft nudge, never a priority override

`/work`'s ready-lane picker now gives a plan in the release closest to
complete a small edge — but strictly as a tiebreaker inserted between
`Priority`/`Value` and the existing oldest-file tiebreak. A `P1` plan always
beats a `P2` plan regardless of release completeness, full stop; the bias
only decides between two otherwise-equal plans. And it only kicks in for
releases that are genuinely close to done — a release 10% complete doesn't
outrank an untagged plan either.

## One prompt, not a nag

When every plan pointing at an `open` release has reached `completed/`,
`/work` or `/review` ask once, interactively: *"Release `<name>` is fully
complete — prepare it for deployment?"* — offering to hand off to the
existing `/release` skill, never running it automatically. The release then
flips to `ready` so the question doesn't repeat. If a new plan later joins an
already-`ready` release, the next check flips it back to `open` on its own,
no prompt, so the completion question surfaces again once it's genuinely
done.

## What ships

```bash
python scripts/release_progress.py --list
v0.3.0                            open     12/17 complete (5 remaining)
```

`--status <slug>` gives the member breakdown; `--json` for tooling. A plan
pointing at an undefined release slug is reported as `unknown-release`
rather than silently dropped or counted toward a phantom "complete" release.
