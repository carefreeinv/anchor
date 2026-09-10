---
title: Aider joins Anchor as a drone-only platform
authors: [carefree]
tags: [feature, skills, tooling]
---

Anchor's scaffold has covered Claude Code and Grok Build for a while — both
harnesses with a real slash-command runtime, so a scaffolded project gets the
full skill suite (`/work`, `/draft`, `/review`, and the rest). Aider is
different: it's usually the harness running a small local model, and it has
no slash-command runtime to hook into. `anchor --platform aider` now
scaffolds it anyway, with a brief scoped to what that actually calls for.

<!-- truncate -->

## Queen-bee plans, drone executes

A small local model is a fine executor and a poor architect. Rather than
pretend Aider sessions can safely draft, review, or merge plans, the new
`AIDER.md` brief gives them exactly one job: run **`/work`** against a plan a
bigger session — Claude Code, Grok Build, or a human — already made ready.

Since Aider has no slash-command parser, the brief teaches the model to treat
the literal text `/work` as an instruction to follow a condensed procedure
itself: pick the highest-priority ready plan, claim it into
`.plans/in-progress/`, execute its Steps, run the project's tests before
committing, commit on a feature branch, then hand off to
`.plans/review-needed/` and stop. A drone never merges, and it never asks the
merge question `/work` asks in a full harness — that judgment call stays with
a queen-bee session.

## What ships

```bash
anchor <project-dir> --platform aider
```

writes `AIDER.md` to the project root and a tracked
`.aider.conf.yml.example` — copy it to `.aider.conf.yml` and Aider loads the
brief into every session automatically:

```yaml
read: AIDER.md
```

Host-specific values like `OLLAMA_API_BASE` stay out of the tracked example
and belong in a gitignored `.env`, same as every other local-model config in
Anchor.

The brief also points a drone at the fleet probe
(`fit_device.py --probe`) so it defaults to the memory-safer model fit on
constrained hardware rather than the largest model that only theoretically
fits — the same **Default for wire** vs **Max fit** split `/local-models`
already reports.

## What's next

This is deliberately the thin layer: a brief and a scaffold entry, not a full
skills port. A follow-on plan will bridge Anchor's slash skills into Aider's
prompt loop more directly so a drone session can run more than `/work` alone.
