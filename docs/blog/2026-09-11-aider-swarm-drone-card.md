---
title: A thinner drone card for Qwen3 on Aider — and a real invocation bug
authors: [carefree]
tags: [feature, skills, tooling, bugfix]
---

The Aider drone brief (`AIDER.md`) and its skills index are sized for a
mid-class model. A ≤8B local model — Qwen3 4B in particular, Anchor's default
swarm-local pick — doesn't have the context budget to reason about either one
reliably: a live canary from a 2026-09-08 session shows a plain `hello`
sending a 4B model into a 600-second confusion loop, treating Aider's own
edit-format rules as the task. `anchor --platform aider` now also scaffolds a
thinner, script-first card built for exactly that class of model — and along
the way, live testing turned up a real bug in how the whole Aider platform is
invoked.

<!-- truncate -->

## A ≤1-screen card, not a bigger prompt

`platforms/aider/work-drone.md` is 60 lines: pick and claim a ready plan by
running `work_once.py`/`plan_fit.py` (never by reasoning about `.plans/`
lanes by hand), execute the claimed plan's Steps one row at a time, finish to
`.plans/review-needed/`, never merge. It pairs with a new
`.aider.conf.swarm.yml.example` that loads *only* that card — not the fuller
`AIDER.md` brief or the skills-index roster — and trims the request itself:
`diff` edit format instead of whole-file rewrites, a capped repo-map, a 60s
per-call timeout, streaming off. Every key in that config was checked against
a live `aider --verbose` dump on the actual installed binary (Aider 0.86.2),
not assumed from memory.

## The bug: Aider eats `/work` before the model ever sees it

Testing the new card against a real Ollama endpoint surfaced something more
fundamental than a slow model: Aider treats *any* message starting with `/`
as one of its own built-in commands. Type a bare `/work` and Aider answers
`Invalid command: work` itself — the LLM is never called. This affects every
Aider platform file shipped so far, for every model size, not just small
ones; `AIDER.md` still tells operators to treat literal `/work` as the
trigger. The two files this plan owns now say what actually works instead:
type the word `work`, with no leading slash. `AIDER.md` itself needs the same
fix as a follow-up — it wasn't in this change's scope to touch.

## An honest partial

The card's mechanics — claim, list, thin context loading, correct invocation
syntax — are all verified live and working. A full interactive round-trip
(the model actually replying) is not: on this WSL2 + Windows-host-Ollama
profile, even a trivial message without any drone-card context still failed
to complete within a 60-second cap via Aider, while the same Ollama endpoint
answered a comparable prompt over raw `curl` in under 12 seconds — litellm
retries a timed-out call automatically, so a per-attempt cap doesn't bound
the total wait the way it looks like it should. That gap is documented as an
open question rather than papered over. "Interactive 4B stays hopeless on
this class of host" was always a named risk for this work, with the fallback
already built: `work_once.py` for unattended execution.
