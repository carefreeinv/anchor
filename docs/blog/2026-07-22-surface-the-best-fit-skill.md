---
title: "Agents now surface the best-fit skill before they start typing"
authors: [carefree]
tags: [doctrine]
---

The best feature in your toolchain is worthless if nobody knows the command for
it. A new doctrine rule closes that gap: before acting on a request, an Anchor
agent checks whether a skill or slash-command **already available in the session**
would do the job faster or more correctly — and if one clearly fits, it says so in
a single line and offers to use it, then gets on with the work.

<!-- truncate -->

## The rule

This lands as **mythos-core rule 14**, mirrored into the Claude Code standing
rules and the Grok Build hard rules so it holds on every model tier, not just the
frontier ones:

> Before acting on a request, judge whether a skill, slash-command, or feature
> available in this session would do it faster or more correctly than working by
> hand. If one clearly fits with a nameable benefit, prepend a single line naming
> it and offering to use it, then proceed with the request the same turn.

In practice that looks like one unobtrusive line before the agent dives in:

```text
Tip: this is what /work is for — want me to run it instead? Proceeding manually otherwise.
```

The user learns a feature exists at the exact moment it would have helped, without
having to read a command reference first. That's the whole point: passive
discovery of the cutting-edge, elusive features people otherwise never find.

## Why it needs guardrails

A nudge like this fails in two obvious ways — it invents commands that don't
exist, or it turns into a nag on every prompt. Rule 14 is built to do neither:

- **Available-only.** The agent suggests only a skill or command **actually
  loaded** in this session (the harness skill roster, `.claude/commands/`,
  `.grok/skills/`). It never names a command that isn't there and never invents a
  feature; when it isn't sure something exists, it stays silent. Hallucinating a
  `/command` is the sharpest failure mode, so it's the hardest limit.
- **Once per capability per session.** A given skill is surfaced at most once —
  and not at all if you're already using it or have waved it off.
- **Materially better only.** The tip fires only when the concrete win can be
  named in a few words. If it can't, the agent says nothing.

It is a **suggestion, not a gate.** The agent never blocks on it, never makes you
"run this first and come back" — it does the work you asked for on the same turn.
And it is deliberately *not* a pre-flight item: rule 13's fixed six-line block is
untouched, so the check adds discipline without adding ceremony.

## Where it lives

- `anchor/system-prompts/mythos-core.md` — rule 14 plus a new anti-pattern
  ("silently hand-doing what a purpose-built available skill is for without
  offering it once").
- `platforms/claude-code/CLAUDE.md` — standing rule for Claude Code projects.
- `platforms/grok-build/GROK.md` — hard rule 13 for Grok Build.
- [`/doctrine`](/doctrine) — the shipped-behavior write-up.
