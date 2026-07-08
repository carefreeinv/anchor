---
sidebar_position: 4
sidebar_label: Local Models
---

<!-- synced-from: platforms/local-models/README.md @ d27166c10e57709522ecc2c5f3c96cf44a08777e -->

# Local Models

Per-model adaptations live in `platforms/local-models/`. Five general laws first — they matter more than any per-model trick:

1. One task spec per fresh context (small models degrade fastest with context length)
2. Force the output format; reject-and-retry outputs missing the footer
3. External verification always — smaller model = more confident fabrication
4. Right-size the role: small models are good executors and decent critics, poor planners
5. More parameters at Q4 beats fewer at Q8; a wrong chat template costs more than quantization

## The lineup

| Model | Key quirk | Role fit |
|---|---|---|
| **Qwen3** (4B–32B, 30B-A3B) | `/think` / `/no_think` per message; never greedy in thinking mode | executor + critic; 32B a passable planner |
| **Gemma 3** (12B/27B) | no true system role — fold instructions into first user turn; one task per conversation | obedient executor; add the BLOCKED guardrail (it won't push back on bad specs) |
| **Mistral Small 3.x** | wants LOW temp (0.15); terse — enforce the footer in the pipeline | fast executor, best local tool-caller per GB |
| **DeepSeek-R1 distills** | NO system prompt; temp ~0.6 (greedy breaks it); no few-shot; strip `<think>` downstream | critic + hard single problems; never an executor |
| **Llama 3.3 70B** | none — the boring reliable one | generalist executor+critic if you have ~40GB VRAM |

The quirks are encoded in `scripts/endpoints.yaml` (`quirks:` block) and applied automatically by `anchor_client.py`, so orchestration code never special-cases models.
