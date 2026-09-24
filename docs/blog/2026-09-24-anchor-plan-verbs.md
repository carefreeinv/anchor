---
title: "anchor work, anchor review: the plan workflow without a chat harness"
authors: [carefree]
tags: [feature, tooling]
---

Until now the `.plans/` workflow (pick a ready plan, claim it, finish it, review
it, land it) ran inside a coding agent's slash commands, or headless through
`work_once.py`. The `anchor` command now runs it from a plain terminal:
`anchor plans`, `anchor work`, `anchor review`, `anchor draft`. None of them
runs a model unless you ask.

<!-- truncate -->

## Deterministic by default

Picking, claiming, lane moves, dependency and fit checks, and the merge gate
follow from the files on disk and git alone, so the CLI does them directly by
calling the scripts that already own those rules. It has no copy of the lane
priority or fit logic of its own.

```bash
anchor work --list --tier mid        # ready plans, your fit, unmet deps
anchor work --agent-id me            # claim the top fit plan (move + lease)
anchor work --finish my-plan --agent-id me   # → review-needed/
anchor review my-plan                # package, then Approve / Needs Work / Skip / Defer
anchor draft new-idea --goal "…"     # skeleton in drafts/
anchor draft --promote new-idea --to features
```

Steps that need judgment come back as named `pending` items rather than being
skipped quietly: `execute` after a claim, `critic` before a review decision,
`plan-prose` for a new draft. In an interactive terminal, `--delegate
[ENDPOINT]` sends the critic pass or the draft prose to an endpoint from your
`endpoints.yaml`.

## Safe for agents to call

The same verbs serve an agent inside Claude Code, Grok Build or Aider. When
stdin or stdout is not a terminal, or you pass `--non-interactive`, the CLI
never prompts, always prints schema-v1 JSON, never merges, and never starts a
model of its own; the calling agent is already the model. A step that needs an
operator's answer, such as a review decision, exits `3` and names the answer.
No flag supplies that answer, so an unattended run can't approve its own work.

## Merges stay gated

`anchor review` merges only after you answer **Approve** in the terminal. It
fast-forwards onto `dev`/`develop` through `merge_feature.py`'s gate, pinned to
the head you were shown, and never touches `main`. A merge that would need a
merge commit stops and points you at `/review`, because that tree needs
`/commit-prep` first. That holds even when `dev` moves while you're deciding:
the fast-forward is checked again at the moment of merging, and if it fails
nothing is left staged. If a delegated critic says REVISE, Approve asks once
more before it merges anything.

## Also in this change

- Every workflow script now reaches `.plans/` through `scripts/plan_store.py`,
  so a future plan layout changes one module instead of a dozen.
- `bin/anchor` works when symlinked onto `PATH`, the way `/install-anchor`
  installs it.
- `pip install -e .` now ships every module `anchor` imports.

Full contract, including exit codes and `--help` for each verb:
[Plan workflow verbs](/tooling/plan-verbs).
