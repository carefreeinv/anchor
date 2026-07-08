---
title: Introducing Anchor
authors: [carefree]
tags: [announcement]
---

Anchor makes less-powerful models behave like a Mythos-class model — through
structure, not capability. Plan on the smartest thing you can afford, cut the plan
into task specs that fit one context window each, execute on the cheapest model
that passes your benchmarks, verify with tooling, review with a fresh-context
critic, and escalate after two failures instead of retrying forever.

<!-- truncate -->

The premise is economic: frontier models are becoming metered utilities. The
operator skill that matters is knowing which tasks actually deserve frontier
pricing — and routing everything else to models that are already good enough,
whether that's a cheaper API tier, a Mac Mini on your desk, or an H100 node you
own.

The [repo](https://github.com/carefreeinv/anchor) ships the whole loop, not just the doctrine: per-platform instruction
files (Claude Code, Grok Build, NVIDIA NIM/Nemotron, local models, plain chat
UIs), a scaffolder (`anchor <project-dir>`) that drops the right doctrine into any
project, fleet scripts for routing/orchestration/benchmarking, and MCP servers so
a frontier agent can delegate keystrokes to your local fleet instead of burning
credits on them.

Model quirks — Gemma's missing system role, Qwen3's thinking toggle, DeepSeek-R1's
no-system-prompt rule, repetition loops under greedy decoding — live in one place
(`anchor_client.py`), keyed by each endpoint's `quirks:` block, so every caller
stays model-agnostic.

Start with [the doctrine](/doctrine), then [the playbook](/playbook) for the
economics, then run `./config.sh` and scaffold your first project.
