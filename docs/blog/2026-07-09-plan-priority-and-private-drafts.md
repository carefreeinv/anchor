---
title: Priority-ordered plans, and drafts that stay private by default
authors: [carefree]
tags: [feature, tooling]
---

Two refinements to the `.plans/` workflow: ready plans can now carry an explicit
**`Priority`** that orders them ahead of the coarse `Value` field, and **fresh
drafts are private by default** so a half-baked plan never lands in a commit
before you mean it to.

<!-- truncate -->

## Priority orders the backlog

`Value: high | medium | low` was the only lever for ordering ready work, and it's
blunt — most plans end up "high," so ties fell back to filename. Plans now take a
**`Priority`** header:

```markdown
- **Value:** high
- **Priority:** P1        # P1 > P2 > P3; default P2; orders within a lane
```

Selection — everywhere it happens: interactive [`/work`](/skills/work),
headless `scripts/work_once.py`, and the fleet pullers — now follows one order:

> your in-progress → **bugs before features** → **Priority (P1 → P2 → P3)** → Value → oldest first

Lane precedence still wins: a `P1` feature never jumps a `P2` bug. Priority only
sorts *within* a lane. Anything without the header is treated as `P2`, so existing
plans keep their relative order. The parser is tolerant — `P1`, `p1`, or bare `1`
all read the same — and `work_once.py --list` grew a `priority` column so you can
see the queue the way a worker will:

```bash
python scripts/work_once.py --list --tier mid --agent-id worker-1
# path                       lane      priority  value  preferred  fit   …
# features/scope-diff-gate.md features  P1        high   mid        good  …
```

## Drafts are private until you promote

A fresh draft is a thought in progress, not a shipped artifact — and it shouldn't
be committable by accident. `/draft` now writes new plans as **`<slug>.local.md`**
by default, which `.plans/.gitignore` keeps untracked:

```bash
/draft fix flaky login test      # → .plans/drafts/fix-flaky-login-test.local.md (private)
```

Promotion is the moment a plan becomes real, so that's where it gets published:

```bash
/draft --promote fix-flaky-login-test   # → .plans/features/fix-flaky-login-test.local.md (still private)
```

**Update:** the `.local` suffix is **sticky** — promote and agent lane moves keep
the same basename. Agents never drop `.local`. Only a **human manual rename**
(or create with `/draft --shared`) makes a plan git-tracked. The earlier
“drop `.local` on promote” rule is withdrawn.

Nothing changed about the tree itself — `.plans/` is still tracked, and
`*.local.md` is still the private-plan suffix in any lane. What changed is the
*default*: you now opt **in** to committing a draft, instead of opting out.
