---
title: Model reasoning lands in var/log
authors: [carefree]
tags: [feature, fleet, cli]
---

Anchor CLI and orchestrate chats now write chain-of-thought to local
`var/log/reasoning-YYYY-MM-DD.log` files so you can see what a model was
doing without stuffing that text into the coordinator's context.

<!-- truncate -->

`Endpoint.chat` is the choke point. After each HTTP 200 it records
`message.reasoning` / `message.thinking`, any `<think>` blocks (before
strip), finish reason, usage counts, and message sizes. The string callers
get back is still the stripped assistant content. Mythos-core's footer
relay is unchanged.

`var/` stays gitignored. Relocate with `ANCHOR_LOG_DIR`, disable with
`ANCHOR_NO_REASONING_LOG=1`, include prompt bodies only when you set
`ANCHOR_LOG_PROMPTS=1` on a machine you trust. Orchestrate still archives
full executor replies under `var/task-transcripts/`.
