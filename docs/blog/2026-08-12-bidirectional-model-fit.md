---
slug: bidirectional-model-fit
title: Bidirectional model fit — escalate and downgrade
authors: [carefree]
tags: [feature, doctrine, fleet]
---

Anchor already stopped **too-hard** work with a first-line `SUGGEST-ESCALATE`. Premium sessions still burned credits on **too-easy** work with only a soft “say so and ask.”

<!-- truncate -->

## What shipped

| Direction | Token | Rule |
|-----------|--------|------|
| Too hard | `SUGGEST-ESCALATE: <target> — <reason>` | mythos-core 11 |
| Too easy | `SUGGEST-DOWNGRADE: <cheaper> — <reason>` | mythos-core 10 |
| Good fit | *(silence)* | no model pitch |

`orchestrate.py` treats both as fit gates alongside `SUGGEST-REROUTE` for specialty mismatch (no retry burn; `--insist` proceeds) — see [Dual-axis model fit](/blog/dual-axis-model-fit) for the specialty side. Interactive platforms (Claude, Grok, Chat, local) state the same standing check. Downgrade heuristics stay conservative — rename/format/boilerplate, not “any multi-file mid work.”

See [Model fitness](/model-fitness) and [Doctrine](/doctrine).
