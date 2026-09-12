---
title: "Fix: Aider's /work trigger never reached the model"
authors: [carefree]
tags: [bugfix, aider]
---

`AIDER.md` — the drone brief `anchor --platform aider` scaffolds into every
Aider project — has told operators since it shipped to type a literal
`/work` to start the drone procedure. That instruction was wrong: Aider
intercepts any chat message starting with `/` as one of its own built-in
commands and replies `Invalid command: work` without ever calling the model.
A bare `/work` never reached the LLM, on any model size.

<!-- truncate -->

## What was broken

This surfaced during live testing of the Aider swarm drone card
(`work-drone.md`, `skills-index.md`), which had already been corrected to
say "type `work`, no slash." `AIDER.md` itself — the brief every Aider
scaffold ships, regardless of model size — still carried the original wrong
instruction, because the plan that first shipped it verified `.aider.conf.yml`
config syntax against Aider's docs but never actually typed `/work` into a
live Aider session.

## The fix

`AIDER.md` and its docs mirror now say to type the word **`work`**, with no
leading slash (or embedded mid-sentence — anything not starting with `/`).
Verified live against Aider 0.86.2: a bare `/work` still gets
`Invalid command: /work` from Aider itself (unchanged, correct Aider
behavior — this was a documentation bug, not an Aider bug), while `work` or
`work --list` reaches the model.

If you scaffolded a project with an earlier `anchor --platform aider`,
re-run the scaffold (or hand-edit `AIDER.md`) to pick up the fix.
