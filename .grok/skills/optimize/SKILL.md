---
name: optimize
description: >
  Scan the current project against known/emerging/popular standards for its
  detected type (web app, CLI/library, docs site, general repo hygiene),
  propose up to 10 ranked improvement candidates, and write only human-picked
  candidates as .plans files. Use when the user runs /optimize, or asks for
  a site-standards check, OG image / robots.txt / llms.txt scan, or repo
  hygiene review.
argument-hint: "[path|--dry-run|--write|--to drafts|features|bugs|--continue]"
disable-model-invocation: false
metadata:
  short-description: "Standards scan → checkbox-picked improvement plans"
---

# /optimize — standards scan → checkbox-picked improvement plans

Scan the current project against **known / emerging / popular standards for
projects of its detected type** (web app, CLI/library, docs site, or general
repo hygiene), propose **up to 10** ranked improvement candidates, let the
human **pick a subset**, then write only the picked candidates as `.plans`
files.

This is a **hygiene / discoverability / DX** skill, not a security scanner —
see `/audit` for that. Home: **one project, one scan, plan proposals only.**

`$ARGUMENTS` is everything after `/optimize`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/optimize` | Full scan → findings package → checkbox confirm → write plans |
| `/optimize <path>` | Scan that project root (else CWD / git root) |
| `/optimize --dry-run` | Full scan + findings table; **zero** plan files |
| `/optimize --write` | Skip confirm; write **all** presented candidates |
| `/optimize --to drafts` | Explicit default write lane (private `.local.md`) |
| `/optimize --to features` / `--to bugs` | Opt-in: write straight to a ready lane (same bug-vs-feature inference `/draft --promote` uses) |
| `/optimize --continue` | Re-present the deferred backlog from a prior capped run; confirm write |

Flags may combine (e.g. `/optimize --dry-run --to features`).

## Hard rules

1. **Soft model preference, no refuse gate.** State fit in one line
   (`Preferred models: mid, reasoner` — judgment about "is this standard
   actually relevant here" benefits from a stronger model) but **never**
   block a `mid` or `small` session from running it. Unlike `/audit`, there is
   no frontier/reasoner-only gate. **Grok (4.5 or 4.6) is mid-class** for this
   note — high effort is a cost dial, not a tier promotion.

2. **One project, one session.** Full pipeline once; present; write; **stop**.
   Never auto-chain into `/work` on the new plans.

3. **Pipeline order (hard):**

   ```text
   resolve project → detect project type(s)
     → build applicable-standards checklist → check presence/absence in repo
     → rank + cap at 10 candidates → present findings package (human)
     → checkbox confirm subset (or --dry-run / --write)
     → emit chosen candidates as .plans/drafts/*.local.md
     → footer
   ```

4. **No plan writes before the findings package** is presented, unless the
   human already passed `--write` or clear "propose and write these"
   language in the same turn. **`--dry-run`:** never write plan files.

5. **Never implement the suggestions.** This skill proposes plans; it does not
   add `robots.txt`, wire OG images, or touch any product file itself.

## 1. Resolve project

Find a root with source and preferably `.plans/` (CWD, then git root, then
explicit path). Print the absolute path. If missing / not a project: explain
and stop.

## 2. Detect project type(s)

Never propose web-only suggestions at a pure CLI/library project, or vice
versa. A project may match more than one row — union the applicable
categories.

| Signal | Type | Applicable categories |
|--------|------|------------------------|
| `index.html` + bundler config, or SSR framework (Next/Nuxt/SvelteKit/Astro/Docusaurus) | Web app / site | Sharing (OG/Twitter cards), discoverability (`robots.txt`, `sitemap.xml`, `llms.txt`), PWA (manifest, favicon set), structured data, perf basics |
| `package.json` with `bin`, or no web framework, published to npm | CLI / library | `CODEOWNERS`, `SECURITY.md`, `CONTRIBUTING.md`, semantic versioning/release config, CI badge, `.editorconfig` |
| Docs site (Docusaurus/MkDocs/Sphinx/VitePress markers) | Docs | `llms.txt`/`llms-full.txt`, sitemap, search config, versioned-docs hygiene |
| Any repo | General | dependency-update bot (`dependabot.yml`/`renovate.json`), `LICENSE`, `CHANGELOG`, issue/PR templates, `.gitignore` completeness |

## 3. Build the standards checklist

Apply the **baseline checklist** below for every detected category (floor, not
ceiling — see below).

| Category | Check for |
|----------|-----------|
| Sharing / social | `<meta property="og:*">`, `twitter:card`, a real (non-default) preview image asset |
| Crawler discoverability | `robots.txt`, `sitemap.xml`, canonical URLs |
| AI-agent discoverability | `llms.txt` (and `llms-full.txt` for larger docs sites) |
| PWA / icons | `manifest.json`/`site.webmanifest`, favicon set (not just a single 16x16) |
| Structured data | `schema.org` JSON-LD on key pages (article/product/org as applicable) |
| Security posture (non-vuln) | `SECURITY.md`, `.well-known/security.txt` |
| Community / repo health | `CODEOWNERS`, `CONTRIBUTING.md`, issue/PR templates, `LICENSE`, badge(s) in README |
| Dependency hygiene | `dependabot.yml` / `renovate.json` present |
| Dev ergonomics | `.editorconfig`, CI config present, `CHANGELOG` maintained |

**Checklist is a floor, not a ceiling.** Standards for "popular/emerging" keep
shifting past any training cutoff — you **may** propose additional items
beyond the baseline when you have good reason to believe a convention is now
common, and **must** label those extra items `(emerging — verify still
current)` in the findings package so the human knows they weren't
checklist-verified.

## 4. Check presence/absence

For each applicable checklist item, look for the marker file(s)/pattern in the
repo. Mark **present** / **missing** / **weak** (e.g. a favicon exists but is
a single low-res `.ico`, no larger sizes).

## 5. Rank + cap at 10

Each **applicable but missing/weak** check becomes **one** candidate:

**Impact/effort → Priority map:**

| Priority | Criteria | Examples |
|----------|----------|----------|
| **P1** | High impact, low effort, broadly expected for the detected type | Missing `robots.txt`/sitemap on a public site, no `LICENSE` on an OSS repo |
| **P2** | Real value, moderate effort, or narrower applicability | OG image pipeline, `llms.txt`, dependency-bot config |
| **P3** | Nice-to-have / polish / emerging | Structured data beyond basics, extended favicon set, badge polish |

**Cap:** propose **at most 10** candidates per run, highest Priority first
within each detected category — prefer at least **one candidate per
applicable category** before filling out P3 depth in any single one. If more
than 10 applicable gaps exist, list the deferred count in the footer;
`/optimize --continue` re-surfaces the next slice next run.

## 6. Present findings package

Before any write, show:

1. Project path + detected type(s)
2. Per-category status (checked / N/A for this project type)
3. Findings table: Priority, title, one-line rationale, effort estimate
   (trivial/small/medium), `(emerging — verify still current)` tag if beyond
   baseline
4. Write plan: lane (`drafts/` default, or named `--to` lane), count, cap
   leftovers

## 7. Checkbox confirm

Unless `--dry-run` or `--write` (or clear same-turn write language):

Prefer `ask_user_question` (checkbox semantics) when available — this is the
point of the request, not a numbered-reply fallback. Fall back to "reply with
the numbers you want" only when no such UI exists.

| Option | Meaning |
|--------|---------|
| **Pick subset** | Human selects which candidates to write |
| **Write all** | All presented candidates |
| **Cancel** | No files written |

Unchecked candidates are discarded, not persisted anywhere — re-running
`/optimize` regenerates them if still applicable. On cancel or dry-run:
footer only; zero plan files.

## 8. Emit plans

For each checked candidate, write **one** file:

| Field | Rule |
|-------|------|
| Path | Default **`.plans/drafts/<basename>`**. `--to features`/`--to bugs` writes straight to a ready lane instead (apply the same bug-vs-feature inference `/draft --promote` uses: hygiene/fix-shaped → `bugs/`, new-capability-shaped → `features/`). Never write into `in-progress/`, `review-needed/`, or `completed/`. |
| Basename | `opt-<short-kebab>.local.md` (sticky `.local`). Collisions → `-2`, `-3`, … |
| Title / Goal | Enhancement-oriented: what standard, what component |
| **Priority** | From the impact/effort map (required) |
| **Value** | `high`\|`medium`\|`low` (features-style; this is enhancement work) |
| **Preferred models** | Size to the actual task — `small` for a static `robots.txt`/`llms.txt` drop-in, `mid` for OG image generation wiring, `reasoner` only for anything genuinely architectural |
| **Depends on** | `none` unless truly blocked by another plan in this batch |
| Body | One-line rationale, effort estimate, `(emerging — verify still current)` tag if applicable |

Shape follows `.anchor/templates/plan.md` (or `anchor/templates/plan.md`): no
`Lane:` / `Status:` fields.

### Plan body template (emit this shape)

```markdown
# Plan: <enhancement-oriented title>

- **Value:** high|medium|low
- **Priority:** P1|P2|P3
- **Slug:** opt-<short-kebab>
- **Preferred models:** <sized to the actual task>
- **Depends on:** none

## Goal

<one sentence: what standard, what component, why it matters here>

## Context

- Detected project type: <type>
- Effort estimate: trivial|small|medium
- <(emerging — verify still current) if beyond baseline>

## Steps

| # | Task | Touches | Verify by | Route to |
|---|------|---------|-----------|----------|
| 1 | <concrete step> | <files> | <check> | <tier> |

## Done when

- <checkable condition>
```

## 9. Footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: project path, detected type(s), findings count, plans written
(paths) or dry-run/cancel, cap backlog, deferred count. **Do not** start
`/work` on the new plans.

## Out of scope

- Implementing any proposed change (OG images, `robots.txt`, etc.) — plans
  only
- Security vulnerability scanning (`/audit`'s job)
- Executing the written plans (`/work`)
- Promoting drafts (except writing new files into `drafts/`, or the explicit
  `--to features`/`--to bugs` escape hatch)

## Quick discovery

```bash
# project root
ls -la
ls index.html package.json pyproject.toml docusaurus.config.* mkdocs.yml 2>/dev/null
# existing standards markers
ls robots.txt sitemap.xml llms.txt manifest.json SECURITY.md CODEOWNERS \
   dependabot.yml renovate.json .editorconfig LICENSE 2>/dev/null
# plans layout
ls -la .plans/drafts .plans/bugs .plans/features 2>/dev/null
```
