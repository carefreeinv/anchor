---
title: A structured `## Progress` checklist for plan files
authors: [carefree]
tags: [feature, plans, workflow]
---

Plans that span multiple sessions — especially the ones a **human** is
assigned to complete — had no glanceable way to show step-level progress
between sessions. The plan template now carries a **`## Progress`**
checklist that `/draft` seeds and `/work` keeps in sync.

<!-- truncate -->

## The gap

The freeform `## Progress` note has existed for a while: `/work` writes one
on a mid-plan pause, and is told to "resume from the first incomplete step"
when one exists. Both instructions were vague — a prose note doesn't say
*which* step is incomplete, and there was nothing for a **human**-assigned
plan (`- **Assignee:** human`) to update between sessions of its own.

## What's there now

`anchor/templates/plan.md` gains a `## Progress` section right after the
header bullets:

```markdown
## Progress
- [ ] Step 1: <short label>
- [ ] Step 2: <short label>
- [ ] Step 3: <short label>
- [ ] Done when holds
```

One bullet per **Steps**-table row, plus a trailing `Done when holds`
bullet. `/draft` populates it **last** — after `## Steps` and `## Done when`
are actually written, so the checklist mirrors real content instead of
guessing ahead. Everything starts unchecked.

`/work` keeps it honest during execution: a Step bullet checks off once that
step's **Verify by** passes; `Done when holds` checks off right before the
`review-needed/` move; a mid-plan pause leaves unfinished bullets `[ ]`.
"Resume from the first incomplete step" is no longer vague prose — it's
literally the first `- [ ]` bullet.

## Advisory, not enforced

Nothing parses or gates on checklist state — no picker, no `/review`, no
`plan_fit.py`. It's a glanceable summary, not ground truth. It's also fully
optional: nothing in the existing backlog needs retrofitting, and a plan
predating this convention just doesn't have the section.

## Where it ships

- Claude: `.claude/commands/draft.md`, `.claude/commands/work.md`
- Grok: `.grok/skills/draft/SKILL.md`, `.grok/skills/work/SKILL.md`
- Docs: [`/draft`](/skills/draft), [`/work`](/skills/work)
- `.plans/README.md` documents the shape

No code changes anywhere — the checklist lives entirely inside `## Progress`,
so none of the existing heading-parsing (`GOAL_RE`, `DEPENDS_SECTION_RE`,
`check_plans.py`'s required-sections check) had to change.
