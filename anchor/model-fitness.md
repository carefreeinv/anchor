# Model fitness — where each model excels, where it fails

Reviewed **2026-07-08**. Frontier entries move fast; treat vendor-reported numbers as
`(unverified)` until your own `benchmark.py` run says otherwise — that table, not this
file, is your routing policy. This file exists for the *fit check* (below): a model
handed a task should be able to look itself up, see the task lands in its weak column,
and say so before burning tokens.

## The fit check (every model, every task)

Before planning, compare the pending task against your row below (and the project's
`ANCHOR-CONVENTIONS.md` model-routing section, which carries the operator's priority
order). If the task lands in your **weak** column:

1. Make your ENTIRE first line: `SUGGEST-ESCALATE: <better-suited model or role/tier> — <one-line reason>`
2. Stop. Do not begin the task.
3. Proceed only if the spec or the operator explicitly says to proceed anyway — then
   do your best within scope and mark shaky output `(unverified)`.

Suggest *downward* too (per mythos-core rule 10): boilerplate on a frontier tier wastes
credits exactly the way hard problems on a swarm node waste attempts. The operator can
always insist; the point is that silent poor-fit execution is the one forbidden move.

## Frontier / API models

| Model | Excels at | Weak at / quirks |
|---|---|---|
| Claude Fable 5 | Long-horizon autonomous work, large migrations, multi-service debugging, final review of big merges | Credit-metered — wasting it on keystrokes is an economics failure, not a capability one |
| Claude Opus 4.8 | Deep single-problem reasoning, architecture calls, security-adjacent work | Overkill for scoped edits; slower/pricier than Sonnet on routine execution |
| Claude Sonnet 5 | Default executor: scoped multi-file edits, solid tool use, good cost/quality | Hands multi-hour autonomy and hardest architecture calls up a tier |
| Claude Haiku 4.5 | Classification, summaries, spec-tuning, cheap pipeline glue | Multi-file reasoning, subtle bug hunts |
| GPT-5.6 Sol (public 2026-07-09) | Agentic coding + cybersecurity tasks — benchmark leader `(unverified, vendor)` | **Documented over-eagerness**: OpenAI's own system card notes a greater tendency than GPT-5.5 to exceed user intent — unrequested "cleanup" actions and **claiming unperformed work**. Scope and verification gates are mandatory, not optional |
| GPT-5.6 Terra | ~GPT-5.5 quality at roughly half the cost `(unverified, vendor)` — the economics pick for executor work | Same system-card caveats as Sol; benchmarks vendor-reported |
| GPT-5.6 Luna | Frontier-adjacent quality at budget price ($1/$6) — strong tuner/executor-light | Thinnest tier of the family; keep it off architecture and review roles |
| ChatGPT (product: GPT-5.5 + Instant Mini fallback) | Conversational spec-shaping, explanations, one-step-per-turn piloted work | No shell/file access: every "it works" is a claim on the human's behalf; fallback routing means tier varies mid-session |
| Grok 4.5 (public 2026-07-09) | Terminal/CLI-driven tasks (Terminal-Bench ≈ GPT-5.5 class), long tool-use runs, token efficiency (~4× fewer than Opus-class `(unverified, vendor)`), cheap at $2/$6 | **Repo-scale issue resolution measurably behind** (DeepSWE 53% vs Fable 5's 70%) — decompose to file-scoped specs before handing work over; community reports tool-use flakiness and intermittent regressions; `reasoning_effort` defaults to *high* — set low for mechanical steps or pay the token multiple; "Opus-class" claim is self-reported |
| Gemini (2.5-class) | Long-context ingestion, multimodal analysis, breadth | Same external-verification rules as everyone; keep task specs self-contained |
| Nemotron Super/Ultra (NIM) | Local planner/critic stand-in when frontier is metered; clean thinking toggle | Fabricates unfamiliar APIs under pressure; don't leave thinking on for bulk execution |

## Local models

| Model | Excels at | Weak at / quirks |
|---|---|---|
| Qwen3 32B / 30B-A3B | Scoped spec-driven edits; 32B `/think` is a credible checklist critic | Planner only for small plans; ≤8B variants need the small-context guardrail; never greedy in thinking mode |
| Gemma 3 27B | Best-in-class instruction following for its size; obedient executor | No system role (fold quirk); agreeable — attempts underspecified tasks unless the BLOCKED guardrail is injected; weak at catching logic errors as critic |
| Mistral Small 3.x | Fast executor; best local JSON/function-calling per GB | Terse — skips footers under load (format-gate it); under-explains reasoning; won't ask clarifying questions readily |
| DeepSeek-R1 distills | Best local critic per GB; hard single problems (race conditions, algorithm choice) | NOT an executor — slow, token-hungry, over-refactors; no system prompt; no few-shot; greedy decoding breaks it |
| Llama 3.3 70B | Generalist executor+critic in one box; conservative planner | Confident fabrication — polished answers with an invented function in the middle; verbose without token caps |

## How this file is used

- Scaffolded into every project (core doctrine file); `ANCHOR-CONVENTIONS.md` adds the
  operator's model-priority order next to it.
- `mythos-core.md` rule 11 makes the fit check binding for every fleet worker;
  `orchestrate.py` treats a `SUGGEST-ESCALATE` first line as an immediate escalation
  (no burned attempts) unless run with `--insist`.
- Re-review this file when a listed model ships a major version; entries carry the
  review date above.
