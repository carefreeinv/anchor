#!/usr/bin/env python3
"""anchor — scaffold a project with Anchor doctrine for one or more model platforms.

Asks which platform(s) a project should be optimized for (Claude Code, Grok Build,
NVIDIA NIM/Nemotron, local models, generic chat UIs), then copies the relevant
doctrine + platform files from this repo into the target project. Refuses to
overwrite: any destination file that already exists is reported as a conflict
and NOTHING is written, so the user can resolve it and re-run.

Usage:
  python scripts/anchor.py                                      # scaffold current directory
  python scripts/anchor.py <project-dir>                        # interactive survey
  python scripts/anchor.py <project-dir> --platform claude,grok  # non-interactive
  python scripts/anchor.py <project-dir> --platform local:qwen3,local:gemma3 --fleet
  python scripts/anchor.py <project-dir> --framework rust        # skip framework detection/prompt
  python scripts/anchor.py --list                                # show platform keys
  python scripts/anchor.py --check                               # drift summary (no writes)
  python scripts/anchor.py --diff                                # status + unified diffs (no writes)
  python scripts/anchor.py --upgrade                             # bring project up to current scaffold
  python scripts/anchor.py --upgrade --yes                       # non-interactive safe upgrade
  python scripts/anchor.py --upgrade --yes --force               # also take locally modified files
  python scripts/anchor.py --set-orchestrator claude:opus
  python scripts/anchor.py --yes                                 # scaffold without confirmation prompt

If no --platform is given and ../config.sh has saved defaults (~/.config/anchor/defaults
by default, override with $ANCHOR_CONFIG_DIR), those defaults are used automatically.

Before writing a *new* scaffold, when no overwrite conflicts exist, the CLI prints draft
findings and asks you to confirm. Pass --yes to skip (required for non-interactive writes).
--dry-run previews only.

Also detects the target project's language/framework from marker files (composer.json,
package.json, Cargo.toml, go.mod, ...) and writes its idiomatic-composition guidance to
.anchor/conventions.md. When package.json coexists with a backend marker, the non-node
language wins. If detection fails (blank/ambiguous project) and stdin is a tty, it
asks — proposing the saved config.sh language default, if any.

**Preferred orchestrator** (who should plan / coordinate long-horizon work for this
project) is set via `./config.sh --orchestrator …`, scaffold `--orchestrator …`,
`anchor <dir> --set-orchestrator …`, or by editing the bold line in
.anchor/conventions.md. Lesser models are instructed to recommend that orchestrator
instead of attempting orchestration themselves.

Every scaffold also writes .anchor-manifest.json recording which anchor commit,
platforms, and file hashes were used. Later, **--check** / **--diff** / **--upgrade**
(alias **--update**) compare that project to the current Anchor source: refresh
upstream content, restore missing managed files, migrate legacy layout
(``anchor/`` → ``.anchor/``), and optionally add newly introduced scaffold files
for the project's recorded platforms. Locally modified files are kept unless
``--force``. Nothing is overwritten without ``--upgrade`` (and confirmation / ``--yes``).

Typical shell alias so it can be run as `anchor project/bar`:
  alias anchor="python3 /path/to/Anchor/scripts/anchor.py"
(or symlink bin/anchor, included alongside this script, onto your PATH)
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_FILE = Path(os.environ.get("ANCHOR_CONFIG_DIR", Path.home() / ".config" / "anchor")) / "defaults"
MANIFEST_NAME = ".anchor-manifest.json"
# Generated project conventions (framework idiom + preferred orchestrator).
CONVENTIONS_REL = ".anchor/conventions.md"
CONVENTIONS_LEGACY_REL = "ANCHOR-CONVENTIONS.md"

# Doctrine every platform needs. Source paths live under this repo's `anchor/`
# package; scaffold *destination* is the project's `.anchor/` tree
# (alongside optional `.anchor/mcp.yaml`). Source layout is unchanged.
CORE_FILES: list[str] = [
    "anchor/ANCHOR.md",
    "anchor/model-fitness.md",
    "anchor/capacity-routing.md",
    "anchor/system-prompts/mythos-core.md",
    "anchor/templates/plan.md",
    "anchor/templates/task-spec.md",
    "anchor/templates/review.md",
    "anchor/templates/verification.md",
]


def doctrine_dest(src_rel: str) -> str:
    """Map source ``anchor/<path>`` → scaffold dest ``.anchor/<path>``."""
    if not src_rel.startswith("anchor/"):
        raise ValueError(f"doctrine source must be under anchor/: {src_rel!r}")
    return ".anchor/" + src_rel[len("anchor/") :]


def fleet_dest(src_rel: str) -> str:
    """Map fleet source paths → project ``.anchor/scripts|mcp/…`` (never project root)."""
    rel = src_rel.replace("\\", "/").lstrip("./")
    if rel.startswith("scripts/"):
        return ".anchor/" + rel
    if rel.startswith("mcp/"):
        return ".anchor/" + rel
    raise ValueError(f"fleet source must be under scripts/ or mcp/: {src_rel!r}")


def conventions_path(project_dir: Path, *, for_write: bool = False) -> Path:
    """Path to project conventions file.

    Prefer ``.anchor/conventions.md``. When reading, fall back to legacy root
    ``ANCHOR-CONVENTIONS.md``. When writing, always use the preferred path
    unless only the legacy file exists and ``for_write`` is False for open.
    """
    preferred = project_dir / CONVENTIONS_REL
    legacy = project_dir / CONVENTIONS_LEGACY_REL
    if for_write:
        return preferred
    if preferred.is_file():
        return preferred
    if legacy.is_file():
        return legacy
    return preferred


# Fleet/orchestration tooling — optional, only relevant once you're actually running
# more than one model against the project. Scaffolded under `.anchor/` so they do
# not collide with a project's own scripts/ or mcp/ trees.
FLEET_FILES: list[str] = [
    "scripts/anchor_client.py",
    "scripts/orchestrate.py",
    "scripts/work_once.py",
    "scripts/plan_select.py",
    "scripts/plan_lease.py",
    "scripts/worktree_for_agent.py",
    "scripts/fleet_watch.py",
    "scripts/prompt_tuner.py",
    "scripts/router.py",
    "scripts/benchmark.py",
    "scripts/fit_device.py",
    "scripts/endpoints.yaml",
    "scripts/requirements.txt",
    "mcp/anchor-prompts/server.py",
    "mcp/anchor-prompts/pyproject.toml",
    "mcp/anchor-prompts/README.md",
    "mcp/model-fleet/server.py",
    "mcp/model-fleet/pyproject.toml",
    "mcp/model-fleet/README.md",
    "mcp/project-orchestrator/server.py",
    "mcp/project-orchestrator/coordinator.py",
    "mcp/project-orchestrator/pyproject.toml",
    "mcp/project-orchestrator/README.md",

]

LOCAL_MODEL_FILES: dict[str, str] = {
    "qwen3": "platforms/local-models/qwen3.md",
    "gemma3": "platforms/local-models/gemma3.md",
    "mistral-small": "platforms/local-models/mistral-small.md",
    "deepseek-r1-distill": "platforms/local-models/deepseek-r1-distill.md",
    "llama33": "platforms/local-models/llama33.md",
}

# platform key -> (label, [(src rel path, dest rel path), ...])
# Single-file platform instructions are dropped at the project root, matching the
# "place at repo root" convention documented in each platforms/*/*.md file.
# Always scaffolded into projects as a *git-tracked* `.plans/` tree.
# Sources live under anchor/scaffold/plans/ (this Anchor repo gitignores its own
# working `.plans/` entirely — local backlog for developing Anchor). Project
# projects must NOT gitignore the whole tree; only `*.local.md` plans are
# ignored (via the scaffolded `.plans/.gitignore`).
PLANS_TREE_FILES: list[tuple[str, str]] = [
    ("anchor/scaffold/plans/README.md", ".plans/README.md"),
    ("anchor/scaffold/plans/.gitignore", ".plans/.gitignore"),
    ("anchor/scaffold/plans/bugs/.gitkeep", ".plans/bugs/.gitkeep"),
    ("anchor/scaffold/plans/features/.gitkeep", ".plans/features/.gitkeep"),
    ("anchor/scaffold/plans/in-progress/.gitkeep", ".plans/in-progress/.gitkeep"),
    ("anchor/scaffold/plans/ambiguous/.gitkeep", ".plans/ambiguous/.gitkeep"),
    ("anchor/scaffold/plans/blocked/.gitkeep", ".plans/blocked/.gitkeep"),
    ("anchor/scaffold/plans/review-needed/.gitkeep", ".plans/review-needed/.gitkeep"),
    ("anchor/scaffold/plans/drafts/.gitkeep", ".plans/drafts/.gitkeep"),
    ("anchor/scaffold/plans/completed/.gitkeep", ".plans/completed/.gitkeep"),
]

PLATFORMS: dict[str, dict] = {
    "claude": {
        "label": "Claude Code",
        "files": [
            ("platforms/claude-code/CLAUDE.md", "CLAUDE.md"),
            # NB: /config is deliberately NOT scaffolded (neither here nor for grok).
            # It sets the *operator's* Anchor defaults (~/.config/anchor/defaults) and
            # runs ./config.sh from the Anchor checkout — it has nothing to act on
            # inside a scaffolded project.
            (".claude/commands/work.md", ".claude/commands/work.md"),
            (".claude/commands/draft.md", ".claude/commands/draft.md"),
            (".claude/commands/review.md", ".claude/commands/review.md"),
            (".claude/commands/commit-prep.md", ".claude/commands/commit-prep.md"),
            (".claude/commands/fleet-watch.md", ".claude/commands/fleet-watch.md"),
            (".claude/commands/install-anchor.md", ".claude/commands/install-anchor.md"),
            # Scaffolded skills (source under platforms/; Anchor /anchor is path-required base)
            ("platforms/claude-code/commands/local-models.md", ".claude/commands/local-models.md"),
            ("platforms/claude-code/commands/anchor.md", ".claude/commands/anchor.md"),
        ],
    },
    "grok": {
        "label": "Grok Build",
        "files": [
            ("platforms/grok-build/GROK.md", "GROK.md"),
            (".grok/skills/work/SKILL.md", ".grok/skills/work/SKILL.md"),
            (".grok/skills/draft/SKILL.md", ".grok/skills/draft/SKILL.md"),
            (".grok/skills/review/SKILL.md", ".grok/skills/review/SKILL.md"),
            (".grok/skills/commit-prep/SKILL.md", ".grok/skills/commit-prep/SKILL.md"),
            (".grok/skills/fleet-watch/SKILL.md", ".grok/skills/fleet-watch/SKILL.md"),
            (".grok/skills/install-anchor/SKILL.md", ".grok/skills/install-anchor/SKILL.md"),
            # Scaffolded skills (source under platforms/; Anchor /anchor is path-required base)
            ("platforms/grok-build/skills/local-models/SKILL.md", ".grok/skills/local-models/SKILL.md"),
            ("platforms/grok-build/skills/anchor/SKILL.md", ".grok/skills/anchor/SKILL.md"),
        ],
    },
    "nemotron": {
        "label": "NVIDIA NIM / Nemotron",
        "files": [("platforms/nvidia-nim/NEMOTRON.md", "NEMOTRON.md")],
    },
    "local": {
        "label": "Local models (Qwen3, Gemma 3, Mistral Small, DeepSeek-R1 distill, Llama 3.3)",
        "files": [("platforms/local-models/README.md", "platforms/local-models/README.md")],
        # extra files chosen per submodel, appended at resolve time
    },
    "chat": {
        "label": "Generic chat UI (ChatGPT-style, no tool execution)",
        "files": [("platforms/chat/CHAT.md", "CHAT.md")],
    },
}

# Marker file (relative to project root) -> language/framework key.
# When several markers match, detect_framework de-prioritizes "node" if another
# language is present (package.json is often frontend/test tooling beside PHP,
# Python, Ruby, etc.).
FRAMEWORK_MARKERS: dict[str, str] = {
    "package.json": "node",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Gemfile": "ruby",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "composer.json": "php",
}

# language/framework key -> idiomatic composition mechanism to prefer over deep
# inheritance (see .anchor/ANCHOR.md in scaffolded projects, "Code quality defaults").
FRAMEWORK_IDIOM: dict[str, str] = {
    "node": "interfaces (TypeScript) or small duck-typed composable objects (JS) — avoid deep class hierarchies",
    "python": "Protocols (PEP 544) / narrow ABCs, composition over inheritance",
    "rust": "traits",
    "go": "small single-method interfaces defined at the point of use",
    "java": "interfaces (default methods over inheritance chains)",
    "ruby": "modules (mixins)",
    "dotnet": "interfaces",
    "php": "interfaces/traits",
}
DEFAULT_IDIOM = ("that language's standard composition mechanism "
                 "(interfaces/protocols/traits) — never a deep inheritance tree")


def resolve_selection(keys: list[str]) -> list[tuple[str, str]]:
    """Turn platform keys (e.g. ["claude", "local:qwen3"]) into (src, dest) pairs."""
    pairs: list[tuple[str, str]] = []
    seen_platforms: set[str] = set()
    for raw in keys:
        raw = raw.strip()
        if not raw:
            continue
        base, _, sub = raw.partition(":")
        base = base.strip().lower()
        sub = sub.strip().lower()
        if base not in PLATFORMS:
            raise SystemExit(
                f"Unknown platform '{base}'. Valid: {', '.join(sorted(PLATFORMS))}. "
                f"Run with --list to see details."
            )
        if base not in seen_platforms:
            pairs.extend(PLATFORMS[base]["files"])
            seen_platforms.add(base)
        if base == "local":
            if not sub:
                raise SystemExit(
                    "local platform requires a model, e.g. local:qwen3. "
                    f"Valid models: {', '.join(sorted(LOCAL_MODEL_FILES))}"
                )
            if sub not in LOCAL_MODEL_FILES:
                raise SystemExit(
                    f"Unknown local model '{sub}'. Valid: {', '.join(sorted(LOCAL_MODEL_FILES))}"
                )
            src = LOCAL_MODEL_FILES[sub]
            pairs.append((src, src))  # keep platforms/local-models/<file>.md layout
    return pairs


def _read_defaults_file() -> dict[str, str]:
    """Parse ~/.config/anchor/defaults (or $ANCHOR_CONFIG_DIR/defaults) into key/value pairs."""
    if not DEFAULTS_FILE.exists():
        return {}
    values: dict[str, str] = {}
    for line in DEFAULTS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


def load_defaults() -> tuple[list[str], bool] | None:
    """Read platform/fleet defaults saved by config.sh, if any. None if unset."""
    values = _read_defaults_file()
    platform_keys = [k for k in values.get("PLATFORMS", "").split(",") if k.strip()]
    if not platform_keys:
        return None
    want_fleet = values.get("FLEET", "0") in {"1", "true", "yes"}
    return platform_keys, want_fleet


def load_saved_language() -> str | None:
    """Read the default language/framework saved by config.sh, if any. None if unset."""
    return _read_defaults_file().get("LANGUAGE", "").strip().lower() or None


def load_model_priority() -> list[str]:
    """Read the ordered model-priority preference saved by config.sh (highest first).

    Tokens are provider or provider:model (e.g. nim, grok, openai:gpt-5, claude:sonnet).
    Empty list if unset. Recorded in each scaffold's manifest so the project carries
    the user's preferred escalation order.
    """
    raw = _read_defaults_file().get("MODEL_PRIORITY", "")
    return [tok.strip().lower() for tok in raw.split(",") if tok.strip()]


def load_orchestrator() -> str | None:
    """Read the preferred orchestrator token saved by config.sh, if any.

    Token form matches model-priority entries (e.g. claude:opus, grok, nim).
    """
    raw = _read_defaults_file().get("ORCHESTRATOR", "").strip().lower()
    return raw or None


def resolve_orchestrator(
    explicit: str | None,
    model_priority: list[str] | None,
    saved: str | None = None,
) -> str | None:
    """Prefer explicit CLI → saved config → last model_priority token (frontier end)."""
    if explicit and explicit.strip():
        return explicit.strip().lower()
    if saved and saved.strip():
        return saved.strip().lower()
    if model_priority:
        # Convention is cheapest-first; last entry is the usual orchestrator pick.
        return model_priority[-1]
    return None


# Matches the bold preferred-orchestrator line in ANCHOR-CONVENTIONS.md
_ORCH_LINE_RE = re.compile(
    r"^(\*\*Preferred orchestrator:\*\*\s*)(`?)([^`\n]+)\2\s*$",
    re.MULTILINE,
)


def parse_orchestrator_from_conventions(text: str) -> str | None:
    """Extract preferred orchestrator token from ANCHOR-CONVENTIONS.md body."""
    m = _ORCH_LINE_RE.search(text)
    if not m:
        return None
    token = m.group(3).strip()
    if not token or token.startswith("_(") or token.lower() in {"unset", "(unset)"}:
        return None
    return token.strip("`").lower()


def set_orchestrator_in_conventions(text: str, orchestrator: str) -> str:
    """Replace or insert the Preferred orchestrator line; keep the rest intact."""
    orch = orchestrator.strip()
    new_line = f"**Preferred orchestrator:** `{orch}`"
    if _ORCH_LINE_RE.search(text):
        return _ORCH_LINE_RE.sub(new_line, text, count=1)
    # Insert after title or at top of Model routing / Preferred section
    if "## Preferred orchestrator" in text:
        return text.replace(
            "## Preferred orchestrator",
            f"## Preferred orchestrator\n\n{new_line}",
            1,
        )
    if "## Model routing" in text:
        return text.replace(
            "## Model routing (fit check)",
            f"## Preferred orchestrator\n\n{new_line}\n\n## Model routing (fit check)",
            1,
        )
    return text.rstrip() + f"\n\n## Preferred orchestrator\n\n{new_line}\n"


def resolve_project_dir(project_dir: str | None) -> Path:
    """Resolve the scaffold target: explicit path, or the current working directory."""
    if project_dir:
        return Path(project_dir).resolve()
    cwd = Path.cwd()
    print(f"No project directory given; using current directory '{cwd}'.")
    return cwd


def format_scaffold_findings(
    project_dir: Path,
    platform_keys: list[str],
    want_fleet: bool,
    framework: str | None,
    model_priority: list[str] | None,
    preferred_orch: str | None,
    plan: list[tuple[Path, Path]],
    conventions: tuple[Path, str] | None,
) -> str:
    """Human-readable draft findings + recommended action (no writes)."""
    framework_line = framework if framework else f"(none — no {CONVENTIONS_REL} language section)"
    orch_line = preferred_orch if preferred_orch else "(unset — frontier session may act as temporary coordinator)"
    priority_line = (
        " > ".join(model_priority) if model_priority else "(none saved)"
    )
    file_lines = [f"  {dest.relative_to(project_dir)}" for _, dest in plan]
    if conventions is not None:
        file_lines.append(f"  {conventions[0].relative_to(project_dir)} (generated)")
    file_lines.append(f"  {MANIFEST_NAME} (generated — compare later with --check)")
    total = len(plan) + (1 if conventions is not None else 0) + 1

    lines = [
        "",
        "## Draft findings",
        "",
        f"Target:              {project_dir}",
        f"Framework:           {framework_line}",
        f"Platforms:           {', '.join(platform_keys)}",
        f"Fleet tooling:       {'yes' if want_fleet else 'no'}",
        f"Preferred orchestrator: {orch_line}",
        f"Model priority:      {priority_line}",
        "Overwrite conflicts: none",
        "",
        "## Recommended action",
        "",
        "Scaffold Anchor doctrine into the target project (copy platform files,",
        f"generate {CONVENTIONS_REL} + .anchor-manifest.json, ensure var/).",
        "Nothing will be overwritten — destinations above do not exist yet.",
        "",
        f"Would write {total} file(s):",
        *file_lines,
        f"  {VAR_DIR_NAME}/ (+ {VAR_DIR_NAME}/worktrees/, root .gitignore → "
        f"{VAR_GITIGNORE_ENTRY}) (ensure)",
        "",
    ]
    return "\n".join(lines)


def confirm_scaffold_write(*, yes: bool) -> bool:
    """Return True if the user confirmed writing. --yes skips the prompt.

    Non-interactive terminals refuse without --yes so automation does not
    silently scaffold.
    """
    if yes:
        print("Proceeding without prompt (--yes).")
        return True
    if not sys.stdin.isatty():
        raise SystemExit(
            "Refusing to write without confirmation in a non-interactive terminal. "
            "Re-run with --yes to proceed, or --dry-run to preview only."
        )
    raw = input("Proceed with this plan? [y/N]: ").strip().lower()
    return raw in {"y", "yes"}


def detect_framework(project_dir: Path) -> str | None:
    """Guess the project's language/framework from marker files. None if blank or ambiguous.

    Collects every matching marker. A lone hit wins. When package.json coexists with
    a backend marker (composer.json, Cargo.toml, …), prefer the non-node language —
    root package.json is commonly Playwright/asset tooling, not the primary stack.
    Pass --framework to override.
    """
    if not project_dir.exists() or not any(project_dir.iterdir()):
        return None
    hits: list[str] = []
    for marker, key in FRAMEWORK_MARKERS.items():
        if (project_dir / marker).exists() and key not in hits:
            hits.append(key)
    if next(project_dir.glob("*.csproj"), None) is not None and "dotnet" not in hits:
        hits.append("dotnet")
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    # Polyglot root: treat node as secondary when another language is present.
    non_node = [h for h in hits if h != "node"]
    if non_node:
        return non_node[0]
    return hits[0]


def resolve_framework(project_dir: Path, cli_framework: str | None, saved_language: str | None) -> str | None:
    """Detect the project's framework, falling back to --framework, a prompt, or the saved default."""
    if cli_framework:
        return cli_framework.strip().lower()

    detected = detect_framework(project_dir)
    if detected:
        print(f"Detected project framework: {detected}")
        return detected

    if sys.stdin.isatty():
        suggestion = f" [{saved_language}]" if saved_language else ""
        raw = input(
            "\nCouldn't detect this project's language/framework (e.g. node, python, "
            f"rust, go, java, ruby, dotnet, php).{suggestion}\n"
            "Enter one, or leave blank to skip: "
        ).strip().lower()
        return raw or saved_language

    if saved_language:
        print(f"No framework detected and no interactive terminal; using saved default '{saved_language}'.")
        return saved_language

    print("No framework detected, no --framework given, and no saved default language "
          f"— skipping {CONVENTIONS_REL} (run ./config.sh to set a default, or pass --framework).")
    return None


def plan_conventions(
    project_dir: Path,
    framework: str | None,
    model_priority: list[str] | None = None,
    orchestrator: str | None = None,
) -> tuple[Path, str] | None:
    """Build the (dest, content) pair for generated ``.anchor/conventions.md``.

    None only when there is nothing to say (no framework, priority, or orchestrator).
    """
    orch = (orchestrator or "").strip().lower() or None
    if not framework and not model_priority and not orch:
        return None
    parts = ["# Anchor conventions for this project\n"]
    if framework:
        idiom = FRAMEWORK_IDIOM.get(framework, DEFAULT_IDIOM)
        parts.append(f"""
Detected/declared language or framework: **{framework}**

- Follow SOLID principles by default (see `.anchor/ANCHOR.md`, "Code quality defaults").
- Prefer {framework}'s idiomatic composition mechanism over deep inheritance: {idiom}.
- Actively avoid spaghetti control flow and dead code; treat shortcuts as tracked
  technical debt (name them in `## Deferred / concerns`), not silent debt.
- Wrong guess? Edit this file — it's just a note for whichever model works on this project next.
""")

    parts.append("\n## Preferred orchestrator\n\n")
    if orch:
        parts.append(f"**Preferred orchestrator:** `{orch}`\n\n")
    else:
        parts.append(
            "**Preferred orchestrator:** _(unset — run "
            "`anchor <project-dir> --set-orchestrator <provider:model>` "
            "or edit this line)_\n\n"
        )
    parts.append(
        "This is who should **plan multi-step work, coordinate fleets, make architecture "
        "calls, review large merges, and evaluate plan **Depends on** against existing "
        "`.plans/**` for this project.\n\n"
        "### Temporary coordinator (when Preferred orchestrator is unset)\n\n"
        "If the Preferred orchestrator line is **unset** / empty and **no** project "
        "MCP coordinator is registered for this tree:\n\n"
        "1. If **you** are a **frontier or near-frontier** model (e.g. Fable-class, "
        "Opus-class, GPT-5.x Sol/Terra-class, Grok 4.5 when used as a strong "
        "session lead — see `.anchor/model-fitness.md`), you **may take a temporary "
        "coordinator role** for this session only.\n"
        "2. While temporary coordinator: inventory `.plans/**`, propose/fill "
        "**Depends on**, draft or refine plans under `drafts/`, refuse to start "
        "work with unmet deps, and say clearly: "
        "`TEMPORARY-COORDINATOR: <your model name> — Preferred orchestrator unset`.\n"
        "3. Still recommend the operator set a durable Preferred orchestrator "
        "(`anchor --set-orchestrator …`) so the next session is not ambiguous.\n"
        "4. If you are **mid / small / local / executor-tier**, do **not** self-appoint; "
        "escalate (below) or ask the human to pick a stronger session.\n\n"
        "### If you are a lesser / executor / local / small model\n\n"
        "When the user asks you to act as the project **orchestrator** (long-horizon "
        "planning across services, multi-hour autonomy, fleet coordination, dependency "
        "analysis across plans, promotion of drafts, or any task in your weak column "
        "in `.anchor/model-fitness.md`):\n\n"
        "1. Do **not** silently attempt it.\n"
        "2. Recommend the **Preferred orchestrator** above when set; otherwise recommend "
        "a frontier/near-frontier session as temporary coordinator (or the top of the "
        "model-priority list).\n"
        "3. Your ENTIRE first line must be "
        "`SUGGEST-ESCALATE: <preferred orchestrator or frontier tier> — <one-line reason>`, "
        "then stop.\n"
        "4. You may still execute well-scoped task specs and ready `/work` plans whose "
        "**Preferred models** match your tier **and** whose **Depends on** are met.\n\n"
        "Change the durable orchestrator any time: edit the bold line, or run "
        "`anchor <project-dir> --set-orchestrator <token>`.\n"
    )

    parts.append("""
## Model routing (fit check)

Before starting any task, check your own row in `.anchor/model-fitness.md`. If the
task lands in your weak column, your ENTIRE first line must be
`SUGGEST-ESCALATE: <better-suited model> — <one-line reason>`, then stop — prefer
the **Preferred orchestrator** above when the work is orchestration-class. The
operator may insist you proceed — then stay strictly in scope and mark shaky
output `(unverified)`.
""")
    if model_priority:
        parts.append("The operator's model priority for this project, highest first "
                     "(saved by `config.sh` at scaffold time):\n\n")
        parts.extend(f"{i}. `{tok}`\n" for i, tok in enumerate(model_priority, 1))
        parts.append("\nSuggest the nearest better-fitting model from this list; skip tiers only "
                     "when the fitness table says every intermediate one is also a poor fit. "
                     "For orchestration-class work, jump to the Preferred orchestrator.\n")
    else:
        parts.append("No saved model priority — set one with `./config.sh --model-priority ...` "
                     "and re-scaffold, or edit this section by hand.\n")
    content = "".join(parts)
    return conventions_path(project_dir, for_write=True), content


def set_project_orchestrator(project_dir: Path, orchestrator: str) -> None:
    """Write preferred orchestrator into ``.anchor/conventions.md`` (+ manifest if present).

    Trivial path for an existing project — does not re-scaffold doctrine files.
    Always refreshes ``var/`` + root ``.gitignore`` ignore rule. Migrates legacy
    root ``ANCHOR-CONVENTIONS.md`` to ``.anchor/conventions.md`` when writing.
    """
    orch = orchestrator.strip().lower()
    if not orch:
        raise SystemExit("--set-orchestrator requires a non-empty token "
                         "(e.g. claude:opus, grok, nim).")

    var_info = ensure_project_var(project_dir)
    print(f"var/: ensured ({var_info['gitignore']} .gitignore rule for var/)")

    legacy = project_dir / CONVENTIONS_LEGACY_REL
    conv_path = conventions_path(project_dir, for_write=True)
    read_path = conventions_path(project_dir, for_write=False)
    if read_path.is_file():
        text = read_path.read_text(encoding="utf-8")
        new_text = set_orchestrator_in_conventions(text, orch)
        if "If you are a lesser" not in new_text:
            block = (
                "\nThis is who should **plan multi-step work, coordinate fleets, make "
                "architecture calls, and review large merges** for this project.\n\n"
                "### If you are a lesser / executor / local / small model\n\n"
                "When the user asks you to act as the project **orchestrator**, do **not** "
                "silently attempt it. Recommend the Preferred orchestrator. First line: "
                f"`SUGGEST-ESCALATE: {orch} — <one-line reason>`.\n"
            )
            new_text = new_text.replace(
                f"**Preferred orchestrator:** `{orch}`",
                f"**Preferred orchestrator:** `{orch}`\n{block}",
                1,
            )
        conv_path.parent.mkdir(parents=True, exist_ok=True)
        conv_path.write_text(new_text, encoding="utf-8")
        if legacy.is_file() and legacy.resolve() != conv_path.resolve():
            legacy.unlink()
            print(f"  migrated {CONVENTIONS_LEGACY_REL} → {CONVENTIONS_REL}")
    else:
        result = plan_conventions(project_dir, None, None, orch)
        assert result is not None
        conv_path.parent.mkdir(parents=True, exist_ok=True)
        conv_path.write_text(result[1], encoding="utf-8")

    manifest_path = find_manifest_path(project_dir) or (project_dir / MANIFEST_NAME)
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        manifest["preferred_orchestrator"] = orch
        files = manifest.get("files") or {}
        # Drop legacy key; record preferred path
        files.pop(CONVENTIONS_LEGACY_REL, None)
        files[CONVENTIONS_REL] = {
            "src": None,
            "hash": _sha256(conv_path),
        }
        manifest["files"] = files
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Preferred orchestrator for '{project_dir}' → `{orch}`")
    print(f"  wrote {conv_path.relative_to(project_dir)}"
          + (f" and updated {manifest_path.name}" if manifest_path.is_file() else ""))
    print(f"Lesser models reading {CONVENTIONS_REL} will recommend this orchestrator "
          "for planning/fleet/architecture work.")


def print_platform_list() -> None:
    print("Available platforms (use with --platform, comma-separated):\n")
    for key, info in PLATFORMS.items():
        print(f"  {key:10s} {info['label']}")
        if key == "local":
            for mkey in LOCAL_MODEL_FILES:
                print(f"    local:{mkey}")
    print("\nAdd --fleet to also copy orchestrator/fleet tooling "
          "(.anchor/scripts/, .anchor/mcp/).")


def survey() -> tuple[list[str], bool]:
    """Interactive prompt. Returns (platform keys, want_fleet)."""
    print("Which platform(s) should this project be optimized for?\n")
    order = list(PLATFORMS)
    for i, key in enumerate(order, 1):
        print(f"  {i}. {PLATFORMS[key]['label']}")
    raw = input("\nEnter numbers, comma-separated (e.g. 1,3): ").strip()
    if not raw:
        raise SystemExit("No selection made. Aborting.")
    chosen: list[str] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok.isdigit() or not (1 <= int(tok) <= len(order)):
            raise SystemExit(f"Invalid selection '{tok}'.")
        chosen.append(order[int(tok) - 1])

    keys: list[str] = []
    for key in chosen:
        if key == "local":
            print(f"\nWhich local model(s)? {', '.join(LOCAL_MODEL_FILES)}")
            sub_raw = input("Enter names, comma-separated: ").strip()
            subs = [s.strip().lower() for s in sub_raw.split(",") if s.strip()]
            if not subs:
                raise SystemExit("No local model selected. Aborting.")
            for s in subs:
                if s not in LOCAL_MODEL_FILES:
                    raise SystemExit(f"Unknown local model '{s}'.")
                keys.append(f"local:{s}")
        else:
            keys.append(key)

    fleet_raw = input(
        "\nAlso include fleet/orchestration tooling (.anchor/scripts/, .anchor/mcp/)? [y/N]: "
    ).strip().lower()
    want_fleet = fleet_raw in {"y", "yes"}
    return keys, want_fleet


def plan_copy(project_dir: Path, platform_keys: list[str], want_fleet: bool) -> list[tuple[Path, Path]]:
    """Build the full (src, dest) copy plan: core doctrine + .plans tree + platforms + fleet."""
    rel_pairs: list[tuple[str, str]] = [(f, doctrine_dest(f)) for f in CORE_FILES]
    rel_pairs.extend(PLANS_TREE_FILES)
    rel_pairs.extend(resolve_selection(platform_keys))
    if want_fleet:
        rel_pairs.extend((f, fleet_dest(f)) for f in FLEET_FILES)

    # de-dupe while preserving order (e.g. core files can't collide with platform files here,
    # but --platform could list the same platform twice)
    seen: set[str] = set()
    plan: list[tuple[Path, Path]] = []
    for src_rel, dest_rel in rel_pairs:
        if dest_rel in seen:
            continue
        seen.add(dest_rel)
        plan.append((REPO_ROOT / src_rel, project_dir / dest_rel))
    return plan


def check_conflicts(plan: list[tuple[Path, Path]]) -> list[Path]:
    return [dest for _, dest in plan if dest.exists()]


def apply_copy(plan: list[tuple[Path, Path]]) -> None:
    for src, dest in plan:
        if not src.exists():
            raise SystemExit(f"Source file missing from repo, aborting: {src}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


# Local project state (worktrees, caches, agent scratch). Never committed.
VAR_DIR_NAME = "var"
VAR_GITIGNORE_ENTRY = "var/"
VAR_GITIGNORE_COMMENT = "# Anchor local state (worktrees, caches) — never commit"


def _gitignore_covers_var(text: str) -> bool:
    """True if root .gitignore already ignores the var/ tree."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Common forms that cover var/
        if line in {
            "var/",
            "/var/",
            "var",
            "/var",
            "var/**",
            "/var/**",
            "**/var/",
        }:
            return True
    return False


def ensure_var_gitignored(project_dir: Path) -> str:
    """Ensure project root ``.gitignore`` ignores ``var/``. Returns action label.

    Labels: ``created`` | ``updated`` | ``unchanged``
    """
    gi = project_dir / ".gitignore"
    if gi.is_file():
        text = gi.read_text(encoding="utf-8")
        if _gitignore_covers_var(text):
            return "unchanged"
        if text and not text.endswith("\n"):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        text += f"{VAR_GITIGNORE_COMMENT}\n{VAR_GITIGNORE_ENTRY}\n"
        gi.write_text(text, encoding="utf-8")
        return "updated"
    gi.write_text(f"{VAR_GITIGNORE_COMMENT}\n{VAR_GITIGNORE_ENTRY}\n", encoding="utf-8")
    return "created"


def ensure_project_var(project_dir: Path) -> dict[str, str]:
    """Create ``var/`` (and ``var/worktrees/``) and ensure root ``.gitignore`` ignores them.

    Safe to call on every scaffold / project config; never overwrites non-gitignore
    content except appending a missing ``var/`` rule to ``.gitignore``.
    """
    project_dir = project_dir.resolve()
    var = project_dir / VAR_DIR_NAME
    var.mkdir(parents=True, exist_ok=True)
    worktrees = var / "worktrees"
    worktrees.mkdir(parents=True, exist_ok=True)
    # Placeholder so empty dirs survive tooling that skips empty folders
    keep = var / ".gitkeep"
    if not keep.exists():
        keep.write_text(
            "# Local Anchor state lives under var/ (gitignored). "
            "Worktrees: var/worktrees/<agent-id>/\n",
            encoding="utf-8",
        )
    gi_action = ensure_var_gitignored(project_dir)
    return {
        "var": str(var),
        "worktrees": str(worktrees),
        "gitignore": gi_action,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repo_commit() -> str:
    """This repo's current commit, or "unknown" if it isn't a git checkout."""
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                                 capture_output=True, text=True, timeout=5, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_manifest(project_dir: Path, plan: list[tuple[Path, Path]],
                    conventions: tuple[Path, str] | None, platform_keys: list[str],
                    want_fleet: bool, framework: str | None,
                    model_priority: list[str] | None = None,
                    preferred_orchestrator: str | None = None) -> dict:
    """Record what was scaffolded so a later --check can tell drift from local edits."""
    files: dict[str, dict] = {}
    for src, dest in plan:
        files[str(dest.relative_to(project_dir))] = {
            "src": str(src.relative_to(REPO_ROOT)),
            "hash": _sha256(src),
        }
    if conventions is not None:
        dest, content = conventions
        # No repo source file backs a generated file; --check regenerates it instead.
        files[str(dest.relative_to(project_dir))] = {"src": None, "hash": _sha256_text(content)}
    return {
        "anchor_commit": _repo_commit(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platforms": platform_keys,
        "fleet": want_fleet,
        "framework": framework,
        "model_priority": model_priority or [],
        "preferred_orchestrator": preferred_orchestrator or "",
        "files": files,
    }


# ---------------------------------------------------------------------------
# Drift check / diff / upgrade (refresh an already-scaffolded project)
# ---------------------------------------------------------------------------

MANIFEST_CANDIDATES = (MANIFEST_NAME, ".anchor/manifest.json")

# Legacy scaffold dests that should move under .anchor/ (source package paths
# still begin with anchor/; doctrine_dest maps them for *new* scaffolds).
_LEGACY_DOCTRINE_PREFIX = "anchor/"


@dataclass
class FileStatus:
    dest_rel: str
    state: str  # unchanged | locally_modified | upstream_updated | missing | source_missing | new
    src_rel: str | None
    manifest_hash: str | None
    project_text: str | None
    upstream_text: str | None
    upstream_label: str


@dataclass
class LayoutMove:
    """Rename a managed path to match current scaffold layout."""
    old_rel: str
    new_rel: str
    reason: str


def find_manifest_path(project_dir: Path) -> Path | None:
    for rel in MANIFEST_CANDIDATES:
        p = project_dir / rel
        if p.is_file():
            return p
    return None


def _read_text_or_none(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _manifest_meta(manifest: dict) -> tuple[list[str], list[str], str | None]:
    priority = list(manifest.get("model_priority") or [])
    orch = (manifest.get("preferred_orchestrator") or "").strip() or None
    if not orch and priority:
        orch = resolve_orchestrator(None, priority, None)
    framework = manifest.get("framework")
    return priority, orch, framework


def _print_scaffold_banner(project_dir: Path, manifest: dict) -> None:
    priority, orch, framework = _manifest_meta(manifest)
    print(f"Scaffolded from anchor commit {manifest.get('anchor_commit', 'unknown')} "
          f"at {manifest.get('generated_at', '?')} "
          f"(platforms={','.join(manifest.get('platforms', []))}, "
          f"fleet={manifest.get('fleet')}, framework={framework}"
          + (f", model_priority={'>'.join(priority)}" if priority else "")
          + (f", orchestrator={orch}" if orch else "") + ")")
    print(f"Anchor source: {REPO_ROOT} @ {_repo_commit()}\n")


def _notes_var_layout(project_dir: Path) -> None:
    var = project_dir / VAR_DIR_NAME
    gi = project_dir / ".gitignore"
    if not var.is_dir():
        print(f"note: {VAR_DIR_NAME}/ missing — re-run scaffold/upgrade or "
              f"`anchor {project_dir} --set-orchestrator …` / ensure_project_var")
    elif gi.is_file() and not _gitignore_covers_var(gi.read_text(encoding="utf-8")):
        print(f"note: root .gitignore does not ignore {VAR_GITIGNORE_ENTRY} — "
              f"upgrade/ensure will append the rule")


def detect_layout_moves(project_dir: Path, manifest: dict) -> list[LayoutMove]:
    """Legacy layout → current ``.anchor/…`` destinations."""
    moves: list[LayoutMove] = []
    seen_new: set[str] = set()
    files = manifest.get("files") or {}

    def _add(old_rel: str, new_rel: str, reason: str) -> None:
        if old_rel == new_rel or new_rel in seen_new:
            return
        old_path = project_dir / old_rel
        new_path = project_dir / new_rel
        if new_path.exists() and not old_path.exists():
            return
        if old_path.exists() or old_rel in files:
            moves.append(LayoutMove(old_rel=old_rel, new_rel=new_rel, reason=reason))
            seen_new.add(new_rel)

    for dest_rel in files:
        # Doctrine: anchor/… → .anchor/… (not scaffold plans)
        if dest_rel.startswith(_LEGACY_DOCTRINE_PREFIX) and not dest_rel.startswith("anchor/scaffold/"):
            try:
                _add(dest_rel, doctrine_dest(dest_rel), "doctrine dest is now under .anchor/")
            except ValueError:
                pass
        # Fleet: project-root scripts/|mcp/ → .anchor/scripts|mcp/
        if dest_rel.startswith("scripts/") or dest_rel.startswith("mcp/"):
            try:
                _add(dest_rel, fleet_dest(dest_rel), "fleet tooling dest is now under .anchor/")
            except ValueError:
                pass
        # Conventions: root ANCHOR-CONVENTIONS.md → .anchor/conventions.md
        if dest_rel == CONVENTIONS_LEGACY_REL or dest_rel.endswith("/" + CONVENTIONS_LEGACY_REL):
            _add(dest_rel, CONVENTIONS_REL, "conventions dest is now .anchor/conventions.md")

    # Filesystem-only: legacy trees present but not listed (partial installs)
    legacy_root = project_dir / "anchor"
    if legacy_root.is_dir():
        for path in sorted(legacy_root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(project_dir)).replace("\\", "/")
            if rel.startswith("anchor/scaffold/"):
                continue
            try:
                _add(rel, doctrine_dest(rel), "legacy anchor/ tree on disk")
            except ValueError:
                continue
    for prefix in ("scripts", "mcp"):
        legacy = project_dir / prefix
        if not legacy.is_dir():
            continue
        # Only migrate if this looks like Anchor fleet (has known files), not user's app scripts
        sample = {p.name for p in legacy.rglob("*") if p.is_file()}
        anchor_markers = {
            "anchor_client.py", "work_once.py", "fleet_watch.py", "orchestrate.py",
            "server.py", "endpoints.yaml",
        }
        if not (sample & anchor_markers) and prefix == "scripts":
            # require at least one known fleet script name
            continue
        if prefix == "mcp" and "server.py" not in sample and not any(
            (legacy / n).is_dir() for n in (
                "anchor-prompts", "model-fleet", "project-orchestrator",
            )
        ):
            continue
        for path in sorted(legacy.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(project_dir)).replace("\\", "/")
            try:
                _add(rel, fleet_dest(rel), f"legacy {prefix}/ fleet tree on disk")
            except ValueError:
                continue
    legacy_conv = project_dir / CONVENTIONS_LEGACY_REL
    if legacy_conv.is_file() and not (project_dir / CONVENTIONS_REL).is_file():
        _add(CONVENTIONS_LEGACY_REL, CONVENTIONS_REL, "conventions dest is now .anchor/conventions.md")
    return moves


def classify_project(project_dir: Path, manifest: dict) -> list[FileStatus]:
    """Classify each manifest-tracked file against current Anchor source."""
    priority, orch, framework = _manifest_meta(manifest)
    regenerated = (plan_conventions(project_dir, framework, priority, orch)
                   if framework or priority or orch else None)
    statuses: list[FileStatus] = []
    for dest_rel, info in sorted((manifest.get("files") or {}).items()):
        dest = project_dir / dest_rel
        manifest_hash = info.get("hash")
        src_rel = info.get("src")
        project_text = _read_text_or_none(dest)

        if src_rel is None:
            upstream_text = regenerated[1] if regenerated is not None else None
            upstream_label = f"(generated {CONVENTIONS_REL})"
            upstream_hash = _sha256_text(upstream_text) if upstream_text is not None else None
        else:
            src = REPO_ROOT / src_rel
            if src.is_file():
                upstream_text = _read_text_or_none(src)
                upstream_label = src_rel
                upstream_hash = _sha256(src)
            else:
                upstream_text = None
                upstream_label = src_rel
                upstream_hash = None

        if src_rel is not None and upstream_hash is None:
            state = "source_missing"
        elif not dest.exists():
            state = "missing"
        else:
            disk_hash = _sha256(dest)
            if manifest_hash and disk_hash != manifest_hash:
                state = "locally_modified"
            elif upstream_hash is not None and manifest_hash and upstream_hash != manifest_hash:
                state = "upstream_updated"
            elif upstream_hash is not None and not manifest_hash and disk_hash != upstream_hash:
                state = "upstream_updated"
            else:
                state = "unchanged"

        statuses.append(FileStatus(
            dest_rel=dest_rel,
            state=state,
            src_rel=src_rel,
            manifest_hash=manifest_hash,
            project_text=project_text if dest.exists() else None,
            upstream_text=upstream_text,
            upstream_label=upstream_label,
        ))
    return statuses


def classify_new_scaffold_files(project_dir: Path, manifest: dict) -> list[FileStatus]:
    """Files current plan_copy would add that are not in the manifest yet."""
    platforms = list(manifest.get("platforms") or [])
    if not platforms:
        return []
    want_fleet = bool(manifest.get("fleet"))
    plan = plan_copy(project_dir, platforms, want_fleet)
    priority, orch, framework = _manifest_meta(manifest)
    conventions = plan_conventions(project_dir, framework, priority, orch)
    known = set(manifest.get("files") or {})
    # After layout moves, also treat new_rel as known if old_rel was known
    for m in detect_layout_moves(project_dir, manifest):
        known.add(m.new_rel)
    out: list[FileStatus] = []
    for src, dest in plan:
        rel = str(dest.relative_to(project_dir)).replace("\\", "/")
        if rel in known:
            continue
        if dest.exists():
            continue  # user-owned / pre-existing — do not claim
        text = _read_text_or_none(src)
        out.append(FileStatus(
            dest_rel=rel,
            state="new",
            src_rel=str(src.relative_to(REPO_ROOT)),
            manifest_hash=None,
            project_text=None,
            upstream_text=text,
            upstream_label=str(src.relative_to(REPO_ROOT)),
        ))
    if conventions is not None:
        rel = str(conventions[0].relative_to(project_dir)).replace("\\", "/")
        if rel not in known and not conventions[0].exists():
            out.append(FileStatus(
                dest_rel=rel,
                state="new",
                src_rel=None,
                manifest_hash=None,
                project_text=None,
                upstream_text=conventions[1],
                upstream_label=f"(generated {CONVENTIONS_REL})",
            ))
    return out


def render_unified_diff(status: FileStatus) -> str:
    old = (status.project_text or "").splitlines(keepends=True)
    new = (status.upstream_text or "").splitlines(keepends=True)
    if not old and not new:
        return ""
    diff = difflib.unified_diff(
        old,
        new,
        fromfile=f"a/{status.dest_rel}",
        tofile=f"b/{status.upstream_label}",
    )
    return "".join(diff)


def _state_label(state: str) -> str:
    return {
        "unchanged": "unchanged",
        "locally_modified": "locally modified",
        "upstream_updated": "upstream updated",
        "missing": "MISSING",
        "source_missing": "source missing in this Anchor checkout",
        "new": "new (not in manifest; current scaffold would add)",
    }.get(state, state)


def check_project(project_dir: Path) -> None:
    """Report each manifest-tracked file state. Never writes."""
    mpath = find_manifest_path(project_dir)
    if mpath is None:
        raise SystemExit(
            f"No {MANIFEST_NAME} in '{project_dir}' — nothing to check "
            "(only projects scaffolded by this anchor.py have one). "
            "Run `anchor <dir>` to scaffold, or `anchor <dir> --upgrade` after."
        )
    _notes_var_layout(project_dir)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    _print_scaffold_banner(project_dir, manifest)
    moves = detect_layout_moves(project_dir, manifest)
    if moves:
        print("Layout migrations available (apply with --upgrade):")
        for m in moves:
            print(f"  {m.old_rel}  →  {m.new_rel}  ({m.reason})")
        print()
    for st in classify_project(project_dir, manifest):
        print(f"  {st.dest_rel}: {_state_label(st.state)}")
    news = classify_new_scaffold_files(project_dir, manifest)
    if news:
        print("\nNew scaffold files (not yet in this project):")
        for st in news:
            print(f"  {st.dest_rel}: {_state_label(st.state)}")


def diff_project(project_dir: Path) -> None:
    """Print classification + unified diffs. Never writes."""
    mpath = find_manifest_path(project_dir)
    if mpath is None:
        raise SystemExit(f"No {MANIFEST_NAME} in '{project_dir}' — nothing to diff.")
    _notes_var_layout(project_dir)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    _print_scaffold_banner(project_dir, manifest)
    moves = detect_layout_moves(project_dir, manifest)
    if moves:
        print("## Layout migrations\n")
        for m in moves:
            print(f"  {m.old_rel}  →  {m.new_rel}  ({m.reason})")
        print()
    print("## Managed files\n")
    for st in classify_project(project_dir, manifest):
        print(f"=== {st.dest_rel}  [{_state_label(st.state)}]")
        if st.state in {"upstream_updated", "locally_modified", "missing"} and st.upstream_text is not None:
            body = render_unified_diff(st)
            print(body if body else "(no textual diff)\n")
        elif st.state == "source_missing":
            print(f"  (source {st.src_rel!r} missing under {REPO_ROOT})\n")
        else:
            print()
    news = classify_new_scaffold_files(project_dir, manifest)
    if news:
        print("## New scaffold files\n")
        for st in news:
            print(f"=== {st.dest_rel}  [{_state_label(st.state)}]")
            if st.upstream_text:
                preview = st.upstream_text.splitlines()
                for line in preview[:20]:
                    print(f"+ {line}")
                if len(preview) > 20:
                    print(f"... ({len(preview) - 20} more lines)")
            print()


def _confirm_upgrade(*, yes: bool, dry_run: bool) -> bool:
    if dry_run:
        return False
    if yes:
        print("Proceeding without prompt (--yes).")
        return True
    if not sys.stdin.isatty():
        raise SystemExit(
            "Refusing to upgrade without confirmation in a non-interactive terminal. "
            "Re-run with --yes (safe: skips locally modified) or --diff to preview."
        )
    raw = input("Apply upgrade plan? [y/N]: ").strip().lower()
    return raw in {"y", "yes"}


def upgrade_project(
    project_dir: Path,
    *,
    yes: bool = False,
    force: bool = False,
    dry_run: bool = False,
    add_new: bool = True,
) -> None:
    """Bring a scaffolded project toward current Anchor scaffold patterns.

    - Layout: ``anchor/`` doctrine dests → ``.anchor/``
    - Content: take upstream for clean ``upstream_updated`` / restore ``missing``
    - Locally modified: keep unless ``force``
    - Optionally add newly introduced scaffold files for recorded platforms
    - Refresh manifest hashes / anchor_commit
    """
    mpath = find_manifest_path(project_dir)
    if mpath is None:
        raise SystemExit(
            f"No {MANIFEST_NAME} in '{project_dir}' — nothing to upgrade "
            "(scaffold with `anchor <dir>` first)."
        )
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    _print_scaffold_banner(project_dir, manifest)
    _notes_var_layout(project_dir)

    moves = detect_layout_moves(project_dir, manifest)
    statuses = classify_project(project_dir, manifest)
    news = classify_new_scaffold_files(project_dir, manifest) if add_new else []

    actionable_content = [
        s for s in statuses
        if s.state in {"upstream_updated", "missing"}
        or (s.state == "locally_modified" and force)
    ]
    # source_missing: never auto-delete project files
    skip_local = [s for s in statuses if s.state == "locally_modified" and not force]

    print("## Upgrade plan\n")
    if moves:
        print("Layout:")
        for m in moves:
            print(f"  MOVE  {m.old_rel}  →  {m.new_rel}")
    if actionable_content:
        print("Content:")
        for s in actionable_content:
            action = {
                "upstream_updated": "TAKE upstream",
                "missing": "RESTORE from upstream",
                "locally_modified": "TAKE upstream (--force)",
            }.get(s.state, s.state)
            print(f"  {action:24}  {s.dest_rel}")
    if news:
        print("Add new scaffold files:")
        for s in news:
            print(f"  ADD   {s.dest_rel}")
    if skip_local:
        print("Keep (locally modified; pass --force to overwrite):")
        for s in skip_local:
            print(f"  KEEP  {s.dest_rel}")
    unchanged = sum(1 for s in statuses if s.state == "unchanged")
    print(f"\nUnchanged managed files: {unchanged}")

    if not moves and not actionable_content and not news:
        print("\nNothing to do — project matches current scaffold for managed files.")
        # Still ensure var/
        if not dry_run:
            ensure_project_var(project_dir)
        return

    if dry_run:
        print("\n(dry run — nothing written)")
        return

    if not _confirm_upgrade(yes=yes, dry_run=False):
        raise SystemExit("Aborted — nothing written.")

    files_map: dict[str, dict] = dict(manifest.get("files") or {})
    applied: list[str] = []

    # 1) Layout moves
    for m in moves:
        old_p = project_dir / m.old_rel
        new_p = project_dir / m.new_rel
        if new_p.exists() and old_p.exists():
            print(f"  skip MOVE {m.old_rel}: both old and new exist — resolve manually")
            continue
        if old_p.exists():
            new_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_p), str(new_p))
            print(f"  moved {m.old_rel} → {m.new_rel}")
            applied.append(f"move:{m.new_rel}")
        if m.old_rel in files_map:
            files_map[m.new_rel] = files_map.pop(m.old_rel)
            # keep src as-is (still anchor/… in the source tree)

    # Re-classify after moves
    manifest["files"] = files_map
    statuses = classify_project(project_dir, manifest)
    news = classify_new_scaffold_files(project_dir, manifest) if add_new else []

    def write_upstream(st: FileStatus) -> None:
        if st.upstream_text is None:
            print(f"  skip {st.dest_rel}: no upstream text")
            return
        dest = project_dir / st.dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(st.upstream_text, encoding="utf-8")
        files_map[st.dest_rel] = {
            "src": st.src_rel,
            "hash": _sha256_text(st.upstream_text),
        }
        applied.append(st.dest_rel)
        print(f"  wrote {st.dest_rel}")

    for st in statuses:
        if st.state == "upstream_updated":
            write_upstream(st)
        elif st.state == "missing":
            write_upstream(st)
        elif st.state == "locally_modified" and force:
            write_upstream(st)

    for st in news:
        write_upstream(st)

    ensure_project_var(project_dir)

    manifest["files"] = files_map
    manifest["anchor_commit"] = _repo_commit()
    manifest["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Prefer writing to existing manifest path
    out_path = mpath
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nUpdated manifest: {out_path.relative_to(project_dir)}")
    print(f"Applied {len(applied)} change(s). Done.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", nargs="?",
                    help="target project folder (default: current working directory)")
    ap.add_argument("--platform", help="comma-separated platform keys, e.g. claude,local:qwen3 "
                                        "(skips the interactive survey)")
    ap.add_argument("--fleet", action="store_true", help="also copy orchestrator/fleet tooling")
    ap.add_argument("--framework", help="language/framework to optimize code conventions for (e.g. node, "
                                         "python, rust); skips detection and the prompt")
    ap.add_argument("--orchestrator",
                    help="preferred orchestrator token for this project (e.g. claude:opus, grok); "
                         f"written into {CONVENTIONS_REL} — lesser models recommend this for "
                         "planning/fleet work")
    ap.add_argument("--set-orchestrator", metavar="TOKEN",
                    help=f"update only the project's preferred orchestrator ({CONVENTIONS_REL} "
                         "+ manifest); does not re-scaffold. Example: claude:opus")
    ap.add_argument("--list", action="store_true", help="print available platform keys and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview only (scaffold findings or upgrade plan); never write")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="skip confirmation prompts and write (required when stdin is not a tty)")
    ap.add_argument("--force", action="store_true",
                    help="with --upgrade/--update: overwrite locally modified managed files")
    ap.add_argument("--check", action="store_true",
                    help="report drift vs current Anchor source (no writes)")
    ap.add_argument("--diff", action="store_true",
                    help="like --check plus unified diffs (no writes)")
    ap.add_argument("--upgrade", action="store_true",
                    help="upgrade an already-scaffolded project to current scaffold patterns "
                         "(layout + content + new managed files); confirm or pass --yes")
    ap.add_argument("--update", action="store_true",
                    help="alias for --upgrade")
    args = ap.parse_args()

    if args.list:
        print_platform_list()
        return

    project_dir = resolve_project_dir(args.project_dir)

    if args.set_orchestrator is not None:
        set_project_orchestrator(project_dir, args.set_orchestrator)
        return

    mode_count = sum(bool(x) for x in (args.check, args.diff, args.upgrade, args.update))
    if mode_count > 1:
        raise SystemExit("Use only one of --check, --diff, --upgrade/--update.")

    if args.check:
        check_project(project_dir)
        return
    if args.diff:
        diff_project(project_dir)
        return
    if args.upgrade or args.update:
        upgrade_project(
            project_dir,
            yes=args.yes,
            force=args.force,
            dry_run=args.dry_run,
            add_new=True,
        )
        return

    if not project_dir.exists():
        if sys.stdin.isatty():
            create = input(f"'{project_dir}' does not exist. Create it? [y/N]: ").strip().lower()
            if create not in {"y", "yes"}:
                raise SystemExit("Aborted.")
        print(f"Creating '{project_dir}'.")
        project_dir.mkdir(parents=True)
    elif not project_dir.is_dir():
        raise SystemExit(f"'{project_dir}' is not a directory.")

    if args.platform:
        platform_keys = [k for k in args.platform.split(",") if k.strip()]
        want_fleet = args.fleet
    else:
        defaults = load_defaults()
        if defaults is not None:
            platform_keys, want_fleet = defaults
            want_fleet = want_fleet or args.fleet
            print(f"No --platform given; using saved defaults from {DEFAULTS_FILE} "
                  f"(platform={','.join(platform_keys)}, fleet={want_fleet}). "
                  f"Run ./config.sh to change these, or pass --platform to override.\n")
        elif not sys.stdin.isatty():
            raise SystemExit("No --platform given, no saved defaults (run ./config.sh to set some), "
                              "and no interactive terminal available. Pass --platform explicitly (see --list).")
        else:
            platform_keys, want_fleet = survey()

    framework = resolve_framework(project_dir, args.framework, load_saved_language())
    model_priority = load_model_priority()
    preferred_orch = resolve_orchestrator(
        args.orchestrator, model_priority, load_orchestrator()
    )
    conventions = plan_conventions(project_dir, framework, model_priority, preferred_orch)

    plan = plan_copy(project_dir, platform_keys, want_fleet)
    manifest_path = project_dir / MANIFEST_NAME
    conflicts = check_conflicts(plan)
    if conventions is not None and conventions[0].exists():
        conflicts.append(conventions[0])
    if manifest_path.exists():
        conflicts.append(manifest_path)

    if conflicts:
        print(f"\nRefusing to overwrite {len(conflicts)} existing file(s) in "
              f"'{project_dir}':\n", file=sys.stderr)
        for c in conflicts:
            print(f"  {c}", file=sys.stderr)
        print("\nResolve these (move, rename, or remove) and re-run. Nothing was written.",
              file=sys.stderr)
        raise SystemExit(1)

    print(format_scaffold_findings(
        project_dir,
        platform_keys,
        want_fleet,
        framework,
        model_priority,
        preferred_orch,
        plan,
        conventions,
    ), end="")

    if args.dry_run:
        print("(dry run — nothing written)")
        return

    if not confirm_scaffold_write(yes=args.yes):
        raise SystemExit("Aborted — nothing written.")

    print(f"\nWriting into '{project_dir}':")
    apply_copy(plan)
    for _, dest in plan:
        print(f"  {dest.relative_to(project_dir)}")
    if conventions is not None:
        dest, content = conventions
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        print(f"  {dest.relative_to(project_dir)} (generated)")
    var_info = ensure_project_var(project_dir)
    print(f"  {VAR_DIR_NAME}/ (local state; gitignored via root .gitignore "
          f"[{var_info['gitignore']}])")
    manifest = build_manifest(project_dir, plan, conventions, platform_keys, want_fleet,
                              framework, model_priority, preferred_orch)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"  {MANIFEST_NAME} (generated)")
    print("\nDone.")


if __name__ == "__main__":
    main()
