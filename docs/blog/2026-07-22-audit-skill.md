---
title: "/audit — security findings that become ready bug plans"
authors: [carefree]
tags: [feature, skills]
---

Security holes die in chat transcripts. **`/audit`** turns an exhaustive code-
and-dependency pass into **prioritized `.plans` bug plans** so the fleet can
close them like any other ready work.

<!-- truncate -->

## The gap

Teams already have scanners, ad-hoc reviews, and “we should fix that someday”
threads. What Anchor was missing was a **session that**:

1. Covers **first-party code and third-party dependencies** in one pipeline
2. Maps severity to plan **`Priority`** (P1–P3) so `/work` picks the right order
3. Tags every fix plan with **`Preferred models: frontier, reasoner`** so mid
   and small workers leave security repair alone under normal fit rules
4. **Writes plans only** — no silent “I fixed it,” no exploit PoCs, no secret
   dumps

## What `/audit` does

**One project, one session.** Pipeline (fixed):

```text
resolve project → model-fit gate → inventory
  → dependency audit → first-party code audit
  → dedupe / severity → Priority
  → present findings → confirm (or --write / --dry-run)
  → emit bug plans → stop
```

It never auto-starts `/work` on the plans it creates.

| Flag | Role |
|------|------|
| `--dry-run` | Full findings package; **zero** plan files |
| `--write` | Skip confirm after the package |
| `--to drafts` | Private drafts instead of ready `bugs/` |
| `--force-model` | Override the mid/small refuse (risk on you) |
| `--deps-only` / `--code-only` | Narrow buckets |

Default writes land as sticky **`.plans/bugs/sec-<kebab>.local.md`** so unvetted
findings stay gitignored until a human renames them for tracking.

## Frontier / reasoner only (by default)

A weak model that “audits” confidently is worse than no audit: false negatives
leave holes open; false positives bury the ready queue. `/audit` **refuses** mid
and small sessions unless the operator passes **`--force-model`**. Grok 4.5 is
mid-class for this gate — high reasoning effort is a cost dial, not a promotion.

Every emitted fix plan repeats the floor so fleet pickers keep security work on
the right tier.

## Safety

- No exploit payloads or weaponized “proofs” in chat, Steps, or the repo
- Secrets redacted (path + last 4 / hash)
- Cap of **25** plans per run; residual risk when a scanner is missing
- No public disclosure side-effects from the skill defaults

## Where it ships

- Claude: `.claude/commands/audit.md`
- Grok: `.grok/skills/audit/SKILL.md`
- Docs: [Skills → `/audit`](/skills/audit)
- Scaffolded with the other dual-use skills (`scripts/anchor.py`)

Pair with **`/work`** on the plans it writes (on a reasoner/frontier session)
and **`/review`** when those fixes are ready for human sign-off.
