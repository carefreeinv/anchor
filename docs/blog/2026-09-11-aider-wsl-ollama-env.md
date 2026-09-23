---
title: "Fix: bare aider Connection-refused on WSL + Ollama"
authors: [carefree]
tags: [bugfix, aider, local-models]
---

On WSL2 with Ollama running on the Windows side, a plain `aider` invocation
(model already set in `.aider.conf.yml`) failed with `OllamaError: … Connection
refused` even though the model server was healthy. `scripts/write_aider_env.py`
fixes it by writing the endpoint where Aider actually looks.

<!-- truncate -->

## Why it broke

Aider (via litellm) reads `OLLAMA_API_BASE` from a repo-root `.env`, loaded
before its own model-info probe. On WSL2, the Windows-side Ollama doesn't
answer on the guest's own `localhost` — only the default-gateway IP (or a
`resolv.conf` nameserver) reaches it. Nothing wrote that reachable address
into `.env`, so Aider kept probing a dead loopback address and retried with
backoff until it gave up.

## The fix

`scripts/write_aider_env.py` reuses the reachable-`base_url` discovery
`fit_device.py --probe` already does (loopback → default-gateway → resolv
nameserver — the same fix that shipped for `/local-models` reports) and
writes it into a **gitignored** project `.env`:

```bash
python scripts/write_aider_env.py --root .            # write/refresh
python scripts/write_aider_env.py --root . --dry-run   # preview only
```

It's idempotent — re-running after `wsl --shutdown` or a gateway-IP change
updates only the `OLLAMA_API_BASE` line, leaving the rest of `.env` (and any
unrelated secrets already in there) untouched — and it ensures `.gitignore`
covers `.env`/`.env.*` so the machine-local value never gets committed.
`/local-models`'s report now points at this tool directly on Aider projects,
instead of the previous vague "wire Aider/.env" instruction.

Verified live against Aider 0.86.2 on a real WSL2 host: before the fix, bare
`aider` gave `Connection refused` / `OLLAMA_API_BASE: Not set`; after writing
`.env`, the same command resolved model info and began generating with no
errors.
