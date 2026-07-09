---
title: Plans, fleet workers, and inference savings
authors: [carefree]
tags: [feature]
---

Anchor now treats **tracked plans**, **durable fleet pullers**, and **honest inference economics** as first-class operator surfaces — not just doctrine on a shelf.

<!-- truncate -->

## Plans you can run

Scaffolded projects get a git-tracked **`.plans/`** tree. **Path is the status:** ready work lives in `bugs/` or `features/`; agents claim into `in-progress/`, park half-baked or stuck work, and archive to `completed/`. Drafts stay under `drafts/` until you promote them.

Use **`/draft`** to write, list, load, or promote a plan (optional `--local` for `*.local.md`). Use **`/work`** to execute the next fit ready plan — Preferred models and **Depends on** are honored so the wrong tier does not burn credits on the wrong job.

## Fleet without a central assigner

**`scripts/work_once.py`** is the headless companion to `/work`: claim with a lease, respect fit and dependencies, exit idle when the queue is empty. **`/fleet-watch`** (and `scripts/fleet_watch.py`) turns that into reboot-persistent multi-tier timers so mid, small, and reasoner workers each pull only what they should.

Docs live under **Tooling → Fleet workers** and **Skills → `/work`**, **`/draft`**, **`/fleet-watch`**.

## See the savings

The new **[Savings](/savings)** page sketches how the orchestrator pattern cuts API spend over a first year of adoption (with a realistic Q1 ramp), and when solar might help power always-on local boxes. Numbers are illustrative worksheets — plug in your own tokens and rates. Those savings can be significant; please consider [donating](https://donate.stripe.com/28E6oHeq8fxQ5p7fmBdjO01) to help support this project.

## Try it

```bash
./config.sh --platform claude,grok --fleet --orchestrator claude:opus
anchor /path/to/your-app
# then in the agent: /draft …  → promote when ready → /work
# durable pullers: /fleet-watch
```

Doctrine and platforms still apply: verify with tooling, escalate after two failures, and keep public docs about **shipped** behavior — not the private plan backlog.
