---
description: Exhaustive security audit (code + deps) → prioritized bug plans; frontier/reasoner only
argument-hint: "[path|--dry-run|--write|--to drafts|bugs|--force-model|--deps-only|--code-only|--include-noise|--continue]"
---

# /audit — security audit → prioritized bug plans

Run an **exhaustive security-oriented audit** of the current project (first-party
code **and** third-party dependencies), then **write one `.plans` bug-fix plan
per distinct finding** so the fleet can close holes without rediscovery.

This is **not** a pen-test product, not auto-remediation, and not a free-form
“review this PR” skill. Home: **one project, one audit session, plans only**.

`$ARGUMENTS` is everything after `/audit`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/audit` | Full audit → findings package → confirm → write bug plans |
| `/audit <path>` | Audit that project root (else CWD / git root) |
| `/audit --dry-run` | Full audit + findings table; **zero** plan files |
| `/audit --write` | Skip post-findings confirm; write all eligible plans after package |
| `/audit --to drafts` | Write under `.plans/drafts/` instead of `.plans/bugs/` |
| `/audit --to bugs` | Explicit default write lane |
| `/audit --force-model` | Override mid/small model gate (print risk line first) |
| `/audit --deps-only` | Dependency / supply-chain buckets only |
| `/audit --code-only` | First-party code buckets only |
| `/audit --include-noise` | Keep low-signal/informational scanner hits |
| `/audit --continue` | After a prior capped run: re-present deferred backlog; confirm write |

Flags may combine (e.g. `/audit --dry-run --deps-only`).

## Hard rules

1. **Frontier / reasoner only by default.** Classify this session’s fit tier
   (`frontier` | `reasoner` | `mid` | `small`) using the same spirit as `/work`
   model-fit and `.anchor/model-fitness.md` (or project copy). Catalog names:
   Fable/Opus-class → reasoner/frontier; Sonnet/Grok 4.5 → **mid**; Haiku/local
   small → **small**. If you are **mid or below** (or clearly not
   frontier/reasoner-class), **refuse**:

   ```text
   skip: /audit — underqualified (need: frontier|reasoner; you: <model>/<tier>)
   → re-run on a reasoner/frontier session
   → /audit --force-model to override (risk: false negatives / noisy plans)
   ```

   With **`--force-model`**: print one risk acknowledgment line, then continue.
   Default is refuse, not soft-warn-and-continue.

2. **One project, one session.** Full pipeline once; present; write; **stop**.
   Never auto-chain into `/work` on the new plans.

3. **Pipeline order (hard):**

   ```text
   resolve project → model-fit gate → inventory surface
     → dependency audit → first-party code audit
     → dedupe / severity / priority map
     → present findings package (human)
     → confirm write set (or --write / --dry-run)
     → emit bug plans under .plans/
     → footer
   ```

4. **No plan writes before the findings package**, unless the human already
   passed `--write` or clear “audit and file bug plans” language in the same
   turn. **`--dry-run`:** never write plan files.

5. **Plans only — no fixes, no exploits.** Never implement remediations, never
   write exploit PoCs / weaponized payloads / proof shells into chat, Steps, or
   the repo. **Redact** secrets (path + last 4 chars or hash only).

6. **No public disclosure side-effects.** Do not `git push`, open public issues,
   or contact third parties about vulns unless the human explicitly asks outside
   this skill’s default path. No destructive remediation from `/audit`.

## 1. Resolve project

Find a root with source and preferably `.plans/` (CWD, then git root, then
explicit path). Print the absolute path. If missing / not a project: explain and
stop.

## 2. Model-fit gate

Apply Hard rule 1. Stop on refuse.

## 3. Inventory surface

List detected ecosystems (markers below), top-level languages, presence of
`.plans/`, CI configs, MCP/`mcp/` if any. Report which audit **buckets** will
run given flags (`--deps-only` / `--code-only`).

## 4. Dependency / supply-chain audit

For each detected ecosystem, run the best available **non-interactive,
read-oriented** tool. On missing tools: status **tool missing** + residual risk
— **do not invent CVEs**.

| Ecosystem | Markers (any) | Prefer |
|-----------|---------------|--------|
| **Node** | `package-lock.json` / `pnpm-lock.yaml` / `yarn.lock` / `package.json` | Match lockfile: `npm audit --json` / `pnpm audit` / `yarn npm audit` |
| **Python** | `requirements*.txt`, `pyproject.toml`, `Pipfile.lock`, `poetry.lock` | `pip-audit` if installed; else skip + manual checklist |
| **Rust** | `Cargo.lock` | `cargo audit` if installed |
| **Go** | `go.sum` / `go.mod` | `govulncheck` if installed |
| **Other** | `composer.lock`, `Gemfile.lock`, etc. | Best-effort tool or explicit “no automated scanner” |

Also note: missing lockfiles, risky install scripts (`postinstall`), obvious
unpinned `latest` where cheap. Record stderr tails on failure.

## 5. First-party code audit

Cover every applicable bucket (mark **ran** / **skipped** / **N/A**):

| Bucket | Look for |
|--------|----------|
| **Secrets & credentials** | API keys, tokens, private keys, committed `.env`, cloud creds |
| **Injection** | SQL/command/path/template; unsafe `eval` / `pickle` / `yaml.load` / deserialize |
| **AuthZ / AuthN** | Missing checks, IDOR-shaped handlers, open admin routes |
| **Web/API** | XSS sinks, CSRF, SSRF-shaped fetches, CORS `*`, verbose errors |
| **Filesystem / process** | Path traversal, unsafe temp files, `shell=True`, privilege flags |
| **Crypto** | Hard-coded keys/IVs, MD5/SHA1 for security, TLS verify disabled |
| **CI / ops** | Workflow secrets printed, world-writable scripts, privileged containers |
| **Agent / MCP** (if present) | Over-broad tool allowlists, untrusted path exec, secret leakage into prompts |

Use search + targeted reads. Prefer a **fresh-context read-only critic subagent**
when the platform supports it (same spirit as `/review` AI pass) so the
orchestrator is not the sole author of severity.

## 6. Dedupe and severity → Priority

Merge scanner + manual hits on the same root cause. Drop pure informational
noise unless `--include-noise`.

| Severity | Priority | Examples |
|----------|----------|----------|
| Critical / High | **P1** | RCE, auth bypass, committed live secrets, critical CVE in reachable dep |
| Medium | **P2** | Limited XSS, medium CVE in used path, missing auth on non-admin |
| Low / hygiene | **P3** | Defense-in-depth, unused transitive, informational scanner noise |

Cap: if more than **25** distinct findings, keep all **P1**, then **P2** by
impact, until 25; put the rest in the footer as a numbered backlog (human can
`/audit --continue`).

## 7. Present findings package

Before any write, show:

1. Project path + model tier used (+ force-model note if any)
2. Per-bucket status table (ran / skipped / tool missing / N/A)
3. Findings table: severity, Priority, short title, evidence (file:line or
   package@version + advisory id), suggested fix **direction** (not exploit)
4. Write plan: lane (`bugs/` or `drafts/`), count, cap leftovers
5. Residual risk (tools missing, buckets skipped)

## 8. Confirm write set

Unless `--dry-run` or `--write` (or clear same-turn write language):

Prefer platform ask UI when available:

| Option | Meaning |
|--------|---------|
| **Write all** | All findings in the presented set (after cap) |
| **Write P1 only** | Critical/high only |
| **Pick subset** | Human lists numbers / titles |
| **Cancel** | No files written |

On cancel or dry-run: footer only; zero plan files.

## 9. Emit bug plans

Each **distinct, actionable** finding → **one** plan file:

| Field | Rule |
|-------|------|
| Path | Default `.plans/bugs/<basename>`; `--to drafts` → `.plans/drafts/` |
| Basename | `sec-<short-kebab>.local.md` (sticky `.local`). Collisions → `-2`, `-3`, … |
| Title / Goal | Fix-oriented: vulnerability class + component |
| **Priority** | From severity map (required) |
| **Preferred models** | `frontier, reasoner` — or **`frontier` alone** for critical/RCE-class |
| **Value** | **Omit** (bugs are pure fixes) |
| **Depends on** | `none` unless truly blocked by another plan in this batch |
| **Done when** | Machine-checkable fix + test or re-scan note |
| **Steps** | Concrete **repair** steps only — **no exploit steps** |
| Body | Evidence, impact, fix direction, residual risk |

Shape follows `.anchor/templates/plan.md` (or `anchor/templates/plan.md`): no
`Lane:` / `Status:` fields. Never write into `in-progress/`, `review-needed/`,
or `completed/`.

### Plan body template (emit this shape)

```markdown
# Plan: <fix-oriented title>

- **Priority:** P1|P2|P3
- **Slug:** sec-<short-kebab>
- **Preferred models:** frontier, reasoner
- **Depends on:** none

## Goal

<one sentence: restore safe behavior>

## Context

- Evidence: `<path>:<line>` or `package@version` + advisory id
- Impact: <who/what is exposed>
- (redacted) secret path if any: `<path>` ends `…<last4>`

## Constraints

- No exploit code in Steps or tests beyond safe regression asserts
- Prefer minimal fix; do not drive-by refactor

## Steps

| # | Task | Touches | Verify by | Route to |
|---|------|---------|-----------|----------|
| 1 | <repair step> | <files> | <test or re-scan> | reasoner |

## Done when

- <checkable condition>
- Relevant scanner/test clean or documented residual
```

## 10. Footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: project path, model gate outcome, buckets status, findings count,
plans written (paths) or dry-run/cancel, cap backlog, residual risk.
**Do not** start `/work` on the new plans.

## Out of scope

- Live penetration testing, authenticated cloud account scans, paid SaaS SAST
- Writing or running exploit PoCs
- Auto-implementing fixes
- Public CVE disclosure / security advisories for the product
- Executing the bug plans (`/work`)
- Promoting drafts (except writing new files into `drafts/` when `--to drafts`)

## Quick discovery

```bash
# project root
ls -la
ls package.json pyproject.toml Cargo.toml go.mod 2>/dev/null
# plans layout
ls -la .plans/bugs .plans/drafts 2>/dev/null
# scanners (use what exists)
command -v npm pip-audit cargo govulncheck
```
