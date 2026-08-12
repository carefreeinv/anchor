---
slug: bidirectional-model-fit
title: Bidirectional model fit — escalate and downgrade
authors: [anchor]
tags: [routing, doctrine, fleet]
---

# Bidirectional model fit — escalate and downgrade

Anchor already stopped **too-hard** work with a first-line `SUGGEST-ESCALATE`. Premium sessions still burned credits on **too-easy** work with only a soft “say so and ask.”

## What shipped

| Direction | Token | Rule |
|-----------|--------|------|
| Too hard | `SUGGEST-ESCALATE: <target> — <reason>` | mythos-core 11 |
| Too easy | `SUGGEST-DOWNGRADE: <cheaper> — <reason>` | mythos-core 10 |
| Good fit | *(silence)* | no model pitch |

`orchestrate.py` treats both as fit gates (no retry burn; `--insist` proceeds). Interactive platforms (Claude, Grok, Chat, local) state the same standing check. Downgrade heuristics stay conservative — rename/format/boilerplate, not “any multi-file mid work.”

See [Model fitness](/model-fitness) and [Doctrine](/doctrine).
