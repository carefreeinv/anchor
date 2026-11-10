---
title: "Slash skills drive the same CLI loop as the terminal"
authors: [carefree]
tags: [docs, skills]
---

Grok and Claude standing rules, plus `/work`, `/review`, and `/draft`, now
tell the agent to prefer **`anchor work`**, **`anchor review`**, and
**`anchor draft "<desc>"`** — the same loop as a terminal with `anchor` on
PATH.

<!-- truncate -->

Empty `review-needed/` with integration ahead of mainline still names
`anchor review --promote`; the operator has to pass the flag. Probe once
this session; last-known-good CLI still wins over re-implementing lane
moves in chat.
