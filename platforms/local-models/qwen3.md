# Qwen3 — Anchor adaptation

**Sizes:** 0.6B–32B dense; 30B-A3B MoE (best quality/VRAM ratio for executors; runs well even on CPU-heavy rigs).

**Official quick start:** [Qwen3 Quickstart](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) · [HF collection](https://huggingface.co/collections/Qwen/qwen3)

## Thinking toggle

Qwen3 supports hybrid reasoning. Control per message:

- Append `/think` for planner/critic roles — sampling: temp 0.6, top_p 0.95, top_k 20. **Never greedy in thinking mode** (causes repetition loops).
- Append `/no_think` for executor steps — temp 0.7, top_p 0.8.
- Do not include reasoning content from previous turns back into context (strip `<think>` blocks in multi-turn use; `.anchor/scripts/` helpers do this).

### OpenAI-compatible pitfall (Ollama and similar)

On some Ollama builds, `/v1/chat/completions` with a small `max_tokens` returns
HTTP 200 with **`content=""`** while tokens sit in `message.reasoning` and
`finish_reason=length`. Treat that as a failure, not a successful empty string.
`anchor_client.Endpoint.chat` floors `max_tokens` via `min_completion_tokens`,
retries once with think-off + a higher budget, then raises `EmptyAssistantText`
instead of returning `""`. Do **not** paste `reasoning` into user-visible output.

Native Ollama `/api/chat` `think:false` can still put “thinking” into `content`
on some builds — prefer the OpenAI path through `anchor_client` with the quirks
below, and keep `/no_think` on executor turns.

Registry mapping for the fleet scripts (`.anchor/scripts/fit_device.py` emits this for you):

```yaml
quirks:
  think_toggle: qwen3          # appends /think or /no_think per call
  strip_think: true
  min_completion_tokens: 256   # avoid reasoning burning a tiny budget
  sampling_thinking: {top_p: 0.95, top_k: 20}
  sampling: {top_p: 0.8}       # /no_think executor rec (Anchor keeps temp low for determinism)
```

**Ollama-only opt-in:** add `openai_think: false` (or `true`) to an Ollama
endpoint when you want the OpenAI-body `think` field. Key **presence** (not the
bool) makes `Endpoint.chat` send it; on HTTP 400 the client drops the field and
caches that the endpoint rejects it so later calls skip re-probing. Do **not**
set this on llama.cpp / MLX / vLLM registries — they pay a 400+retry tax.

`anchor_client.py` refuses greedy decoding whenever thinking is on, so the repetition-loop failure can't be triggered from the pipeline.

## System prompt

Use `.anchor/system-prompts/mythos-core.md` as-is (Qwen3 respects system role well). Add for sizes ≤8B:

> Your context is small and your memory unreliable. Trust only the task spec text above. If the spec doesn't contain something you need, say BLOCKED and name it — do not improvise.

## Role fit

- **Executor:** 30B-A3B or 14B/32B dense. Excellent at scoped, spec-driven edits.
- **Critic:** 32B `/think` with `templates/review.md` — checklist review is where mid models punch above weight.
- **Planner:** only 32B `/think`, and only for small plans; prefer a frontier model or Nemotron Super.
- **Not the project orchestrator:** recommend the Preferred orchestrator when set; if unset, escalate to a frontier/near-frontier session as temporary coordinator—do not self-appoint.

## Aider + swarm-local `/work` (canary and context budget)

Live canary (2026-09-08, `ollama_chat/qwen3:4b`, Aider `whole` edit format,
~4096-token repo-map): the user typed `hello`. The model took **600s** (a
LiteLLM timeout) and, on retry, treated Aider's own file-list system rules as
the task — a thinking loop, not an answer. Two lessons drive
`platforms/aider/work-drone.md`:

- **Canonical `.grok/skills/work/SKILL.md` / `.claude/commands/work.md` are
  hundreds of lines** (Grok effort maps, the culmination merge question, the
  scoped-merge gate, promotion review). Asking a 4B/8B model to load that
  whole file on `/work` is the same failure class as `hello`, only with a
  bigger prompt to get lost in. A ≤8B swarm session must **never** load the
  full skill — it follows the thin drone card instead (script-first: run
  `plan_fit.py` / `plan_select.py --claim` rather than reasoning about lanes).
- **A confused small model needs a short leash, not a bigger prompt.** Cap
  `--timeout` and `--map-tokens` so a confusion loop dies in tens of seconds,
  not 600s; keep the always-loaded (`read:`) context to the brief + drone card
  only, not the doctrine novel. See `platforms/aider/.aider.conf.swarm.yml.example`.

**Re-verified live (2026-09-11) on the same WSL2 + Windows-host-Ollama
profile, with the thin drone-card context and a 60s `timeout:` cap already
applied — two findings that correct/extend the above:**

- **A bare `/work` never reaches the model at all.** Aider treats any message
  starting with `/` as one of its **own** built-in commands and replies
  `Invalid command: work` without ever calling the LLM — this is true for
  *every* model size, not just small ones. The operator has to type the word
  `work` with no leading slash. `platforms/aider/work-drone.md` and
  `platforms/aider/skills-index.md` document this; `AIDER.md` (shipped by an
  earlier plan) still says to treat literal `/work` as the trigger and needs
  the same correction — flagged as a follow-up, not fixed here (out of this
  plan's file scope).
- **`--timeout` caps one attempt, not the whole exchange.** litellm retries a
  timed-out call automatically (observed: 3 retries, each hitting the full
  60s cap again, ~0.2s/0.5s/1.0s backoff between them) — so a per-attempt cap
  does not bound total wall-clock the way it looks like it should. A trivial,
  minimal-context prompt ("hello, just say hi back", no drone card loaded)
  still failed to complete in 60s on this host via Aider/litellm, while the
  **same** Ollama endpoint answered a comparable prompt over raw `curl` in
  ~8–12s — the gap is in the Aider/litellm request path on this host, not
  raw model throughput. Root cause not further isolated here; treat
  "Interactive 4B remains hopeless on this class of host" (this plan's own
  Risk) as the honest current status rather than something the timeout/map-tokens
  caps alone fixed.

## Serving

llama.cpp GGUF (Q4_K_M sweet spot) or vLLM (AWQ/FP8 on H100). Long-context variants exist; still prefer short, fresh contexts per Anchor law #1.
