---
sidebar_position: 2
sidebar_label: Grok Build
---

<!-- synced-from: platforms/grok-build/GROK.md @ a0d6abd302208ee66cba5cdfd32d45f795081402 -->

# Grok Build

Install: place `platforms/grok-build/GROK.md` at your repo root; paste its session preamble into custom instructions if your Grok Build environment supports them.

## Grok's failure profile

Fast, eager, terse: it acts before planning, compresses reasoning it should show, and over-trusts first drafts. In long sessions it weights recent instructions over early ones, so discipline set at session start decays.

## The countermeasures

The eight hard rules (restate → plan → one-step-per-turn → verify-don't-claim → mark `(unverified)` → two-fail stop → scope → footer) plus three Grok-specific ones:

- Force risk enumeration before the plan ("list 3 ways this could go wrong") — surfaces the reasoning Grok skips.
- **One task spec per session.** Restart instead of accumulating context; instruction decay makes long Grok sessions untrustworthy.
- Architecture and security-adjacent steps are marked `Route to: bigger model` in the plan — Grok doesn't decide these alone.

## Grok 4.5 (reviewed 2026-07-08)

Play to the strength: terminal/CLI-driven steps are Grok 4.5's best fit (GPT-5.5-class on terminal benchmarks, unusually token-efficient). Compensate for the weakness: it measurably trails Fable/GPT tiers on repo-scale issue resolution, so decompose to file-scoped task specs before handing work over. API `reasoning_effort` defaults to *high* — set low for mechanical steps or pay a token multiple for nothing. Community-reported tool-use flakiness `(unverified)` makes external verification load-bearing. A poor-fit task gets a `SUGGEST-ESCALATE:` first line per the fit check in `anchor/model-fitness.md`, not a silent attempt.

If MCP is available, connect `anchor-prompts` and call `tune_prompt` on any vague task before starting, and `preflight_check` before executing any spec.
