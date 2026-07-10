# Anchor discipline for NVIDIA NIM / Nemotron

<!-- For Nemotron models served as NIM microservices (OpenAI-compatible on :8000/v1).
     Applies to Llama-Nemotron variants (Nano/Super/Ultra) and Nemotron-H family. -->

## Serving

```bash
docker run --gpus all --rm -p 8000:8000 \
  -e NGC_API_KEY=$NGC_API_KEY \
  nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1:latest
# → OpenAI-compatible API at http://localhost:8000/v1
```

Register the endpoint in `scripts/endpoints.yaml` under the `reasoner` tier.

## The reasoning toggle — the key Nemotron quirk

Llama-Nemotron models switch modes via the system prompt:

- `detailed thinking on` → deliberate multi-step reasoning (planner/critic roles)
- `detailed thinking off` → direct answers (executor role, cheap steps)

Recommended sampling: thinking **on** → temperature 0.6, top_p 0.95; thinking **off** → greedy (temperature 0).

Registry mapping for the fleet scripts:

```yaml
quirks:
  think_toggle: nemotron   # prepends 'detailed thinking on/off' per call
  temperature: 0           # greedy when thinking is off (thinking-on stays 0.6)
  sampling_thinking: {top_p: 0.95}
```

## Role-mapped system prompts

Prepend the toggle line to `.anchor/system-prompts/mythos-core.md`:

| Role | System prompt |
|---|---|
| Planner | `detailed thinking on` + mythos-core + "Your only output is a plan per templates/plan.md. Do not write implementation code." |
| Executor | `detailed thinking off` + mythos-core + one task-spec |
| Critic | `detailed thinking on` + mythos-core + "You are reviewing, not fixing. Output per templates/review.md." |

This gives you the orchestrator pattern on a single deployed model: expensive deliberate tokens only where judgment lives, fast tokens for execution.

## Fleet placement

- Nemotron Super/Ultra (thinking on) is a credible stand-in for the frontier planner/critic when Fable-class models are unavailable or credit-metered.
- Nemotron Nano works as an executor on task specs; keep specs self-contained.
- Behind NIM everything is OpenAI-compatible, so `scripts/orchestrate.py` and `mcp/model-fleet` work unchanged.

## Tracked plans (`./.plans`)

As **planner**, write self-contained plans (template: `.anchor/templates/plan.md`)
into **`.plans/drafts/<slug>.md`**, including **Preferred models** and **Depends on**
(inventory other `.plans/**` goals first; use `none` only after checking). Do **not**
promote out of `drafts/` except via **`/draft --promote <slug>`** (infer bugs vs
features from the plan; or a human move; **path is the ready marker**). Executors claim → `in-progress/`,
finish → `completed/`; park half-baked/stuck work in `ambiguous/`|`blocked/`. Prefer
a durable Preferred orchestrator; if unset, frontier/near-frontier may be temporary
coordinator. Executors: **`/work`** or `work_once` / `orchestrate.py --plan-file`.

**Docs describe current state, not plans:** never write README/docs/CHANGELOG/blog
from `.plans/` contents. Document **shipped** code and public contracts only.
Documenting the `.plans/` **workflow** itself is fine when it is a shipped feature.

## Cautions

- Don't leave `detailed thinking on` for bulk execution — it multiplies latency and tokens for no quality gain on mechanical tasks (same lesson as the Fable credit playbook, locally).
- Nemotron follows format instructions well but will still fabricate unfamiliar APIs under pressure; the `(unverified)` marking rule and external verification remain mandatory.
