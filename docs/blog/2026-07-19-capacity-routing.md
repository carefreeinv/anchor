---
title: When the subscription runs out, that's a scheduling problem
authors: [carefree]
tags: [feature, docs, fix]
---

Subscription tiers ration capacity, not just tokens: a session cap, a rolling
window, a weekly quota. Anchor now has doctrine for what an agent does when it
hits one — and a `/commit-prep` that actually ships to your projects.

<!-- truncate -->

## The failure that looks like success

An agent that hits a usage limit and gives up wastes your afternoon. An agent that
hits one and quietly finishes the job on a weaker model wastes something worse,
because the work *looks* done. The second failure is the dangerous one, and it is
increasingly common in harnesses that silently downgrade your tier mid-session
rather than stopping.

**`anchor/capacity-routing.md`** is the doctrine, scaffolded into every project as
`.anchor/capacity-routing.md`. It first separates a **capacity** limit from a
**transient** one: a per-minute rate limit resolves with one backoff and a retry, a
weekly cap does not. If the error names a reset hours or days out, retrying it in a
loop buys nothing but wall-clock and log noise.

Then it works a fixed order — **reroute**, else **wait**, else **stop and report**,
always after checkpointing to the in-progress plan.

## Reroute is gated on a fitness floor

This is the part that matters, and the part a naive implementation gets wrong.

Model priority is an **escalation ladder, not a menu of equals**. Rerouting a
rename or a formatting pass down a tier costs nothing. Rerouting architecture work,
a security review, or a subtle debugging session down a tier produces confident,
wrong output — precisely the failure Anchor exists to prevent. So the rule consults
[model fitness](/model-fitness): if the task lands in the fallback model's weak
column, **waiting is the correct answer**, and so is stopping.

A quota reset never sets the quality bar.

Rerouting also requires restating the work, because a different model is a
different session with no memory of this one. Re-sending the last prompt loses the
plan, the constraints, and every decision already made. So a reroute checkpoints
first, restates the task spec on arrival, names the tier it moved to, and
re-verifies inherited claims rather than trusting them — anything unverified stays
`(unverified)` across the handoff.

The hard limits: never continue on a silently downgraded tier, never narrow scope
or weaken tests to beat a cap, never fabricate completion. Partial work reported
honestly beats a claimed finish.

This pays off most in multi-provider harnesses — Cursor, Cline, OpenRouter-backed
tools, or an `endpoints.yaml` fleet — where a second model is one config line away.

## `/commit-prep` now actually reaches your projects

While wiring the above, a related gap turned up. `CLAUDE.md` and `GROK.md` have
long required `/commit-prep` before any `git commit`, and `/work` calls it. But the
command was missing from the scaffold's platform map — so scaffolded projects were
instructed to run a command they had never received. Grok's only copy sat at an
abandoned path, unused since Grok moved to `.grok/skills/*/SKILL.md`.

Both now ship, covered by a test that asserts it:

```bash
anchor /path/to/project --platform claude,grok
ls /path/to/project/.claude/commands/commit-prep.md
ls /path/to/project/.grok/skills/commit-prep/SKILL.md
ls /path/to/project/.anchor/capacity-routing.md
```

The command body was also rewritten to be project-agnostic **by discovery rather
than by assumption**. It treats your CI config as the authority on what "green"
means, falling back to a task-runner target, then the language's default runner. It
matches whatever release-note convention you already use — and when your notes are
*generated* from Conventional Commits or PR labels, it tells you the entry belongs
in the commit message instead of hand-editing a generated file. It follows an
existing blog directory's conventions, or writes plain Markdown under `docs/blog/`
with no static-site generator required.

Every gate can skip with a one-line note. A pre-commit pass should never scaffold a
test suite, a changelog, or a blog your project never asked for.
