---
title: "/optimize — standards checks that become checkbox-picked plans"
authors: [carefree]
tags: [feature, skills]
---

Every project accumulates the same small gaps: no `robots.txt`, no `llms.txt`,
a single stray `favicon.ico` instead of a real icon set, no dependency-update
bot. **`/optimize`** scans for the standards that actually apply to *this*
project's type, and turns the gaps into `.plans` you pick from — not a wall of
text you have to triage by hand.

<!-- truncate -->

## The gap

Unlike security holes (`/audit`'s job), hygiene and discoverability gaps don't
page anyone — they just quietly cost a project its social preview image, its
crawler visibility, or its "why doesn't this repo have a `SECURITY.md`"
moment. What was missing was a session that:

1. **Detects project type before suggesting anything** — a CLI tool never
   gets told to add Open Graph tags; a static site never gets told to add
   `CODEOWNERS` alone as if that were the priority
2. Checks a **reproducible baseline** instead of relying on model recall alone
3. Ranks by **impact/effort**, caps the noise, and lets a human **pick a
   subset** instead of writing ten plans nobody asked for
4. **Writes plans only** — it never touches `robots.txt` or wires an OG image
   pipeline itself

## What `/optimize` does

**One project, one scan.** Pipeline (fixed):

```text
resolve project → detect project type(s)
  → build applicable-standards checklist → check presence/absence
  → rank + cap at 10 candidates → present findings (human)
  → checkbox confirm (or --write / --dry-run)
  → emit chosen candidates → stop
```

| Signal | Type | Checks |
|--------|------|--------|
| SSR framework / bundled `index.html` | Web app | OG/Twitter cards, `robots.txt`/`sitemap.xml`/`llms.txt`, PWA icons, structured data |
| `package.json` with `bin`, published library | CLI / library | `CODEOWNERS`, `SECURITY.md`, `CONTRIBUTING.md`, release config, `.editorconfig` |
| Docusaurus/MkDocs/Sphinx/VitePress markers | Docs | `llms.txt`/`llms-full.txt`, search config |
| Any repo | General | dependency bot, `LICENSE`, `CHANGELOG`, issue/PR templates |

A project can match more than one row — Anchor's own docs site, for instance,
reads as **Docs + CLI/library + General** all at once, and only the union of
those categories gets checked.

| Flag | Role |
|------|------|
| `--dry-run` | Findings only; **zero** plan files |
| `--write` | Skip confirm; write all presented candidates |
| `--to features` / `--to bugs` | Opt-in straight to a ready lane |
| `--continue` | Resume a capped backlog from a prior run |

## The checklist is a floor, not a ceiling

A hardcoded baseline keeps results reproducible run to run — but "popular
standard" keeps shifting past any model's training cutoff. `/optimize` may
propose items beyond the baseline when it has good reason to, always tagged
**`(emerging — verify still current)`** so the human knows it wasn't
checklist-verified.

## No refuse gate

`/optimize` is hygiene and DX, not security — there's no frontier/reasoner
wall the way `/audit` has one. It states a soft `mid, reasoner` preference
(judgment about "is this standard actually relevant here" benefits from a
stronger model) and runs on any tier that picks it up.

## Where it ships

- Claude: `.claude/commands/optimize.md`
- Grok: `.grok/skills/optimize/SKILL.md`
- Docs: [Skills → `/optimize`](/skills/optimize)
- Scaffolded with the other dual-use skills (`scripts/anchor.py`) — it
  installs into every project scaffolded or reconciled with Anchor, not just
  this repo

Written plans default to sticky **`.plans/drafts/opt-<kebab>.local.md`** —
review and promote with **`/draft --promote`**, or execute directly with
**`/work`** once they land in a ready lane.
