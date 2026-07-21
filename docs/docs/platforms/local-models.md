<!-- synced-from: platforms/local-models/README.md @ db39c71e59fa5f999db8115e5622777e217277c9 -->
---
sidebar_position: 4
sidebar_label: Local Models
---

<!-- synced-from: platforms/local-models/README.md @ PENDING -->

# Local Models

Per-model adaptations live in `platforms/local-models/`. General laws first — they matter more than any per-model trick:

1. One task spec per fresh context (small models degrade fastest with context length)
2. Force the output format; reject-and-retry outputs missing the footer
3. External verification always — smaller model = more confident fabrication
4. Right-size the role: small models are good executors and decent critics, poor planners
5. More parameters at Q4 beats fewer at Q8; a wrong chat template costs more than quantization
6. Tracked plans follow the same `/work` contract when the harness has shell
7. **Docs describe current state, not plans** — never write product docs from `.plans/` contents

## The lineup

Each model name links to its **official quick start** (download / serve / chat template). Use that first if you are new to the model; then apply Anchor’s adaptation notes under `platforms/local-models/`.

| Model | Key quirk | Role fit | Official quick start |
|---|---|---|---|
| [**Qwen3**](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) (4B–32B, 30B-A3B) | `/think` / `/no_think` per message; never greedy in thinking mode | executor + critic; 32B a passable planner | [Qwen3 Quickstart](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) |
| [**Gemma 3**](https://ai.google.dev/gemma/docs/core) (12B/27B) | no true system role — fold instructions into first user turn; one task per conversation | obedient executor; add the BLOCKED guardrail (it won't push back on bad specs) | [Gemma docs](https://ai.google.dev/gemma/docs/core) |
| [**Mistral Small 3.x**](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503) | wants LOW temp (0.15); terse — enforce the footer in the pipeline | fast executor, best local tool-caller per GB | [HF model card](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503) |
| [**DeepSeek-R1 distills**](https://huggingface.co/collections/deepseek-ai/deepseek-r1) | NO system prompt; temp ~0.6 (greedy breaks it); no few-shot; strip `<think>` downstream | critic + hard single problems; never an executor | [DeepSeek-R1 collection](https://huggingface.co/collections/deepseek-ai/deepseek-r1) |
| [**Llama 3.3 70B**](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | none — the boring reliable one | generalist executor+critic if you have ~40GB VRAM | [HF model card](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) |

The quirks are encoded in `scripts/endpoints.yaml` (`quirks:` block) and applied automatically by `anchor_client.py`, so orchestration code never special-cases models. Hardware-specific serve helpers: [personal devices](/hardware/personal-devices/mac-mini), [H100](/hardware/h100).

## Tracked plans and coordination

Local models follow the same **`/work`** contract when the harness has shell: honor **Preferred models** and **Depends on**, claim into `in-progress/`, finish to **`review-needed/`** (human [`/review`](/skills/review) → `completed/`), never promote drafts. They do **not** self-appoint as temporary coordinator when Preferred orchestrator is unset—escalate to a frontier session. The reverse failure is just as real: local models are the *intended* executors for `small`/`mid` plans, so a scoped, well-specified task is not escalated because a bigger model exists, because the plan's **Preferred models** also lists one (only listed *tiers* gate), or because the repo is unfamiliar. See [model fitness](/model-fitness) and Skills → [`/work`](/skills/work).
