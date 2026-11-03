---
title: "`anchor models` nicknames for fleet endpoints"
authors: [carefree]
tags: [cli, fleet]
---

Operators can nickname a configured endpoint (`lightning` for
`nemotron-build`) and pass that name to `anchor work --endpoint`.

<!-- truncate -->

`anchor models list` shows name, aliases, machine, model, and effort.
`anchor models nick lightning --endpoint nemotron-build --machine flippy`
writes only a machine-local overlay (`~/.config/anchor/endpoints.local.yaml`
or `var/endpoints.local.yaml`), never the shared registry. Duplicate
aliases fail at load. `--effort` on the CLI still wins over a nickname
default. Machine is a label, not a locality flag.
