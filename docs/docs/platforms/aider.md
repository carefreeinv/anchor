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

writes `AIDER.md` and `platforms/aider/skills-index.md` to the project root
plus a tracked `.aider.conf.yml.example` (never `.aider.conf.yml` itself —
host-specific values like `OLLAMA_API_BASE` stay in `.env`, gitignored). Copy
the example to `.aider.conf.yml` and Aider loads both into every session:

```yaml
read:
  - AIDER.md
  - platforms/aider/skills-index.md
```

`skills-index.md` is the roster: `/work` is the only Anchor skill Aider runs
in v1, and it lists everything else (`/draft`, `/review`, `/audit`, …) as
queen-bee-only, so a drone session points the operator back to Claude Code or
Grok Build instead of guessing at an unimplemented skill.

## Swarm profile: Qwen3 ≤8B and similar

`AIDER.md` and `skills-index.md` are sized for a mid-class model. A ≤8B local
model (the typical swarm-local default) runs out of context budget reasoning
about the full brief the same way it can run out of budget on a plain
`hello` — see [Local Models](/platforms/local-models) for the live canary.
For that profile, copy `platforms/aider/.aider.conf.swarm.yml.example` to
`.aider.conf.yml` instead of the default example:

```yaml
read:
  - platforms/aider/work-drone.md
edit-format: diff
map-tokens: 1024
timeout: 60
stream: false
```

It loads only `work-drone.md` — a script-first `work` card scoped to what a
small model can reliably follow (run `plan_fit.py` / `work_once.py` rather
than reasoning about plan lanes by hand) — in place of the fuller `AIDER.md`
and `skills-index.md`.

**Type `work`, not `/work`.** Aider treats any message starting with `/` as
one of its own built-in commands, so a bare `/work` never reaches the model —
Aider answers `Invalid command: work` itself. Type the word `work` with no
leading slash (or embed it mid-sentence).

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
