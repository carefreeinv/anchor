# Changelog

Notable, user-visible changes to Anchor. Updated by `/commit-prep` before each
commit; format loosely follows [Keep a Changelog](https://keepachangelog.com).
Newest first.

## [Unreleased]

### Added
- Tracked **`.plans/`** workflow (git-tracked tree; do not ignore wholesale): lanes `bugs/` → `features/` → archive `completed/`; non-executable `drafts/`; process contract in `.plans/README.md`
- Local-only plans: **`<slug>.local.md`** under any lane, ignored by scaffolded `.plans/.gitignore` (`**/*.local.md`); `/work <slug>` matches tracked or local filenames
- **`/work`** entrypoint (Claude `.claude/commands/work.md`, Grok `.grok/skills/work/SKILL.md`, Chat section in `CHAT.md`) — pick/execute next ready plan; `--list`, `--no-fit-check`; honors plan **Preferred models**
- Plan template header fields: Lane, Value, Status, Slug, Preferred models (`small|mid|reasoner|frontier` or names)
- `scripts/check_plans.py` — lane/section sanity for `.plans/`
- `orchestrate.py --plan-file` rejects paths under `.plans/drafts/` or `.plans/completed/`; examples use ready lanes
- Scaffold always installs empty `.plans/` tree + README + `.plans/.gitignore` (ignores `*.local.md`); sources under `anchor/scaffold/plans/`; Claude gets `/work` command, Grok gets work skill
- `anchor/model-fitness.md` — per-model excels/weak matrix (Claude tiers, GPT-5.6 Sol/Terra/Luna, Grok 4.5, Gemini, Nemotron, all local models; reviewed 2026-07-08) + the fit-check protocol; scaffolded into every project and mirrored on the docs site
- Fit check (mythos-core rule 11): a model handed a poor-fit task opens with `SUGGEST-ESCALATE: <model> — <reason>` and stops; `orchestrate.py` escalates/holds immediately without burning attempts, `--insist` overrides
- `ANCHOR-CONVENTIONS.md` now carries a model-routing section with the operator's saved model priority (generated even when no framework is detected)
- Grok 4.5 notes in `GROK.md` (terminal-strong / repo-scale-weak, `reasoning_effort` economics) and ChatGPT/GPT-5.6 notes in `CHAT.md` (over-eagerness system-card caveats, Sol/Terra/Luna tier guidance)
- `scripts/fit_device.py` — size a model/quant/context to a personal device's RAM/VRAM; prints a launch command and an `endpoints.yaml` stanza with the right quirks
- `hardware/personal-devices/` tier (Mac Mini, MacBook Pro, RTX laptops, desktop towers) with `configs/serve-apple-silicon.sh` and `configs/serve-cuda.sh`
- Model-priority preference: `./config.sh --model-priority nim,grok,openai:gpt-5,claude:sonnet,...` (also prompted interactively and via `/config`); recorded in each scaffold's `.anchor-manifest.json` and shown by `--check`
- Registry quirks in `anchor_client.py`: `system_suffix` guardrail injection, `temperature`/`temperature_thinking` overrides, `sampling`/`sampling_thinking` passthrough, `max_context` completion cap, and a never-greedy-while-thinking clamp
- `/commit-prep` command (Claude Code, Grok Build, chat) — pre-commit tests/release-notes/blog pass
- Docs-site blog (Docusaurus) with `docs/blog/`

### Changed
- Docs site: top-level **Skills** sidebar section for platform-agnostic entrypoints (starts with `/work`); Platforms pages no longer re-document the skill contract
- Docs site: hardware section split into per-device pages; added the `anchor` CLI reference and a quick start on the landing page
- DeepSeek-R1 endpoints now fold system text into the user turn per official guidance (`system_role: fold_into_user`), emitted by `fit_device.py`
- `endpoints.yaml` examples pin per-model sampling recommendations (Qwen3 thinking top_p/top_k, Nemotron greedy-when-off)

### Fixed
- **Agent move rule for `.plans/`:** agents may only relocate a plan ready-lane → `completed/` when Done when holds; promotion (`drafts/` → `bugs|features`) is human-only (docs, `/work`, platforms, MCP planner prompt)
- Sidebar labels on synced docs pages (explicit `sidebar_label` front matter)
- README note for editable installs on old distro pip/setuptools (PEP 660 workaround)
