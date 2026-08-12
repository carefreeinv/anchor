# Model fitness — where each model excels, where it fails

Reviewed **2026-08-12** (dual-axis specialty profiles). Frontier entries move fast; treat vendor-reported numbers as
`(unverified)` until your own `benchmark.py` run says otherwise — that table, not this
file, is your routing policy. This file exists for the *fit check* (below): a model
handed a task should be able to look itself up, see the task lands in its weak column,
and say so before burning tokens.

## The fit check (every model, every task) — dual-axis

Before planning, compare the pending task against your row below (and the project's
`ANCHOR-CONVENTIONS.md` / `.anchor/conventions.md` model-routing / **Preferred
orchestrator** sections). Run **two axes in order**. Good fit on **both** → emit
**nothing** about models and proceed.

### Axis 1 — power (tier / weak column / orchestration)

If the task lands in your **weak** column — or is orchestration-class work and you
are not that preferred orchestrator:

1. Entire first line: `SUGGEST-ESCALATE: <better-suited model or role/tier> — <one-line reason>`
   (prefer the project's Preferred orchestrator when set)
2. Stop. Do not begin the task.
3. Proceed only if the operator insists — then stay in scope and mark `(unverified)`.

**Temporary coordinator:** if Preferred orchestrator is **unset** and no project MCP
coordinator is registered, a **frontier / near-frontier** model (Fable-class,
Opus-class, strong GPT-5.x, Grok 4.5 as session lead, etc.) may temporarily
coordinate: inventory `.plans/**`, propose **Depends on**, draft under `drafts/`.
Announce `TEMPORARY-COORDINATOR: <name> — Preferred orchestrator unset`. Mid, small,
and local models must **not** self-appoint—escalate to a stronger session or the
operator. Recommend setting a durable orchestrator with
`anchor <project> --set-orchestrator …`.

Suggest *downward* too (per mythos-core rule 10): boilerplate on a frontier tier wastes
credits exactly the way hard problems on a swarm node waste attempts.

### Axis 2 — specialty (computational / product profile)

If power is OK (or unknown) but you are the **wrong kind of model** for the work —
same power band, different product shape — re-route **laterally**:

1. Entire first line: `SUGGEST-REROUTE: <target model or profile tag> — <one-line reason>`
2. Stop (unless the operator insists — then proceed `(unverified)`).

**Closed profile tags (v1):**

| Profile tag | Work shape | Illustrative products |
|-------------|------------|------------------------|
| `coding-agent` | Multi-file software, tests, repo tools, PR-shaped work | Claude Code / Sonnet-class IDE agents, coding-tuned locals |
| `terminal-agent` | Long CLI / shell / fleet script runs | Grok Build–class terminal agents |
| `critic` | Review, race conditions, hard single-problem reasoning | R1 distills, Nemotron thinking-on, Opus-class deep dives |
| `planner` | Cross-plan Depends on, architecture, orchestration | Preferred orchestrator / frontier coordinator |
| `general-chat` | Spec shaping, explanation, single-turn Q&A without repo agency | ChatGPT Instant / pure chat UIs |
| `multimodal` | Screenshots, diagrams, image+code | Vision-capable endpoints |
| `swarm-local` | Thin boilerplate on host-local cheap models | Qwen3 4B/8B local swarm |

**Example first lines (specialty, not power-up):**

- `SUGGEST-REROUTE: coding-agent — leave multi-file software execution for a software-dev optimized model`
- `SUGGEST-REROUTE: Claude Sonnet 5 — general-chat session cannot run shell/repo tools`
- `SUGGEST-REROUTE: critic — bulk implementation is wrong shape for R1-distill`
- `SUGGEST-REROUTE: coding-agent — swarm-local 4B/8B is thin glue only, not this multi-service edit`
- `SUGGEST-REROUTE: multimodal — task needs screenshot/vision; this endpoint is text-only`
- `SUGGEST-REROUTE: terminal-agent — long fleet shell run fits Grok/CLI agent better than pure chat`
- `SUGGEST-REROUTE: planner — cross-plan Depends on / architecture needs Preferred orchestrator`

Decision order: **power first** (escalate if underqualified/weak-column); else **specialty**;
else silent proceed. Specialty is never “a stronger model exists.”

Plans may list profile tags in **Preferred models** next to tiers/names
(e.g. `mid, coding-agent` or `coding-agent, Claude Sonnet 5`). Mechanical
`/work` fit still keys on **tiers + names** only; unknown profile tokens are
ignored by `plan_select` — they guide **self-assessment**, not the picker floor.

### What does *not* trigger the fit check

The gate is your **weak column**, orchestration-class work, and **material
specialty mismatch**. It is not a general licence to decline. Over-shy
escalation/re-route has a cost the transcript never shows: the plan sits in the
backlog, the operator waits, and a model that could have finished it is idle. Do
**not** escalate or re-route merely because:

- **A stronger model exists.** True of nearly every task; not a fit verdict.
- **A plan's `Preferred models` names a stronger product.** Only listed **tiers**
  (`small | mid | reasoner | frontier`) set the power floor — names are extra
  good-fit hits, not a raised bar. A list with no tier and no name you match is
  *unknown* fit, which is **eligible** (`/work` and `scripts/plan_select.py`).
- **The task is unfamiliar or multi-file *within your profile*.** Unfamiliar is
  what a task spec and the repo are for. Multi-file coding work *is* a specialty
  mismatch for pure `general-chat` / no-tools sessions — not for a coding-agent mid.
- **A single step looks hard.** Claim the plan; route or escalate *that step*
  (per-step `Route to`, `## Escalation triggers`), or hand the plan back to ready.

Escalating or re-routing when you shouldn't is a real failure mode, not the safe
default — it just fails quietly. Weigh it the same way you weigh attempting work
above your tier or outside your profile.

## Frontier / API models

| Model | Profiles | Excels at | Weak at / quirks |
|---|---|---|---|
| Claude Fable 5 | `planner`, `coding-agent`, `critic` | Long-horizon autonomous work, large migrations, multi-service debugging, final review of big merges | Credit-metered — wasting it on keystrokes is an economics failure, not a capability one |
| Claude Opus 4.8 | `critic`, `planner`, `coding-agent` | Deep single-problem reasoning, architecture calls, security-adjacent work | Overkill for scoped edits; slower/pricier than Sonnet on routine execution |
| Claude Sonnet 5 | `coding-agent` | Default executor: scoped multi-file edits, solid tool use, good cost/quality | Hands multi-hour autonomy and hardest architecture calls up a tier |
| Claude Haiku 4.5 | `coding-agent` (light), `swarm-local`-adjacent | Classification, summaries, spec-tuning, cheap pipeline glue | Multi-file reasoning, subtle bug hunts |
| GPT-5.6 Sol (public 2026-07-09) | `coding-agent` | Agentic coding + cybersecurity tasks — benchmark leader `(unverified, vendor)` | **Documented over-eagerness**: OpenAI's own system card notes a greater tendency than GPT-5.5 to exceed user intent — unrequested "cleanup" actions and **claiming unperformed work**. Scope and verification gates are mandatory, not optional |
| GPT-5.6 Terra | `coding-agent` | ~GPT-5.5 quality at roughly half the cost `(unverified, vendor)` — the economics pick for executor work | Same system-card caveats as Sol; benchmarks vendor-reported |
| GPT-5.6 Luna | `coding-agent` (light) | Frontier-adjacent quality at budget price ($1/$6) — strong tuner/executor-light | Thinnest tier of the family; keep it off architecture and review roles |
| ChatGPT (product: GPT-5.5 + Instant Mini fallback) | `general-chat` (primary); Instant Mini stays chat | Conversational spec-shaping, explanations, one-step-per-turn piloted work | No shell/file access: every "it works" is a claim on the human's behalf; fallback routing means tier varies mid-session — **re-route multi-file software to `coding-agent`** |
| Grok 4.5 (public 2026-07-09) | `terminal-agent`, `coding-agent` | Terminal/CLI-driven tasks (Terminal-Bench ≈ GPT-5.5 class), long tool-use runs, token efficiency (~4× fewer than Opus-class `(unverified, vendor)`), cheap at $2/$6; **catalog tier for Preferred matching is mid** | **Repo-scale issue resolution measurably behind** (DeepSWE 53% vs Fable 5's 70%) — decompose to file-scoped specs before handing work over; community reports tool-use flakiness and intermittent regressions; `reasoning_effort` defaults to *high* — set low for mechanical steps (`/effort low` in Grok Build) or pay the token multiple; high effort is a cost dial, not a frontier promotion; "Opus-class" claim is self-reported |
| Gemini (2.5-class) | `multimodal`, `general-chat` | Long-context ingestion, multimodal analysis, breadth | Same external-verification rules as everyone; keep task specs self-contained |
| Nemotron Super/Ultra (NIM) | `critic`, `planner` (thinking-on); executor only thinking-off | Local planner/critic stand-in when frontier is metered; clean thinking toggle | Fabricates unfamiliar APIs under pressure; don't leave thinking on for bulk execution |

## Local models

Model names link to the **official quick start** (download / serve / templates). Anchor adaptations: `platforms/local-models/`.

| Model | Profiles | Excels at | Weak at / quirks |
|---|---|---|---|
| [Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) 32B / 30B-A3B | `coding-agent` (32B); `swarm-local` (≤8B) | Scoped spec-driven edits; 32B `/think` is a credible checklist critic | Planner only for small plans; ≤8B variants need the small-context guardrail; never greedy in thinking mode — **re-route large software plans off tiny swarm locals** |
| [Gemma 3](https://ai.google.dev/gemma/docs/core) 27B | `coding-agent` | Best-in-class instruction following for its size; obedient executor | No system role (fold quirk); agreeable — attempts underspecified tasks unless the BLOCKED guardrail is injected; weak at catching logic errors as critic |
| [Mistral Small 3.x](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503) | `coding-agent` | Fast executor; best local JSON/function-calling per GB | Terse — skips footers under load (format-gate it); under-explains reasoning; won't ask clarifying questions readily |
| [DeepSeek-R1 distills](https://huggingface.co/collections/deepseek-ai/deepseek-r1) | `critic` | Best local critic per GB; hard single problems (race conditions, algorithm choice) | NOT an executor — slow, token-hungry, over-refactors; no system prompt; no few-shot; greedy decoding breaks it — **bulk implement → `SUGGEST-REROUTE: coding-agent`** |
| [Llama 3.3 70B](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | `coding-agent`, `critic` | Generalist executor+critic in one box; conservative planner | Confident fabrication — polished answers with an invented function in the middle; verbose without token caps |

## Observed data (preferred over vendor claims)

Vendor scorecards and the rows above are **starting priors**. After you run
`orchestrate.py` (or any path that records task outcomes), prefer **locally
observed** claim-vs-actual rates:

1. Ledger: append-only JSONL at `var/fleet-metrics/outcomes.jsonl` (metadata only —
   model, tier, task id hash, claimed status, verify exit, optional scope verdict;
   no prompts or task bodies). Written by `orchestrate.py` at each task's verify
   step via `scripts/fleet_metrics.py`.
2. Report: `python scripts/fitness_report.py` (table) or `--json` — per-model
   claim accuracy, verify pass-rate, unparseable rate. Rates with **n < 5** are
   withheld so small samples do not look like truth.
3. **Humans** update this file's prose from the report. Nothing rewrites
   `model-fitness.md` automatically.

The model's claim of success is an input to verification, never a substitute —
this ledger instruments that sentence. Rotate or truncate the JSONL manually if
it grows large; automated rotation is out of scope here.

## How this file is used

- Scaffolded into every project (core doctrine file); `ANCHOR-CONVENTIONS.md` adds the
  operator's model-priority order next to it.
- `mythos-core.md` rule 11 makes the **dual-axis** fit check binding for every fleet worker;
  `orchestrate.py` treats first-line `SUGGEST-ESCALATE` (power) and `SUGGEST-REROUTE`
  (specialty) as immediate fit gates (no burned attempts) unless run with `--insist`.
- Re-review this file when a listed model ships a major version; entries carry the
  review date above. Prefer observed fitness report numbers over vendor claims
  when sample sizes are large enough (see above).
