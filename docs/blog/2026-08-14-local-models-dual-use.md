---
slug: local-models-dual-use
title: /local-models is now a dual-use skill
authors: [carefree]
tags: [feature, skills, tooling]
---

`/local-models` used to exist only after you scaffolded a project. It now
lives in the **Anchor checkout** the same way `/work` does — so you can ask
"what can this box run?" before a project exists — and is still copied into
Claude and Grok projects. The probe is still **this host only**.

<!-- truncate -->

## The gap

The [July 9 skills post](/blog/2026/07/09/agent-skills-scaffold-local-models/)
introduced `/local-models` as a scaffolded-only command: source under
`platforms/…`, installed into a project, missing from the Anchor tree
itself. That left a hole on the first machine you open the checkout on.
Sizing a lean local executor is a *host* question, not a *project*
question, and the skill that answers it was gated behind a scaffold you
had not run yet.

## Dual-use, like `/work`

Source of truth is now the base skill:

| Platform | Path |
|----------|------|
| Grok Build | `.grok/skills/local-models/SKILL.md` |
| Claude Code | `.claude/commands/local-models.md` |

`anchor … --platform claude` or `--platform grok` still copies those files
into the project. The probe is the same either way; the write surfaces
differ:

- **In the Anchor checkout** — operator defaults via `config.sh` / `/config`
  so this machine's local token can follow you across scaffolds, plus an
  optional draft to register a LAN/shared fleet stanza or a machine-local
  overlay for localhost.
- **In a scaffolded project** — still the optional `.plans/drafts/` draft
  (`local-executor-<model>.local.md`): install lives in **Prerequisites**,
  conventions stay portable ("local when reachable"), and the endpoint
  wiring prefers a machine-local overlay.

## This host only

A project is often cloned onto a laptop, a desktop, and a CUDA box with
different RAM and backends. The skill treats that as the default, not an
edge case:

1. **Probe is always this host.** A teammate's "we run 70B locally" note is
   not evidence on this machine.
2. **Host fit is not project law.** Do not commit this laptop's model size,
   quant, or `http://127.0.0.1:11434` as if every clone has that capacity.
3. **Prefer machine-local writes:** `~/.config/anchor/defaults`, a
   gitignored overlay such as `endpoints.local.yaml`, and `.local.md`
   drafts.
4. **Shared conventions stay portable:** "use a local executor when
   reachable" and a tier ceiling — not "everyone runs Qwen3-32B on
   localhost".
5. **Fleet/LAN is different.** A lab H100 at `10.x` may still be committed;
   that is a shared endpoint, not a this-laptop endpoint.

Stale other-host config (`127.0.0.1`, `localhost`, a hostname that does not
resolve here) is a warning and a re-derive, never a silent trust.

## What the report still does

`scripts/fit_device.py --probe` plus a readable, link-rich write-up:

- **Machine profile** — guest OS + WSL?; on WSL, **host** RAM/CPU/GPU via
  `powershell.exe`, not the guest cgroup
- **Executor placement** — prefer a **Windows bare-metal** model server
  under WSL; Anchor stays in the guest and points a machine-local registry
  at the host API
- **Best lean fit** from the catalog (Qwen3, Gemma 3, Mistral Small, R1
  distills, Llama 3.3) sized to this host's budget
- **Install path** for the detected OS — official docs and weight links,
  not a guessed `pip install`
- **Routing policy** — the operator's **model-priority** list stays
  primary; small locals stay on light tiers; a host that can run heavy
  local inference may prefer a fit local for that work, without promoting
  a 4B CPU model into a frontier role

No silent `pip install vllm`, no multi-GB pull without confirmation. A
recommendation is not a promise the endpoint answers after reboot, or on
the next clone.

## Existing projects

Projects whose manifest still records `src` as
`platforms/grok-build/skills/local-models/SKILL.md` or
`platforms/claude-code/commands/local-models.md` are remapped by
`anchor --check` / `anchor --upgrade`. You do not hand-edit the manifest
to pick up the new source path.

```bash
anchor --check
anchor --upgrade --dry-run
```

## Where to read it

- [Skills → `/local-models`](/skills/local-models)
- [Skills overview](/skills/overview)
- [Local models (platform notes)](/platforms/local-models)
- [Personal devices](/hardware/personal-devices)
- [The `anchor` CLI](/tooling/cli)
