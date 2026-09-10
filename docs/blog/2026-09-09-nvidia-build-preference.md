---
title: Anchor prefers NVIDIA Build over local inference when it's live
authors: [carefree]
tags: [feature, tooling]
---

Local Ollama/llama.cpp is the right default for offline work and tiny swarm
edits, but it's often the slowest option on a laptop. Plenty of operators
already have an NVIDIA Build key sitting in their environment for something
else — Anchor now checks for it and prefers it automatically when it's
actually live, without touching an operator's existing choice otherwise.

<!-- truncate -->

## Configured and reachable, not just configured

A key existing in the environment doesn't mean the endpoint is reachable
right now — a typo, an expired key, or a network hiccup all look identical
from the outside. `scripts/nvidia_build_probe.py` does a real, short-timeout
check against the endpoint before ever preferring it:

```bash
python scripts/nvidia_build_probe.py --probe
```

Missing key, invalid key, or no network: it reports `local` as the backend
and moves on — never a crash, never a loud failure blocking an Aider session
from starting.

## Operator override always wins

If you've explicitly configured local inference — a specific model in
`.aider.conf.yml`, a CLI flag, `prefer_local` in your conventions — a live
Build key never silently overrides that. The preference only kicks in when
nothing else was already decided.

## Hosted, not self-hosted

This is NVIDIA's **hosted** developer API
([build.nvidia.com](https://build.nvidia.com)) — no container, no GPU of your
own. It's a different product from the self-hosted NIM containers Anchor
already documents (`platforms/nvidia-nim/NEMOTRON.md`), and the two docs pages
now cross-link explicitly so nobody confuses which one they're reading. See
[NVIDIA Build](/platforms/nvidia-build) for the full configuration and Aider
wiring.
