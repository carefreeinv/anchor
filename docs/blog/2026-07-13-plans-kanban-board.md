---
title: A terminal kanban board for .plans/
authors: [carefree]
tags: [feature, tooling]
---

Your backlog was always readable with `ls`. Now it's readable at a glance.

<!-- truncate -->

**`scripts/plan_board.py`** renders a scaffolded project's `.plans/` tree as a live terminal kanban board — five columns, **Drafts | Ready | In Progress | Review Needed | Completed** — sorted the same way `/work` already picks: Priority, then Value, then oldest first. `Ready` merges `bugs/` and `features/`, with bugs always ranking first, exactly as bare `/work` does.

```bash
python scripts/plan_board.py               # live, redraws every 60s
python scripts/plan_board.py --once         # single frame, for piping/CI
python scripts/plan_board.py --include-parked --no-color
```

It's read-only — it never writes, moves, or edits anything under `.plans/` — and stdlib-only, so it copies standalone into any scaffolded project the same way `plan_select.py` and friends do.

**Two things make it more than a static `ls`:**

The header tracks rolling 7-day throughput: **Completed** and **Processed** (plans that entered the new `review-needed/` lane). A growing gap between the two is a visible sign of a human-review bottleneck, not something you'd notice from a flat directory listing. Where a `.plans/logs/` event log exists, the board reads it directly (exact, immune to clone/checkout mtime resets); otherwise it falls back to git commit time for tracked plans and filesystem mtime for private `.local.md` ones.

Each card also carries a brief label for the most recent event on record for its slug — "Completed", "Sent for review" — sourced from that same log, not from whatever column the card happens to sit in right now. If the two visibly disagree, that's a real signal, not something the board smooths over.

Cards animate briefly when they change column between refreshes, and column headers carry a color accent (green completed, yellow review-needed, orange in-progress, red everything else) — decoration only; the column name stays authoritative under `--no-color` or when stdout isn't a terminal.

Fresh scaffolds get `scripts/plan_board.py` automatically; existing projects pick it up on `anchor --upgrade`.
