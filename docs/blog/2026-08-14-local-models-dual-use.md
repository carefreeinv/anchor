---
slug: local-models-dual-use
title: /local-models is now a dual-use skill
authors: [carefree]
tags: [feature, skills, tooling]
---

# `/local-models` is now a dual-use skill

<!-- truncate -->

`/local-models` used to exist only after you scaffolded a project. It now lives in the **Anchor checkout** the same way `/work` does, and is still copied into Claude/Grok projects.

That means you can ask “what can this box run?” from the Anchor tree before a project exists. The probe is still **this host only** — do not commit localhost fit as fleet-wide law. Existing projects whose manifest still points at `platforms/…/local-models` are remapped by `anchor --check` / `--upgrade`.
