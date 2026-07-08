# Anchor discipline for local models

Per-model adaptations of `anchor/system-prompts/mythos-core.md` for the models that consistently perform well for local serving. General laws for ALL local models, in descending order of impact:

1. **One task spec per fresh context.** Small models degrade fast with context length; never run long conversations. `scripts/orchestrate.py` enforces this.
2. **Force the output format.** The mythos-core `## Result / ## How to verify / ## Deferred` footer matters *more* for small models — it's the hook external tooling checks.
3. **External verification always.** The smaller the model, the more confident its fabrications. Tests/lint/build are the truth.
4. **Right-size the role.** Small models are fine executors and surprisingly good critics (checklist-driven review); they are poor planners. Plan on the biggest thing you have; execute locally.
5. **Quantization: prefer more parameters at Q4 over fewer at Q8** for reasoning-flavored work; use the model's official chat template (a wrong template silently costs more quality than quantization).
6. **Tracked plans:** if the harness has shell, use the same **`/work`** contract as Claude/Grok (bugs before features; never execute drafts/completed; honor **Preferred models**). Only relocate under `.plans/` is ready → `completed/` when done; do not promote drafts. Keep the command body short for small context windows; prefer loading one plan file and one step.

| Model | File | Role fit |
|---|---|---|
| Qwen3 (4B–32B, 30B-A3B) | `qwen3.md` | Executor + critic; 32B is a passable planner |
| Gemma 3 (12B/27B) | `gemma3.md` | Executor; strong instruction following |
| Mistral Small 3.x | `mistral-small.md` | Executor; fast, good tool use |
| DeepSeek-R1 distills | `deepseek-r1-distill.md` | Critic / hard single problems |
| Llama 3.3 70B | `llama33.md` | Generalist executor+critic if you have the VRAM |
