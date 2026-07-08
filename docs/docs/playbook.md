---
sidebar_position: 2
---

# The Playbook

The operator playbook for a credit-metered frontier model, generalized beyond any one vendor. The premise: frontier models are becoming **metered utilities**, so the operator skill is knowing which tasks deserve frontier pricing and routing everything else to models that are already good enough.

## The five moves

**1. Reserve the frontier model for long-horizon work only.** Its edge is autonomy over hours, not intelligence per prompt. One-session, one-file tasks never touch it.

**2. Run the orchestrator pattern.** The frontier model reads the codebase, writes the plan, decomposes it into task specs. Cheaper models execute each spec. The frontier model reviews the merged result. It touches the project exactly twice — you pay credit prices for judgment, not keystrokes. Commit ready plans under **`.plans/`** and start executors with [**`/work`**](skills/work) (or `orchestrate.py --plan-file`) so handoff is file-based, not chat archaeology.

**3. Tune prompts on a cheap model first.** A sloppy prompt costs the same as a great one. Have a cheap model rewrite every task into a spec with acceptance criteria, files in scope, and a definition of done. Three attempts at a task is the silent budget killer; one tuned attempt is the fix. (`scripts/prompt_tuner.py`)

**4. Don't pay the classifier tax.** Security-adjacent work may get rerouted by safety classifiers anyway — route it yourself to the model you'd be rerouted to, and save the credits.

**5. Benchmark your real workload.** Don't take routing tables on faith — run your own tasks across your own tiers and let pass-rate and latency decide. (`scripts/benchmark.py`)

## Why this matters double for Anchor

The playbook's economics assume "cheap model" means Sonnet. Anchor pushes it further down: the same orchestration discipline lets a swarm of cheap, always-on workers do the keystrokes. And the discipline that saves money on frontier credits is *the same discipline* that makes small models reliable at all — small models don't fail because they lack knowledge for scoped tasks; they fail because nothing imposes process on them. Impose it, verify externally, and an 8B model executing a well-cut task spec is indistinguishable from a much bigger model on most of your backlog.

The uncomfortable truth holds here too: for a typical build, ~80% of the work never needed the big model. Anchor exists to make that 80% run on hardware you own.
