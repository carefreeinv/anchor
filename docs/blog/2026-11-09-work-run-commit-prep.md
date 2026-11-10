---
title: "Successful --run now commit-preps and commits on the feature branch"
authors: [carefree]
tags: [feature, tooling]
---

Unattended `work_once --run` and interactive `anchor work --run` leave a
**feature-branch SHA** after a green prep, then park in `review-needed/`. You
can `/review` and `git log` without a chat harness.

<!-- truncate -->

Prep red does not commit and does not auto-finish. `--no-commit` is apply-only.
Protected branches (`main`, `master`, `dev`, `develop`) are refused.
