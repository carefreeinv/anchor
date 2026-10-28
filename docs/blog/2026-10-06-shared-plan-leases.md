---
title: "Plan leases now work across machines"
authors: [carefree]
tags: [feature, tooling]
---

Plan leases used to live in `.plans/.leases/`, which is gitignored and local to
one machine. Two developers sharing a remote could claim the same plan without
ever seeing each other's lease.

<!-- truncate -->

When the project has a git remote, a claim is now also published to an orphan
`leases` branch, as `leases/<slug>.json`. The publish happens before the plan
leaves `bugs/` or `features/`. If another clone already holds the plan, the claim
is refused and the plan stays in its ready lane. `plan_select.py --next` skips
plans leased elsewhere. The fast-forward push is the lock, so two simultaneous
claims produce exactly one winner.

See who holds what after a fetch:

```bash
python scripts/lease_branch.py --status
python scripts/lease_branch.py --status --json
python scripts/lease_branch.py --check-isolation
```

The branch holds nothing but lease files. It is never merged, and `/work`,
`/review` and `/release` never touch it. Writes use git plumbing, so your
checked-out branch, index and working tree are left alone.

With no remote, or one that is unreachable, claims fall back to the local lease
with a one-line warning. Set `ANCHOR_LEASE_STRICT=1` to refuse instead. Plans
named `*.local.md` are private and are not published unless
`ANCHOR_LEASE_PUBLISH_LOCAL=1`. `ANCHOR_LEASE_BRANCH=0` turns the layer off.

A lease belongs to an agent id *and* a host, so two machines that both use the default agent id never share or delete each other's claims; `ANCHOR_LEASE_HOST` overrides the host name if your machines share one. An expired shared lease on a **ready** plan (`bugs/`/`features/`) is reclaimable after a 5 minute clock-skew slack. An expired lease on `in-progress/` still needs an explicit recover. Keep hosts on NTP. The identity that pushes needs write access to the `leases` branch.
