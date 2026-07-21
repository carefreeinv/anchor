<!-- synced-from: platforms/grok-build/GROK.md @ 60474fd326aac1e75ac99d83fc837dac93d21db0 -->
---
sidebar_position: 2
sidebar_label: Grok Build
---

<!-- synced-from: platforms/grok-build/GROK.md @ PENDING -->

# Grok Build

Install: place `platforms/grok-build/GROK.md` at your repo root; paste its session preamble into custom instructions if your Grok Build environment supports them.

## Grok's failure profile

Fast, eager, terse: it acts before planning, compresses reasoning it should show, and over-trusts first drafts. In long sessions it weights recent instructions over early ones, so discipline set at session start decays.

## The countermeasures

The hard rules as a forced pipeline (Grok's default is to skip ahead):

```mermaid
flowchart LR
  r["Restate"]
  p["Plan"]
  s["One step"]
  v["Verify"]
  f["Footer"]
  r --> p --> s --> v --> f
  s -->|"two fails"| stop["Stop + escalate"]
```

The hard rules (restate → plan → one-step-per-turn → verify-don't-claim → mark `(unverified)` → two-fail stop → scope → footer → **docs describe current state, not plans** → **`/commit-prep` before any `git commit`** → **capacity limits are a scheduling problem**, not a failure: checkpoint, then reroute to the next model clearing the task's fitness floor, wait for a near reset, or stop and report — see [capacity routing](/capacity-routing)) plus three Grok-specific ones:

- Force risk enumeration before the plan ("list 3 ways this could go wrong") — surfaces the reasoning Grok skips.
- **One task spec per session.** Restart instead of accumulating context; instruction decay makes long Grok sessions untrustworthy.
- Architecture and security-adjacent steps are marked `Route to: bigger model` in the plan — Grok doesn't decide these alone.

## Grok 4.5 (reviewed 2026-07-08)

Play to the strength: terminal/CLI-driven steps are Grok 4.5's best fit (GPT-5.5-class on terminal benchmarks, unusually token-efficient). Compensate for the weakness: it measurably trails Fable/GPT tiers on repo-scale issue resolution, so decompose to file-scoped task specs before handing work over. API `reasoning_effort` defaults to *high* — set low for mechanical steps or pay a token multiple for nothing. In the TUI use **`/effort low`** (or `/model <id> low`); CLI/headless: **`--effort low`**. Catalog tier for Preferred matching is **mid** — high effort is a cost dial, not a frontier promotion. Before [**`/work`**](/skills/work) burns high effort on mid plans, probe for a cheaper local/fleet executor (`scripts/endpoints.yaml`); if none are reachable, emit the effort command rather than a dead stop. Community-reported tool-use flakiness `(unverified)` makes external verification load-bearing. A poor-fit task gets a `SUGGEST-ESCALATE:` first line per the fit check in `.anchor/model-fitness.md`, not a silent attempt. Symmetrically, **mid is a floor Grok clears, not a ceiling to apologize for**: repo-scale issue resolution is the documented weak spot, file-scoped `mid` plans are not — and a plan whose **Preferred models** also names a stronger product is still a good fit, since only listed *tiers* gate.

If MCP is available, connect `anchor-prompts` and call `tune_prompt` on any vague task before starting, and `preflight_check` before executing any spec.

## Tracked plans

Scaffold installs [**`/draft`**](/skills/draft), [**`/work`**](/skills/work), [**`/review`**](/skills/review), [**`/fleet-watch`**](/skills/fleet-watch), [**`/install-anchor`**](/skills/install-anchor), [**`/anchor`**](/skills/anchor) (conform **this** project; CWD default), and [**`/local-models`**](/skills/local-models). Draft: create/list/load/`--promote <slug>` (infer bugs vs features); optional `--local`. `/work` finishes → `review-needed/`; human `/review` → `completed/`. Git: **worktree per agent** (`worktree_for_agent.py`), feature branches from `dev`/`develop` (**create `dev` from main/master if missing**). Grok 4.5 may act as temporary coordinator when Preferred orchestrator is unset. `/install-anchor` registers the CLI on PATH (user-local symlink, no sudo). Full contract: source `platforms/grok-build/GROK.md`.

## /commit-prep

**Required before any `git commit`.** Agents run `/commit-prep` (discover this project’s tests/CI; CHANGELOG; blog-if-warranted — no Docusaurus required). **Prep only** — does not commit. After a green prep, [**`/work`**](/skills/work) / standing rules cover feature-branch commit (worktree preferred; never merge to dev/main).
