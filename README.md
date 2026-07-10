# Anchor

[![Donate](https://img.shields.io/badge/Donate-Stripe-f96854?logo=stripe&logoColor=white)](https://donate.stripe.com/28E6oHeq8fxQ5p7fmBdjO01)

Make less-powerful models behave like a Mythos-class model (Claude Fable 5) through structured prompting, orchestration, and verification — instead of raw capability.

An open-source project by [Carefree Investments LLC](https://carefreeinv.com).

Built from two ideas:

- Treat frontier models as a metered resource: reserve them for long-horizon judgment, run the **orchestrator pattern** (frontier plans + reviews, cheap models execute), tune prompts on a cheap model before an expensive run, and benchmark your own workload instead of trusting a routing table on faith.
- Serve capable open models locally ([Qwen3](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html) family, [Gemma 3](https://ai.google.dev/gemma/docs/core), [Mistral Small](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503), [DeepSeek-R1 distills](https://huggingface.co/collections/deepseek-ai/deepseek-r1), [Llama 3.3](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) via llama.cpp / vLLM) using the quantization, context-length, and chat-template choices that consistently work well in practice. Model names link to official quick starts.

## The core idea

A Mythos-class model's edge is not intelligence-per-token — it's **discipline over long horizons**: clarify → plan → decompose → execute small verified steps → self-review → verify against acceptance criteria. Lesser models can approximate this when the discipline is imposed *externally*: by system prompts, forced output formats, one-task-at-a-time context, and verification loops run by tooling rather than trusted to the model.

## Layout

| Path | Purpose |
|---|---|
| `anchor/` | Model-agnostic doctrine, system prompts, and templates (scaffolded into projects as **`.anchor/`**) |
| `platforms/` | Instructions for Claude Code, Grok Build, NVIDIA NIM/Nemotron, local models, and generic chat UIs |
| `hardware/personal-devices/` | Mac Mini, AI-optimized laptops, single-GPU desktops |
| `hardware/h100/` | H100 nodes (vLLM, NIM containers) |
| `hardware/space-1-vera-rubin/` | Space-1 Vera Rubin modules (latency-tolerant, autonomy-first ops) |
| `scripts/` | Python utilities: prompt tuner, orchestrator, `work_once` / `fleet_watch`, router, benchmark, device-fit |
| `mcp/` | MCP servers: `anchor-prompts` (scaffolding tools), `model-fleet` (delegation/routing) |
| `docs/` | Docusaurus documentation site (`cd docs && npm install && npm start`) |
| Scaffold plans | Projects get a tracked `.plans/` tree (`/work`); source: `anchor/scaffold/plans/` |

**Docs rule (all Anchor projects):** documentation describes the project’s **current shipped state**, not `.plans/` backlog. See `CLAUDE.md` / `anchor/ANCHOR.md`. This repository’s own `.plans/` (if present) is private working backlog and must not appear in public docs.

## Quick start

1. Read `anchor/ANCHOR.md` — the doctrine everything else implements.
2. Run `./config.sh` (or type `/config` in Claude Code / Grok Build) to pick your default platform(s), whether you want fleet tooling, model priority, and **preferred orchestrator** (who coordinates multi-step work; e.g. `claude:opus`). It saves your answer and shows you the exact `anchor <project-dir>` command to scaffold a project with it.
3. Scaffold a project (`cd my-app && anchor`, or `anchor <project-dir>`). From the Anchor repo, **`/anchor <project-path>`** (path required) runs the CLI with conflict-aware help when the project already has agent config. **Inside a scaffolded project**, `/anchor` (no path) locates the local Anchor checkout and conforms **this** project. Then use **`/work`** for ready plans under `.plans/`, or **`/fleet-watch`** for reboot-persistent pullers. Set a durable orchestrator anytime: `anchor --set-orchestrator …`. Refresh an existing install: `anchor --check` / `anchor --diff` / `anchor --upgrade --yes` (or project `/anchor`).
4. Point `scripts/endpoints.yaml` at your endpoints; use `scripts/orchestrate.py` to run the orchestrator pattern across them — see your `hardware/` folder's README to serve models on your own fleet. Fleet design: docs **Tooling → Fleet workers**.

Skipping step 2 is fine too — `anchor --platform claude,grok` (etc.) or the interactive survey it falls back to both still work without saved defaults.

Register the CLI with **`/install-anchor`** (agent skill: user-local symlink, no sudo), or symlink `bin/anchor` onto your PATH yourself. `pip install -e .` (or `pipx install .`) from the repo root also works if you'd rather have a packaged `anchor` command — it only installs the scaffolder itself, not the fleet scripts (those stay copy-paste, by design).

> **Editable install fails with "build backend is missing the 'build_editable' hook"?** That's an old distro pip/setuptools (e.g. Ubuntu 22.04 ships setuptools 59, which predates PEP 660) leaking into pip's build isolation — not a problem with this repo. Install into a virtualenv (`python3 -m venv .venv && . .venv/bin/activate && pip install -e .`), or use `pip install -e . --no-build-isolation`, or `pipx install .`.

## Support

If Anchor saves you time or compute, consider [donating](https://donate.stripe.com/28E6oHeq8fxQ5p7fmBdjO01) to support continued development.

## License

[MIT](LICENSE) — Carefree Investments LLC.

---

Built and maintained by [Carefree Investments LLC](https://carefreeinv.com).
