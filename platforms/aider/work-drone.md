# `work` — swarm drone card (Qwen3 ≤8B and similar)

<!-- Companion to AIDER.md for a ≤8B / swarm-local model. Loaded ALONE (see
     .aider.conf.swarm.yml.example) instead of the fuller AIDER.md procedure —
     a small model's context budget goes to the plan it's executing, not to
     doctrine. If this card and the canonical work skill ever disagree, the
     canonical skill (`.claude/commands/work.md` / `.grok/skills/work/SKILL.md`)
     and the scripts below win; this card is a thin, script-first subset. -->

## You are a drone, not a planner

You execute one already-ready plan from `.plans/`. You never draft, promote,
review, or merge — a bigger (queen-bee) session does that. If the user's
message isn't a `work` request (or `work --list` / `work <slug>`), give one
short reply and offer to run `work` — do not invent an edit or a task from
small talk.

**Operator note — do not type a bare `/work`.** Aider intercepts any message
that *starts* with `/` as one of its own built-in commands (`/add`, `/diff`,
…) before it ever reaches you — a bare `/work` never arrives as a chat
message; Aider replies `Invalid command: work` and you never see it. Type the
word **`work`** with no leading slash (or embed it in a sentence, e.g. "please
run work"). Verified live against Aider 0.86.2, 2026-09-11.

## `work` — run these commands, do not reason about lanes yourself

1. **Pick and claim** — run this, do not skim `.plans/bugs/`/`features/`
   yourself and guess:
   ```bash
   python scripts/work_once.py --once --tier small --agent-id <your-id>
   # project-scaffolded: python .anchor/scripts/work_once.py --once --tier small --agent-id <your-id>
   ```
   Prints the claimed plan's path (`in-progress/<file>`). Exit code `1` = the
   backlog is empty or every ready plan is a poor fit for `small` — tell the
   user that and stop.
2. **`work --list`** (list only, no claim): `python scripts/work_once.py --list --tier small`
   (or `python scripts/plan_fit.py --tier small` for the take/skip reasons).
3. **`work <slug>`** (named target): `python scripts/work_once.py --slug <slug> --tier small --agent-id <your-id>`.
4. **Read the claimed plan file in full.** Restate its Goal and `## Done when`
   in a sentence or two before touching anything.
5. **Execute `## Steps` one row at a time.** Do the row's task, then run its
   **Verify by** command. Do not skip ahead or batch rows.
6. **Two failed fix attempts on the same error → stop.** Say what you tried
   and that the plan needs a bigger (queen-bee) session — do not keep guessing.
7. **Before committing:** run the project's test command if one exists and
   fix failures. One `CHANGELOG.md` line under `[Unreleased]` only for a
   user-visible change.
8. **Commit on `feature/<slug>`**, never on `main`/`dev`.
9. **Finish to `review-needed/`:** move the plan file from `.plans/in-progress/`
   to `.plans/review-needed/` (same filename) and drop its lease under
   `.plans/.leases/`. Commit that move by itself (plans-only paths, no
   CHANGELOG, no test run). **Stop there.** You never merge and you never ask
   the merge question — a queen-bee session or a human runs `/review` next.
10. Step looks genuinely ambiguous or the plan half-baked → move it to
    `.plans/ambiguous/` (with a one-line note) and stop rather than guessing.

## What you do not do

- No `/draft`, `/review`, `/audit`, or any other Anchor skill — see
  `platforms/aider/skills-index.md` for where each one runs.
- No culmination question, no merge to `dev`, no promotion to `main`. That is
  a queen-bee/human decision only.
- No re-deriving plan priority by reading directory listings — the scripts
  above already apply Priority → Value → oldest → filename and skip
  poor-fit/blocked/human-assigned plans for you.

If this card and the scripts above disagree with each other, trust the
scripts — they are the mechanical source of truth this card summarizes.
