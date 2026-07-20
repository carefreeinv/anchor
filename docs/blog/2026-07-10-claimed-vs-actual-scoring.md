---
title: Claimed-vs-actual scoring for fleet models
date: 2026-07-10
tags: [fleet, verification, model-fitness]
---

# Claimed-vs-actual scoring for fleet models

Anchor already treats a model’s claim of success as an **input** to verification, not a substitute. That sentence now has a ledger.

When `orchestrate.py` finishes a task, it pairs the executor’s `## Result` footer (parsed as `success`, `should-work`, `blocked`, or `unparseable`) with the actual verify exit code and optional scope-gate verdict. Each row lands in `var/fleet-metrics/outcomes.jsonl` — metadata only (model, tier, task id hash, claim, exits). No prompts or task bodies.

Aggregate with:

```bash
python scripts/fitness_report.py
python scripts/fitness_report.py --json
```

You get per-model claim accuracy, verify pass-rate, and unparseable rate. Rates with fewer than five samples are withheld so a lucky streak does not look like a routing policy.

`model-fitness.md` is still human-edited prose. The report is the preferred evidence when you update that file — vendor leaderboards stay priors until your own fleet data says otherwise.
