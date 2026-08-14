---
slug: dual-axis-model-fit
title: Dual-axis model fit — power and specialty
authors: [carefree]
tags: [routing, doctrine, fleet]
---

# Dual-axis model fit — power and specialty

Anchor’s fit check used to answer one question well: **is this model strong enough?** Mythos-core rule 11 and `model-fitness.md` sent weak-column and orchestration-class work up with `SUGGEST-ESCALATE`. That stopped silent overreach — but it did not catch the other failure mode: a model that is *strong enough* yet the **wrong kind of product** for the job.

## What shipped

Fit is now **dual-axis**:

1. **Power** — weak column, orchestration, under-tier → `SUGGEST-ESCALATE: <target> — <reason>`
2. **Specialty** — power OK, wrong computational/product profile → `SUGGEST-REROUTE: <target or profile> — <reason>`

Good fit on **both** axes means **silence** — no model pitch on every prompt.

Closed specialty profiles (v1): `coding-agent`, `terminal-agent`, `critic`, `planner`, `general-chat`, `multimodal`, `swarm-local`.

Example (lateral, not “pick Opus”):

```text
SUGGEST-REROUTE: coding-agent — leave multi-file software for a software-dev optimized model
```

`scripts/orchestrate.py` honors first-line `SUGGEST-REROUTE` the same way as escalate (no retry burn; `--insist` still forces proceed). Plans may list profile tags next to tiers in **Preferred models**; mechanical pickers still gate on tiers and names only — tags guide self-assessment. Optional `plan_fit.py --profile` adds a soft `specialty_hint` in JSON.

## Where to read it

- [Model fitness](/model-fitness) — protocol, profile table, per-model profiles
- [Doctrine](/doctrine) — right-size diagram includes specialty re-route
- Platform briefs: Claude Code, Grok Build, Chat, local models
