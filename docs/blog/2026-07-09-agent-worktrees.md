---
title: Parallel agents get their own git worktrees
authors: [carefree]
tags: [feature, tooling]
---

Multiple agents on one repo no longer have to fight over a single `HEAD`. Each
worker can own a **git worktree** under `var/worktrees/<agent-id>/`.

<!-- truncate -->

Plan leases already decide *which* plan an agent owns. They do not give each
agent its own checkout. **One working tree means one branch tip** — so parallel
code edits on a shared clone thrash.

**`scripts/worktree_for_agent.py`** creates or reuses a worktree per `--agent-id`:

```bash
python scripts/worktree_for_agent.py ensure \
  --project /srv/myapp --agent-id mid-1 --slug fix-login
# → WORKTREE=…/var/worktrees/mid-1
# → BRANCH=feature/fix-login
# → INTEGRATION=dev

# or after a claim:
python scripts/work_once.py --once --tier mid --agent-id mid-1 --ensure-worktree
```

The helper ensures an integration branch (**`dev`**, else **`develop`**; if
neither exists it **creates `dev` from `main`/`master`**), then checks out
`feature/<slug>` inside that agent’s tree. Edit only under `WORKTREE=`. Run
**`/commit-prep`** before commit; push the feature branch only — never auto-merge
to `dev`/`main`.

Scaffold and project config (`anchor …`, `--set-orchestrator`) now **create
`var/` + `var/worktrees/`** and append **`var/`** to the project’s root
`.gitignore`, so local worktrees stay untracked.

Full isolation notes: [Fleet workers](/tooling/fleet-workers).
