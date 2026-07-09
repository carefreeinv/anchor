---
description: Set your Anchor platform/fleet/model-priority defaults and show how to scaffold a project with them
allowed-tools: Bash(./config.sh:*), Bash(*/config.sh:*)
---

Help the user set their Anchor defaults, then show them how to use them.

1. Ask the user (in chat, not via a terminal prompt):
   - which platform(s) they want as their default — `claude`, `grok`, `nemotron`,
     `local:<model>` (models: qwen3, gemma3, mistral-small, deepseek-r1-distill, llama33),
     and/or `chat` — and whether to include fleet/orchestration tooling by default;
   - their **model priority**: the order they'd reach for / escalate between models,
     highest priority first (the usual convention is cheapest-first, frontier last).
     Tokens are `<provider>` or `<provider>:<model>` — providers are `claude`, `openai`
     (ChatGPT), `gemini`, `grok`, `nim`, `local`, `chat`; e.g.
     `nim,grok,openai:gpt-5,claude:sonnet,claude:opus,claude:fable`;
   - their **preferred orchestrator** (who plans/coordinates multi-step work; lesser
     models should recommend this instead of orchestrating themselves) — same token
     form, e.g. `claude:opus`. Blank = last model-priority entry.
   If `$ARGUMENTS` already looks like `--platform ...` / `--model-priority ...` /
   `--orchestrator ...` flags, use those instead of asking.
2. Run `./config.sh --platform <keys> [--fleet] [--model-priority <ordered,list>]
   [--orchestrator <token>]` from the Anchor repo root via the Bash tool (non-interactive
   form — don't run it with no flags, since its interactive prompts can't be answered
   through this command). If `./config.sh` isn't at the current directory, find the
   Anchor repo root first (it contains `ANCHOR.md`, `platforms/`, `scripts/anchor.py`).
3. Report back exactly what it printed: where the defaults were saved, model priority,
   preferred orchestrator, and the `anchor <project-dir>` command. Mention per-project
   change: `anchor <project-dir> --set-orchestrator <token>`.
4. Point the user to https://carefreeinv.com/anchor for further help.

Don't invent platform keys or file paths beyond what `./config.sh --help` and
`python3 scripts/anchor.py --list` report — check those if unsure.
