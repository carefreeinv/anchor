---
sidebar_position: 5
sidebar_label: Generic Chat
---

<!-- synced-from: platforms/chat/CHAT.md @ 51867f6af6ba2ba846ec1f40d09002763074ee93 -->

# Generic Chat

Install: paste `platforms/chat/CHAT.md`'s session preamble into custom instructions
(if the product supports them) or as the first message of a session.

## ChatGPT / GPT-5.6 (reviewed 2026-07-08)

ChatGPT currently serves GPT-5.5 with an Instant Mini fallback that can vary the tier mid-session — restate constraints after quality shifts. The GPT-5.6 family (Sol/Terra/Luna) is strong at agentic coding `(unverified, vendor)`, but OpenAI's own system card documents a greater tendency to exceed user intent — unrequested actions and claiming unperformed work — which is exactly what the hard rules (verify-don't-claim, `(unverified)` marking, scope) exist to counter. Tier guidance: Terra for executor economics, Luna for tuner work, Sol only where its agentic edge is needed. Poor-fit requests get a `SUGGEST-ESCALATE:` first line per [model fitness](../model-fitness).

## The constraint that shapes everything here

No shell, file, or tool access — just conversation. Every "this works" claim is
unverifiable by the model itself, so the hard rules lean even harder on restate,
plan, one-step-per-turn, `(unverified)` marking, and a required
`## Result / ## How to verify / ## Deferred` footer, all addressed to the human
who will actually run and check things.

## /config without a shell

`/config` can't run `./config.sh` directly here. Instead the model asks which
platform(s)/fleet tooling the user wants plus their model priority (highest first,
e.g. `nim,grok,openai:gpt-5,claude:sonnet,claude:opus,claude:fable`), then hands
them the exact `./config.sh --platform <keys> [--fleet] [--model-priority <list>]`
command to run in their own terminal. Help: https://carefreeinv.com/anchor

## /commit-prep without a shell

Same split for preparing a commit: the human runs the commands and relays output,
the model does the judgment. Three gates, in order — (1) run & fix tests (the CI
set: ruff, pytest, docs-sync; fixes proposed as exact edits, two failed attempts on
one failure → stop), (2) dictate `CHANGELOG.md` entries under `## [Unreleased]` for
user-visible changes, (3) draft a `docs/blog/` post only if the change introduces
or significantly updates a user-facing capability. The model never tells the human
to commit — they decide when.
