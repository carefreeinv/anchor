---
title: "/local-models can now wire your project, not just recommend"
authors: [carefree]
tags: [feature, local-models]
---

`/local-models` has always probed your machine and recommended a fit local
model. Until now it stopped there — even when Ollama and a fit model were
already running, the operator still had to hand-wire endpoints, `.env`, and
Aider config themselves. `local_models_autowire.py` closes that gap.

<!-- truncate -->

## Confirmed, not just reachable

"The API answered" isn't the same as "the model I want is actually being
served there." `local_models_autowire.py --detect` checks both: a
guest-reachable OpenAI-compatible API, **and** that API's `/models` actually
lists the Default-for-wire model id. Either gate failing means **not
confirmed** — no guessing, no writing a stanza for a model that isn't there.

```bash
python scripts/local_models_autowire.py --detect
CONFIRMED: base_url=http://172.26.0.1:11434/v1 model=qwen3-8b tag=qwen3:8b served=True aider=True
```

## One confirm, one write set

When confirmed, `/local-models` now asks **"Wire this project?"**. A yes
writes, all idempotent and machine-local only:

- a `var/endpoints.local.yaml` overlay (the memory-safer Default-for-wire
  model, never the largest fit)
- the gitignored `.env` with `OLLAMA_API_BASE` (reusing `write_aider_env.py`'s
  existing contract — bare `aider` stops Connection-refusing)
- an idempotent conventions-file note, only if the project already has one
- `.aider.conf.yml` and a copied launcher script, but only when `aider` is
  actually on `$PATH`

```bash
python scripts/local_models_autowire.py --project . --write
```

Nothing installs Ollama or downloads weights here — this is "use what's
already running," not a converge/install pipeline. Declining, or an
unconfirmed stack, falls through to the existing draft-offer path unchanged.
