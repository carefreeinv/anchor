# AIDER.md — Anchor discipline for Aider (drone harness)

<!-- Drop this into a repo's root and add `read: AIDER.md` to `.aider.conf.yml`
     (see `.aider.conf.yml.example` alongside this file) so every Aider session
     loads it automatically. Verified against https://aider.chat/docs/usage/conventions.html
     and https://aider.chat/docs/config/options.html on 2026-09-09: the config
     key is `read:` (string or `[a, b]` list); there is no separate `read-only:`
     config key — `--read FILE` is the one-off CLI/env (`AIDER_READ`) equivalent. -->

## Role: drone, not queen-bee

Aider sessions here are usually a **small local model** (Qwen3 4B/8B class) run
through Ollama/llama.cpp — cheap, fast, but not the model that should be making
architectural calls. The split is **queen-bee plans, drone executes**:

- **Queen-bee** (Claude Code, Grok Build, or a human) writes plans into
  `.plans/drafts/` and promotes them to `.plans/bugs/` or `.plans/features/`.
- **Drone** (you, in Aider) only runs **`/work`** against an already-ready plan.
  You do not draft, promote, review, or merge.

If the user types `/draft`, `/review`, or anything else Anchor-shaped: say that
plans are authored and reviewed in a queen-bee session (Claude Code / Grok
Build), and offer to run `/work` on whatever is already ready instead.

## The only skill you run: `/work`

**Verified against Aider 0.86.2, 2026-09-11: type `work`, not `/work`.** Aider
*does* have its own slash-command runtime — it treats any chat message that
*starts* with `/` as one of its own built-in commands (`/add`, `/diff`, …)
and replies `Invalid command: work` without ever calling you; a literal
`/work` never reaches you. Treat the word **`work`** (optionally followed by
a plan slug, e.g. `work my-slug`, or embedded mid-sentence — anything not
starting with `/`) as an instruction to follow this procedure yourself, using
your shell/file tools:

1. **Pick a plan.** No slug given → look under `.plans/bugs/` first, then
   `.plans/features/`; pick the first by `Priority` (P1 → P2 → P3, default P2),
   then `Value` (high → medium → low, default medium), then oldest file. A slug
   given → find `<slug>.md` or `<slug>.local.md` under those two lanes.
2. **Check dependencies.** Skip (report why) if the plan's `Depends on:` names a
   slug not yet under `.plans/completed/`.
3. **Claim it.** Move the file to `.plans/in-progress/` (same filename, keep
   `.local.md` if present). Never touch a plan already sitting in
   `.plans/in-progress/` unless you are the one who put it there.
4. **Execute `## Steps` in order.** One row at a time; run each row's
   **Verify by** command before moving to the next. Two failed fix attempts on
   the same error → stop, summarize what you tried, and say the plan needs a
   stronger model (queen-bee session) — do not keep guessing.
5. **Before committing anything outside `.plans/`:** run the project's test
   command (check `README`/`Makefile`/CI config for what "tests" means here)
   and fix failures. Add a one-line `CHANGELOG.md` entry under `[Unreleased]`
   only for a user-visible change — skip it for internal-only edits. Skip the
   blog-post judgment call entirely; that needs a bigger model or a human.
6. **Commit on `feature/<slug>`**, not on `main`/`dev`. If the repo has no such
   branch yet, create it from the integration branch (`dev`, else `develop`,
   else `main`).
7. **Finish to `review-needed/`.** Move the plan file there and stop — **you
   never merge, and you never ask a merge question.** A queen-bee session or a
   human runs `/review` next.
8. If a step is genuinely ambiguous or the plan itself looks half-baked, move
   it to `.plans/ambiguous/` (with a note) or `.plans/blocked/` and stop rather
   than guessing at scope.

## Standing rules

- Restate the plan's Goal and `## Done when` before you start executing it.
- Touch only files the current plan's Steps name. Log anything else you notice
  under `## Deferred / concerns` in your own reply — don't fix it opportunistically.
- Never claim "this works" — name the command that verifies it, then run it.
- **Docs describe current state, not plans.** `README`/`docs/`/`CHANGELOG`
  cover shipped code only — never restate a `.plans/` file's contents as
  documentation.

## Memory-safe local default

Before assuming this box can run the largest model that theoretically fits,
check for Anchor's fleet probe if this project has one:

```bash
python .anchor/scripts/fit_device.py --probe   # or scripts/fit_device.py in the Anchor checkout
```

It reports **Max fit** (capability ceiling) alongside **Default for wire**
(the memory-safer pick under real free-RAM pressure) — prefer the wire default
for your own model choice on WSL/iGPU/≤16GB-class machines; only opt up if the
probe shows healthy free RAM.

## WSL + Ollama

If `OLLAMA_API_BASE` / `AIDER_MODEL` point at `localhost` and calls fail on
WSL2, the Ollama server is usually reachable via the Windows host, not the WSL
guest's own loopback — see the fleet probe's `Bare metal:` / `Executor place:`
lines above for the address to use instead of guessing.

## Unattended twin

This file covers interactive Aider sessions only. The same reachable Ollama
URL also works headless via `work_once.py`/`fleet_watch.py` — a machine-local
`endpoints.yaml` entry (e.g. `var/endpoints.local.yaml`, never the shared
`scripts/endpoints.yaml`) using this host's URL under a shared name like
`laptop-swarm` — for unattended plan-claiming without an Aider session
running. See [Local Models](/skills/local-models)'s drone recipe.
