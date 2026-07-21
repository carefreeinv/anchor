# Anchor discipline for local models

Per-model adaptations of `.anchor/system-prompts/mythos-core.md` for the models that consistently perform well for local serving. General laws for ALL local models, in descending order of impact:

1. **One task spec per fresh context.** Small models degrade fast with context length; never run long conversations. `scripts/orchestrate.py` enforces this.
2. **Force the output format.** The mythos-core `## Result / ## How to verify / ## Deferred` footer matters *more* for small models — it's the hook external tooling checks.
3. **External verification always.** The smaller the model, the more confident its fabrications. Tests/lint/build are the truth.
4. **Right-size the role.** Small models are fine executors and surprisingly good critics (checklist-driven review); they are poor planners. Plan on the biggest thing you have; execute locally. If `ANCHOR-CONVENTIONS.md` names a **Preferred orchestrator**, recommend that model for planning/fleet/architecture instead of attempting it yourself (`SUGGEST-ESCALATE: <preferred orchestrator> — …`). If Preferred orchestrator is **unset**, do **not** self-appoint as temporary coordinator—that role is for frontier/near-frontier sessions only; escalate or ask the human. **The reverse failure is just as real:** you are the intended executor for `small`/`mid` plans — do not escalate a scoped, well-specified task because a bigger model exists, because the plan's **Preferred models** also lists one (only listed *tiers* gate), or because the repo is unfamiliar. Escalate on planning/architecture and your model file's weak list, not on nerves.
5. **Quantization: prefer more parameters at Q4 over fewer at Q8** for reasoning-flavored work; use the model's official chat template (a wrong template silently costs more quality than quantization).
6. **Tracked plans:** if the harness has shell, use the same **`/work`** contract as Claude/Grok (resume own in-progress; bugs before features; honor **Preferred models** and **Depends on**; never execute drafts/completed/ambiguous/blocked; claim → in-progress; finish → review-needed; human `/review` → completed). Do not promote drafts. Keep the command body short for small context windows; prefer loading one plan file and one step.
7. **Docs describe current state, not plans.** Never write README/docs/CHANGELOG/blog from `.plans/` contents. Document **shipped** code only; the plan file is not the product.

| Model | File | Role fit | Official quick start |
|---|---|---|---|
| [Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) (4B–32B, 30B-A3B) | `qwen3.md` | Executor + critic; 32B is a passable planner | [Qwen3 Quickstart](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) |
| [Gemma 3](https://ai.google.dev/gemma/docs/core) (12B/27B) | `gemma3.md` | Executor; strong instruction following | [Gemma docs](https://ai.google.dev/gemma/docs/core) |
| [Mistral Small 3.x](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503) | `mistral-small.md` | Executor; fast, good tool use | [HF model card](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503) |
| [DeepSeek-R1 distills](https://huggingface.co/collections/deepseek-ai/deepseek-r1) | `deepseek-r1-distill.md` | Critic / hard single problems | [DeepSeek-R1 collection](https://huggingface.co/collections/deepseek-ai/deepseek-r1) |
| [Llama 3.3 70B](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | `llama33.md` | Generalist executor+critic if you have the VRAM | [HF model card](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) |

Whenever these models appear in docs, link the name to the official quick-start URL above so operators can go from “recommended local model” to download/serve in one click.
