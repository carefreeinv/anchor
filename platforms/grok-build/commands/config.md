# /config — Anchor defaults helper (Grok Build)

<!-- (unverified) Grok Build's file-based custom-command convention, if any, isn't
     documented publicly as of this writing. If your Grok Build environment loads
     custom commands from a folder, drop this file there under the name `config`.
     Otherwise paste the body below into custom instructions, or skip the command
     entirely and just run `./config.sh` yourself — this file only exists to make
     `/config` mean the same thing everywhere Anchor is installed. -->

When the user types `/config`:

1. Ask which platform(s) they want as their Anchor default — `claude`, `grok`,
   `nemotron`, `local:<model>` (qwen3, gemma3, mistral-small, deepseek-r1-distill,
   llama33), and/or `chat` — and whether to include fleet/orchestration tooling.
   Also ask their **model priority** (cheapest-first, frontier last is usual) and
   **preferred orchestrator** (who plans/coordinates; lesser models defer to it).
   Tokens are `<provider>` or `<provider>:<model>` — e.g.
   `nim,grok,openai:gpt-5,claude:sonnet,claude:opus,claude:fable` and orchestrator
   `claude:opus` (blank orchestrator = last priority token).
2. Run, from the Anchor repo root: `./config.sh --platform <keys> [--fleet]
   [--model-priority <ordered,list>] [--orchestrator <token>]` (non-interactive form —
   the interactive prompts in `./config.sh` with no flags can't be driven through a chat turn).
3. Relay exactly what it printed: defaults path, model priority, preferred orchestrator,
   and `anchor <project-dir>`. Mention per-project: `anchor <dir> --set-orchestrator <token>`.
4. Point the user to https://carefreeinv.com/anchor for further help.

Mark anything about your specific Grok Build environment's command mechanism as
`(unverified)` per the hard rules in `../GROK.md` — don't assert this file is
wired up unless you've confirmed it.
