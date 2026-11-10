---
sidebar_position: 1.5
sidebar_label: Quick Start
---

# Quick Start

Two paths, same destination: get Anchor into a project and start planning and executing work with disciplined agents.

- **[For Non-Technical People](#for-non-technical-people)** — plain-language setup using your coding agent (Claude Code or Grok Build).
- **[For Technical People](#for-technical-people)** — clone, CLI flags, endpoints, and the full operator loop.

If you only want the big picture first, skim [the one-paragraph version on the intro](/#the-one-paragraph-version), then come back here.

---

## For Non-Technical People

You do **not** need to memorize shell commands. You need:

1. A coding agent that supports Anchor skills (**Claude Code** or **Grok Build**).
2. A copy of the [Anchor repository](https://github.com/carefreeinv/anchor) on your machine (or someone who can put it there once).
3. The app or project folder you want Anchor to help with.

### What Anchor does (in plain English)

Anchor is a **process kit**, not a new chat model. It teaches your agent to:

- **Plan** work as short, trackable documents (instead of one endless chat).
- **Do one clear job at a time**, then check that it really worked.
- Use **cheaper / local models** for routine steps and save the expensive model for planning and review.

Day to day, once `anchor` is on PATH, the same loop is **`anchor work`**, **`anchor review`**, and **`anchor draft "<desc>"`**. In Claude or Grok, tell the agent to prefer those verbs after one probe; slash `/work` `/review` `/draft` stay the in-harness aliases.

### Step 1 — Get Anchor on your computer

Ask a technical friend, or open a terminal in a place you keep projects and run:

```bash
git clone https://github.com/carefreeinv/anchor.git
cd anchor
```

Then open that folder in Claude Code or Grok Build.

### Step 2 — Make the `anchor` command available

In the agent chat (still in the Anchor folder), type:

```text
/install-anchor
```

Follow the prompts. This puts the `anchor` command on your PATH without needing admin/sudo in the normal case. Details: [`/install-anchor`](/skills/install-anchor).

### Step 3 — Pick your defaults once

Still in the Anchor checkout, type:

```text
/config
```

Answer the short survey: which platforms you use (e.g. Claude, Grok), whether you want fleet tooling, model priority, and who should coordinate multi-step work. Your answers are saved so later projects can scaffold without re-deciding everything.

(If `/config` is not available, ask the agent: “Run `./config.sh` and help me through the questions.”)

### Step 4 — Turn on Anchor in *your* project

Open the project you actually work on (your app, website, etc.) in the same agent. Then either:

- Type **`/anchor`** and follow the agent (in a normal project this updates **this** folder), **or**
- From the Anchor repo, type **`/anchor /path/to/your-app`** so the agent scaffolds that path.

When it finishes, your project has Anchor instructions, plan folders under **`.plans/`**, and skills like `/draft` and `/work`.

### Step 5 — Your daily loop

| You want to… | Type this | What happens |
|--------------|-----------|--------------|
| Capture an idea as a plan | `anchor draft "fix login button"` (or `/draft`) | Writes a draft under `.plans/drafts/` |
| See drafts | `anchor draft --list` | Lists what is waiting |
| Make a draft ready for agents | `anchor draft --promote <name>` | Moves it to bugs or features |
| Have the agent do ready work | `anchor work` (or `/work`) | Picks a fit plan and implements it |
| Sign off finished agent work | `anchor review` (or `/review`) | Critic, then you approve or send work back |
| Empty queue, `dev` ahead of `main` | `anchor review --promote` | Promotion review (you still confirm) |
| Background workers on a machine | `anchor fleet-watch` | Optional; for always-on pullers |

You do **not** need to understand every folder under `.plans/` on day one. Promote drafts when they look clear; run `anchor work` when you want implementation; use `anchor review` when work is ready for you.

In Claude or Grok, ask the agent to probe `anchor work --help` once this session and prefer the CLI for the rest. Full contract: [Plan workflow verbs](/tooling/plan-verbs).

### If something feels stuck

- **`anchor` not found** → run [`/install-anchor`](/skills/install-anchor) again (or open a new terminal after install).
- **No plans / empty backlog** → start with [`/draft`](/skills/draft).
- **Want the “why”** → read [The Playbook](/playbook) and [Doctrine](/doctrine) when you are ready; they are optional for first use.
- **Platform-specific install notes** → [Claude Code](/platforms/claude-code), [Grok Build](/platforms/grok-build).

---

## For Technical People

Operator path: doctrine → defaults → scaffold → plan/execute → optional fleet.

### 1. Clone and install the CLI

```bash
git clone https://github.com/carefreeinv/anchor.git
cd anchor
```

Register the CLI with [**`/install-anchor`**](/skills/install-anchor) (user-local symlink, no sudo), or:

```bash
mkdir -p ~/.local/bin && ln -sfn "$(pwd)/bin/anchor" ~/.local/bin/anchor
# ensure ~/.local/bin is on PATH
```

`pip install -e .` (or `pipx install .`) from the repo root also works if you want a packaged `anchor` command. That install is the scaffolder plus the plan-workflow verbs (`anchor plans | work | review | draft`). Fleet scripts under `scripts/` stay copy-paste by design, so `anchor work --run` still needs a checkout (`bin/anchor`).

> **Editable install fails with "build backend is missing the 'build_editable' hook"?** Old distro pip/setuptools (e.g. Ubuntu 22.04 + setuptools 59) leaking into build isolation. Use a venv (`python3 -m venv .venv && . .venv/bin/activate && pip install -e .`), `pip install -e . --no-build-isolation`, or `pipx install .`.

### 2. Read the doctrine

[Doctrine](/doctrine) (`anchor/ANCHOR.md` in the repo) is the behavioral contract everything else implements. Skim it before you invent process on top of Anchor.

### 3. Set defaults

```bash
./config.sh
# or /config in Claude Code / Grok Build
```

Picks default platform(s), fleet tooling, **model priority**, and **preferred orchestrator** (who coordinates multi-step work and cross-plan **Depends on** analysis). Saves under `~/.config/anchor/defaults` and prints the exact `anchor <project-dir>` command to scaffold with those defaults.

Non-interactive example:

```bash
./config.sh --platform claude,grok --fleet --language node \
  --model-priority nim,claude:sonnet,claude:opus \
  --orchestrator claude:opus
```

Skipping this step is fine — `anchor --platform claude,grok` (etc.) or the interactive survey still works without saved defaults.

### 4. Scaffold a project

```bash
cd my-app && anchor                         # current dir + saved defaults
anchor <project-dir> --platform claude,grok # explicit path / platforms
```

From the Anchor checkout, **`/anchor <project-path>`** (path required) runs the CLI with conflict-aware help when the target already has agent config. **Inside a scaffolded project**, `/anchor` (no path) locates the local Anchor checkout and conforms **this** project.

Useful flags — full reference on [the CLI page](/tooling/cli):

| Flag | Purpose |
|------|---------|
| `--fleet` | Include fleet/script scaffolding |
| `--framework <name>` | Skip framework detection |
| `--orchestrator` / `--set-orchestrator` | Preferred planner/coordinator |
| `--dry-run` | Preview without writing |
| `--check` / `--diff` / `--upgrade --yes` | Refresh an existing install |

### 5. Plan and execute

Daily loop from a terminal ([Plan workflow verbs](/tooling/plan-verbs)). In a coding agent, probe once then prefer the same argv; slash [`/work`](/skills/work) [`/review`](/skills/review) [`/draft`](/skills/draft) are harness adapters.

```bash
cd /path/to/your-app          # directory that contains .plans/
anchor plans                  # every plan, by lane; --board for the kanban
anchor work --list --tier mid # ready plans with your fit; claim nothing
anchor work                  # claim top ready plan + execute (interactive and headless)
anchor work --no-run         # claim only
anchor work --finish <slug>   # in-progress → review-needed/ (execute exit 0 also parks)
anchor review --list
anchor review                 # critic on the top review-needed/ plan
anchor review --promote       # empty queue: integration → mainline (explicit)
anchor draft "fix leftover worktrees"
anchor models list
anchor fleet-watch --status
```

`anchor --help` is the scaffolder. Verb help is `anchor work --help` (etc.). Headless or `--json` prints schema-v1 JSON. `--run` is the default for `anchor work` (interactive **and** headless). Empty `review-needed/` with integration ahead of mainline: `anchor review` exits 2 and names `anchor review --promote`. The CLI claims, heartbeats, finishes, and (after an in-terminal Approve) fast-forward merges to `dev`; `--no-finish` keeps the lease after a successful execute. Unattended `python scripts/work_once.py --once --run --ensure-worktree --endpoint …` is the no-TTY fallback if headless `anchor work` is refused.

Architecture for always-on workers: [Fleet workers](/tooling/fleet-workers). Skills map: [Skills overview](/skills/overview).

### 6. Endpoints and the full loop (optional)

Point `scripts/endpoints.yaml` at your OpenAI-compatible endpoints; use `scripts/orchestrate.py` for plan → execute → critic across them. Serve notes live under [Hardware](/hardware/h100); model quirks stay in `anchor_client.py`, never in callers.

```bash
# examples — see scripts/ and hardware docs for your layout
python scripts/work_once.py --list --tier mid --agent-id worker-1
python scripts/orchestrate.py --help
```

### Next reads

1. [Doctrine](/doctrine) — behavioral contract  
2. [Playbook](/playbook) — economics / orchestrator pattern  
3. [Savings](/savings) — projected inference savings  
4. [Skills](/skills/overview) · [Platforms](/platforms/claude-code) · [Tooling](/tooling/cli)
