---
sidebar_position: 3.6
sidebar_label: /audit · security → bug plans
---

# `/audit`

**Best used:** when you want an **exhaustive security-oriented audit** of the
current project (first-party code **and** dependencies) and **prioritized bug
plans** the fleet can execute — without rediscovering holes ad hoc. See
[Skills overview](/skills/overview).

`/audit` is **plans only**: it does not implement fixes, does not pen-test live
systems, and must not write exploit PoCs. Default sessions are **frontier /
reasoner only**; mid/small models refuse unless the operator passes
`--force-model`.

## Why use it

| Without `/audit` | With `/audit` |
|------------------|---------------|
| Security findings live in chat and get lost | Each finding becomes a `.plans` bug plan with Priority |
| Weak models confidently miss holes | Runtime model gate + Preferred models on every fix plan |
| Scanner noise floods the ready queue | Severity map, 25-plan cap, confirm before write |
| Fixes and “proof” shells mix into the audit | Hard ban on exploits; redacted evidence only |

## Usage

| Invocation | Behavior |
|------------|----------|
| `/audit` | Full audit → findings package → confirm → write plans |
| `/audit <path>` | Audit that project root |
| `/audit --dry-run` | Findings only; **zero** plan files |
| `/audit --write` | Write after package without confirm |
| `/audit --to drafts` | Private drafts instead of ready `bugs/` |
| `/audit --force-model` | Override mid/small refuse (risk acknowledged) |
| `/audit --deps-only` / `--code-only` | Narrow buckets |
| `/audit --include-noise` | Keep low-signal scanner hits |
| `/audit --continue` | Resume capped backlog from a prior run |

## Pipeline

```text
resolve project → model-fit gate → inventory
  → dependency audit → first-party code audit
  → dedupe / severity → Priority
  → present findings → confirm (or --write / --dry-run)
  → emit bug plans → stop
```

Never auto-starts `/work` on the new plans.

## Severity → Priority

| Severity | Priority | Examples |
|----------|----------|----------|
| Critical / High | **P1** | RCE, auth bypass, committed secrets, critical reachable CVE |
| Medium | **P2** | Limited XSS, medium CVE in used path |
| Low / hygiene | **P3** | Defense-in-depth, unused transitive noise |

Every emitted plan sets **`Preferred models: frontier, reasoner`** (or
`frontier` alone for critical/RCE-class) so mid/small fleet workers skip under
normal fit rules.

## Write rules

- Default lane: **`.plans/bugs/sec-<kebab>.local.md`** (sticky `.local`)
- `--to drafts` for human promote later
- Cap **25** plans per run; remainder in footer / `--continue`
- Plan shape matches the [plan template](https://github.com/carefreeinv/anchor/blob/main/anchor/templates/plan.md) (no `Lane:` / `Status:`)

## Safety

- No exploit payloads or weaponized “proofs”
- Redact secrets (path + last 4 / hash)
- No public disclosure side-effects from the skill defaults
- No destructive remediation from `/audit` itself

## Scaffolded?

Yes — dual-use Claude command + Grok skill (`scripts/anchor.py` platform lists).

Full contract: source `.claude/commands/audit.md` / `.grok/skills/audit/SKILL.md`.
