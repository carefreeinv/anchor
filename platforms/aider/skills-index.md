# Aider skills index (drone, v1)

<!-- Companion to AIDER.md — loaded via `read:` alongside it. AIDER.md carries
     the full drone brief and a condensed `/work` procedure (Aider has no
     slash-command runtime and no on-demand file-read tool, so the procedure
     has to already be in context, not fetched from the canonical skill file
     when `/work` is typed). This file is the roster: which Anchor skills
     Aider actually runs, and where everything else lives. -->

## Implemented here

| Command | Behavior |
|---------|----------|
| `/work` | Follow the `/work` procedure in `AIDER.md`. Optional slug: `/work <slug>`. Optional `/work --list`: report ready plans (path, Priority, Value) without claiming or executing one. |

That is the only skill this brief implements. It mirrors the canonical work
skill (`.claude/commands/work.md` / `.grok/skills/work/SKILL.md`): same lane
rules, same lease/claim, same finish-to-`review-needed/`-and-stop with no
merge. If a ready plan needs judgment this brief doesn't cover, stop and say
so rather than guessing — don't improvise a third version of `/work`.

## Not implemented here — cloud/queen-bee only

Everything else Anchor ships is a **queen-bee** skill: planning, review, and
anything that inspects or changes more than the one plan `/work` is executing.
If the operator asks for one of these in Aider, say it runs in a queen-bee
session (Claude Code or Grok Build) and offer `/work` on whatever is already
ready instead:

| Command | Where it runs |
|---------|----------------|
| `/draft` | queen-bee — plans are authored on the cloud/orchestrator side |
| `/review` | queen-bee — human sign-off + AI critic pass |
| `/audit` | queen-bee — exhaustive security pass, reasoner/frontier only |
| `/optimize` | queen-bee — standards survey against the whole project |
| `/commit-prep` | folded into `/work` step 5 here (tests + light CHANGELOG); the full skill's blog judgment call stays queen-bee |
| `/deploy` | queen-bee |
| `/release` | queen-bee |
| `/tag` | queen-bee |
| `/push` | queen-bee |
| `/fleet-watch` | queen-bee |
| `/install-anchor` | queen-bee |
| `/config` | queen-bee |
| `/local-models` | queen-bee — probing/recommending models is a setup step, not a drone task |
| `/anchor` | queen-bee — scaffolding other projects |

## Scope creep

Do not implement any of the above here just because the operator asks
convincingly. If a ready plan's Steps genuinely require one of them mid-`/work`
(for example, a plan step says "run `/commit-prep`"), do the narrow thing that
step actually needs (run tests, one CHANGELOG line) rather than pulling in the
full skill — and if that's not enough, stop and name the plan as needing a
queen-bee session, per `AIDER.md`'s two-failed-attempts rule.
