---
sidebar_position: 6
sidebar_label: Aider
---

<!-- synced-from: platforms/aider/AIDER.md @ ac45c7625b6df94b68bcdda4170ae664944ed9f4 -->

# Aider

Aider sessions are usually a small local model (Qwen3 4B/8B class) run through
Ollama or llama.cpp — cheap and fast, but not the model that should be making
architectural calls. Anchor treats Aider as a **drone harness**: it runs
`/work` against plans a bigger session already made ready, and nothing else.

## Queen-bee plans, drone executes

- **Queen-bee** (Claude Code, Grok Build, or a human) writes plans into
  `.plans/drafts/` and promotes them to `.plans/bugs/` or `.plans/features/`.
- **Drone** (Aider) only runs `/work` against an already-ready plan — it does
  not draft, promote, review, or merge.

Aider has no slash-command runtime, so `AIDER.md` teaches the model to treat
the literal text `/work` as an instruction to follow a condensed version of
the [`/work`](/skills/work) procedure itself: pick a ready plan by priority,
claim it into `.plans/in-progress/`, execute its Steps one at a time, run the
project's tests before committing, commit on `feature/<slug>`, then finish to
`.plans/review-needed/` and stop — a drone never merges and never asks a
merge question. If the user types `/draft`, `/review`, or anything else
Anchor-shaped, the brief points them back to a queen-bee session instead.

## Config: always load the brief

```bash
anchor <project-dir> --platform aider
```

writes `AIDER.md` to the project root plus a tracked
`.aider.conf.yml.example` (never `.aider.conf.yml` itself — host-specific
values like `OLLAMA_API_BASE` stay in `.env`, gitignored). Copy the example to
`.aider.conf.yml` and Aider loads the brief into every session:

```yaml
read: AIDER.md
```

## Memory-safe local default

`AIDER.md` points at the fleet probe (`fit_device.py --probe`) so a drone
picks the **Default for wire** model — the memory-safer fit under real free-RAM
pressure — rather than the largest model that only theoretically fits the
box's total RAM. See [Local Models](/platforms/local-models).

## Tracked plans

Same `.plans/` contract as other platforms, with one restriction: a drone
session claims ready work and finishes to `review-needed/`, but never drafts,
promotes, or merges — that stays with a queen-bee session or a human running
`/review`. **Docs describe current state, not plans** — never write product
docs from `.plans/` contents; document shipped code only.
