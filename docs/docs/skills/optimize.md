---
sidebar_position: 3.8
sidebar_label: /optimize · standards → improvement plans
---

# `/optimize`

**Best used:** when you want to check a project against **known, emerging, and
popular standards for its type** — sharing metadata, crawler/AI discoverability,
PWA/icons, repo health, dependency hygiene — and turn any gaps into plans a
human can pick from. See [Skills overview](/skills/overview).

`/optimize` is **hygiene / discoverability / DX**, not security — see
[`/audit`](/skills/audit) for vulnerability scanning. It never implements a
suggestion itself; it only proposes plans.

## Why use it

| Without `/optimize` | With `/optimize` |
|----------------------|-------------------|
| Standards knowledge lives in one contributor's head | A baseline checklist runs the same way every time |
| Web-only or CLI-only advice gets suggested at the wrong project type | Project-type detection gates the checklist first |
| "Add everything" floods the backlog | Capped at 10, ranked by impact/effort, checkbox-picked |
| Suggestions get implemented sight-unseen | Plans only — human picks, `/work` executes later |

## Usage

| Invocation | Behavior |
|------------|----------|
| `/optimize` | Full scan → findings package → checkbox confirm → write plans |
| `/optimize <path>` | Scan that project root |
| `/optimize --dry-run` | Findings only; **zero** plan files |
| `/optimize --write` | Write all presented candidates without confirm |
| `/optimize --to drafts` | Default write lane (private `.local.md`) |
| `/optimize --to features` / `--to bugs` | Opt-in: straight to a ready lane |
| `/optimize --continue` | Resume a capped backlog from a prior run |

## Pipeline

```text
resolve project → detect project type(s)
  → build applicable-standards checklist → check presence/absence
  → rank + cap at 10 candidates → present findings (human)
  → checkbox confirm (or --write / --dry-run)
  → emit chosen candidates → stop
```

Never auto-starts `/work` on the new plans.

## Project-type detection

| Signal | Type | Applicable categories |
|--------|------|------------------------|
| SSR framework / bundled `index.html` | Web app / site | Sharing (OG/Twitter cards), `robots.txt`/`sitemap.xml`/`llms.txt`, PWA, structured data |
| `package.json` with `bin`, published library | CLI / library | `CODEOWNERS`, `SECURITY.md`, `CONTRIBUTING.md`, release config, `.editorconfig` |
| Docusaurus/MkDocs/Sphinx/VitePress markers | Docs | `llms.txt`/`llms-full.txt`, sitemap, search config |
| Any repo | General | dependency bot, `LICENSE`, `CHANGELOG`, issue/PR templates |

A project can match more than one row; applicable categories union.

## Impact/effort → Priority

| Priority | Criteria | Examples |
|----------|----------|----------|
| **P1** | High impact, low effort, broadly expected | Missing `robots.txt`/sitemap on a public site, no `LICENSE` |
| **P2** | Real value, moderate effort, or narrower fit | OG image pipeline, `llms.txt`, dependency bot |
| **P3** | Nice-to-have / polish / emerging | Structured data beyond basics, extended favicon set |

The **baseline checklist is a floor**: the skill may propose additional items
it believes are now common practice, always tagged
`(emerging — verify still current)` so the human knows it wasn't
checklist-verified.

## Write rules

- Default lane: **`.plans/drafts/opt-<kebab>.local.md`** (sticky `.local`)
- `--to features`/`--to bugs` for an explicit human opt-in straight to a ready
  lane, using the same bug-vs-feature inference [`/draft --promote`](/skills/draft) uses
- Cap **10** candidates per run; remainder deferred to `--continue`
- Plan shape matches the [plan template](https://github.com/carefreeinv/anchor/blob/main/anchor/templates/plan.md) (no `Lane:` / `Status:`)

## Model fit

Soft preference only (`mid, reasoner`) — unlike `/audit`, there is **no**
refuse gate. A `small` or `mid` session runs it normally.

## Scaffolded?

Yes — dual-use Claude command + Grok skill (`scripts/anchor.py` platform lists),
so it installs into every project scaffolded or reconciled with Anchor, not
just this repo.

Full contract: source `.claude/commands/optimize.md` / `.grok/skills/optimize/SKILL.md`.
