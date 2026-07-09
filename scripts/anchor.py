#!/usr/bin/env python3
"""anchor — scaffold a project with Anchor doctrine for one or more model platforms.

Asks which platform(s) a project should be optimized for (Claude Code, Grok Build,
NVIDIA NIM/Nemotron, local models, generic chat UIs), then copies the relevant
doctrine + platform files from this repo into the target project. Refuses to
overwrite: any destination file that already exists is reported as a conflict
and NOTHING is written, so the user can resolve it and re-run.

Usage:
  python scripts/anchor.py <project-dir>                        # interactive survey
  python scripts/anchor.py <project-dir> --platform claude,grok  # non-interactive
  python scripts/anchor.py <project-dir> --platform local:qwen3,local:gemma3 --fleet
  python scripts/anchor.py <project-dir> --framework rust        # skip framework detection/prompt
  python scripts/anchor.py --list                                # show platform keys
  python scripts/anchor.py <project-dir> --platform claude --dry-run
  python scripts/anchor.py <project-dir> --check                 # compare against .anchor-manifest.json
  python scripts/anchor.py <project-dir> --set-orchestrator claude:opus   # project preferred orchestrator

If no --platform is given and ../config.sh has saved defaults (~/.config/anchor/defaults
by default, override with $ANCHOR_CONFIG_DIR), those defaults are used automatically.

Also detects the target project's language/framework from marker files (package.json,
Cargo.toml, go.mod, ...) and writes its idiomatic-composition guidance to
ANCHOR-CONVENTIONS.md. If detection fails (blank/ambiguous project) and stdin is a
tty, it asks — proposing the saved config.sh language default, if any.

**Preferred orchestrator** (who should plan / coordinate long-horizon work for this
project) is set via `./config.sh --orchestrator …`, scaffold `--orchestrator …`,
`anchor <dir> --set-orchestrator …`, or by editing the bold line in
ANCHOR-CONVENTIONS.md. Lesser models are instructed to recommend that orchestrator
instead of attempting orchestration themselves.

Every scaffold also writes .anchor-manifest.json recording which anchor commit,
platforms, and file hashes were used. Doctrine files are a one-time copy with no
update path otherwise — run `anchor.py <project-dir> --check` later to see whether
the source has moved on, or the installed copy was hand-edited. Nothing is ever
overwritten automatically; --check only reports.

Typical shell alias so it can be run as `anchor project/bar`:
  alias anchor="python3 /path/to/Anchor/scripts/anchor.py"
(or symlink bin/anchor, included alongside this script, onto your PATH)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_FILE = Path(os.environ.get("ANCHOR_CONFIG_DIR", Path.home() / ".config" / "anchor")) / "defaults"
MANIFEST_NAME = ".anchor-manifest.json"

# Doctrine every platform needs, regardless of choice. Relative paths, repo-root -> project-root.
CORE_FILES: list[str] = [
    "anchor/ANCHOR.md",
    "anchor/model-fitness.md",
    "anchor/system-prompts/mythos-core.md",
    "anchor/templates/plan.md",
    "anchor/templates/task-spec.md",
    "anchor/templates/review.md",
    "anchor/templates/verification.md",
]

# Fleet/orchestration tooling — optional, only relevant once you're actually running
# more than one model against the project.
FLEET_FILES: list[str] = [
    "scripts/anchor_client.py",
    "scripts/orchestrate.py",
    "scripts/work_once.py",
    "scripts/plan_select.py",
    "scripts/plan_lease.py",
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
# Always scaffolded into consumer projects as a *git-tracked* `.plans/` tree.
# Sources live under anchor/scaffold/plans/ (this Anchor repo gitignores its own
# working `.plans/` entirely — local backlog for developing Anchor). Consumer
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
    ("anchor/scaffold/plans/drafts/.gitkeep", ".plans/drafts/.gitkeep"),
    ("anchor/scaffold/plans/completed/.gitkeep", ".plans/completed/.gitkeep"),
]

PLATFORMS: dict[str, dict] = {
    "claude": {
        "label": "Claude Code",
        "files": [
            ("platforms/claude-code/CLAUDE.md", "CLAUDE.md"),
            (".claude/commands/config.md", ".claude/commands/config.md"),
            (".claude/commands/work.md", ".claude/commands/work.md"),
            (".claude/commands/draft.md", ".claude/commands/draft.md"),
            (".claude/commands/fleet-watch.md", ".claude/commands/fleet-watch.md"),
        ],
    },
    "grok": {
        "label": "Grok Build",
        "files": [
            ("platforms/grok-build/GROK.md", "GROK.md"),
            (".grok/skills/work/SKILL.md", ".grok/skills/work/SKILL.md"),
            (".grok/skills/draft/SKILL.md", ".grok/skills/draft/SKILL.md"),
            (".grok/skills/fleet-watch/SKILL.md", ".grok/skills/fleet-watch/SKILL.md"),
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

# Marker file (relative to project root) -> language/framework key. First match wins.
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
# inheritance (see anchor/ANCHOR.md, "Code quality defaults").
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


def detect_framework(project_dir: Path) -> str | None:
    """Guess the project's language/framework from marker files. None if blank or ambiguous."""
    if not project_dir.exists() or not any(project_dir.iterdir()):
        return None
    for marker, key in FRAMEWORK_MARKERS.items():
        if (project_dir / marker).exists():
            return key
    if next(project_dir.glob("*.csproj"), None) is not None:
        return "dotnet"
    return None


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
          "— skipping ANCHOR-CONVENTIONS.md (run ./config.sh to set a default, or pass --framework).")
    return None


def plan_conventions(
    project_dir: Path,
    framework: str | None,
    model_priority: list[str] | None = None,
    orchestrator: str | None = None,
) -> tuple[Path, str] | None:
    """Build the (dest, content) pair for a generated ANCHOR-CONVENTIONS.md.

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

- Follow SOLID principles by default (see `anchor/ANCHOR.md`, "Code quality defaults").
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
        "session lead — see `anchor/model-fitness.md`), you **may take a temporary "
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
        "in `anchor/model-fitness.md`):\n\n"
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

Before starting any task, check your own row in `anchor/model-fitness.md`. If the
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
    return project_dir / "ANCHOR-CONVENTIONS.md", content


def set_project_orchestrator(project_dir: Path, orchestrator: str) -> None:
    """Write preferred orchestrator into ANCHOR-CONVENTIONS.md (+ manifest if present).

    Trivial path for an existing project — does not re-scaffold doctrine files.
    """
    orch = orchestrator.strip().lower()
    if not orch:
        raise SystemExit("--set-orchestrator requires a non-empty token "
                         "(e.g. claude:opus, grok, nim).")

    conv_path = project_dir / "ANCHOR-CONVENTIONS.md"
    if conv_path.is_file():
        text = conv_path.read_text(encoding="utf-8")
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
        conv_path.write_text(new_text, encoding="utf-8")
    else:
        result = plan_conventions(project_dir, None, None, orch)
        assert result is not None
        conv_path.write_text(result[1], encoding="utf-8")

    manifest_path = project_dir / MANIFEST_NAME
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        manifest["preferred_orchestrator"] = orch
        files = manifest.get("files") or {}
        if "ANCHOR-CONVENTIONS.md" in files:
            files["ANCHOR-CONVENTIONS.md"] = {
                "src": None,
                "hash": _sha256(conv_path),
            }
            manifest["files"] = files
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Preferred orchestrator for '{project_dir}' → `{orch}`")
    print(f"  wrote {conv_path.name}"
          + (f" and updated {MANIFEST_NAME}" if manifest_path.is_file() else ""))
    print("Lesser models reading ANCHOR-CONVENTIONS.md will recommend this orchestrator "
          "for planning/fleet/architecture work.")


def print_platform_list() -> None:
    print("Available platforms (use with --platform, comma-separated):\n")
    for key, info in PLATFORMS.items():
        print(f"  {key:10s} {info['label']}")
        if key == "local":
            for mkey in LOCAL_MODEL_FILES:
                print(f"    local:{mkey}")
    print("\nAdd --fleet to also copy orchestrator/fleet tooling (scripts/, mcp/).")


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

    fleet_raw = input("\nAlso include fleet/orchestration tooling (scripts/, mcp/)? [y/N]: ").strip().lower()
    want_fleet = fleet_raw in {"y", "yes"}
    return keys, want_fleet


def plan_copy(project_dir: Path, platform_keys: list[str], want_fleet: bool) -> list[tuple[Path, Path]]:
    """Build the full (src, dest) copy plan: core doctrine + .plans tree + platforms + fleet."""
    rel_pairs: list[tuple[str, str]] = [(f, f) for f in CORE_FILES]
    rel_pairs.extend(PLANS_TREE_FILES)
    rel_pairs.extend(resolve_selection(platform_keys))
    if want_fleet:
        rel_pairs.extend((f, f) for f in FLEET_FILES)

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


def check_project(project_dir: Path) -> None:
    """Report each manifest-tracked file as unchanged, locally modified, upstream
    updated, or missing. Never writes anything — a diff-and-decide tool, not an updater."""
    manifest_path = project_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise SystemExit(f"No {MANIFEST_NAME} in '{project_dir}' — nothing to check "
                          "(only projects scaffolded by this anchor.py have one).")

    manifest = json.loads(manifest_path.read_text())
    priority = manifest.get("model_priority") or []
    orch = (manifest.get("preferred_orchestrator") or "").strip() or None
    if not orch and priority:
        orch = resolve_orchestrator(None, priority, None)
    print(f"Scaffolded from anchor commit {manifest.get('anchor_commit', 'unknown')} "
          f"at {manifest.get('generated_at', '?')} "
          f"(platforms={','.join(manifest.get('platforms', []))}, "
          f"fleet={manifest.get('fleet')}, framework={manifest.get('framework')}"
          + (f", model_priority={'>'.join(priority)}" if priority else "")
          + (f", orchestrator={orch}" if orch else "") + ")\n")

    framework = manifest.get("framework")
    regenerated = (plan_conventions(project_dir, framework, priority, orch)
                   if framework or priority or orch else None)

    for dest_rel, info in sorted(manifest.get("files", {}).items()):
        dest = project_dir / dest_rel
        manifest_hash = info.get("hash")
        src_rel = info.get("src")

        if src_rel is None:
            current_hash = _sha256_text(regenerated[1]) if regenerated is not None else None
            current_label = "(regenerated from current framework guidance)"
        else:
            src = REPO_ROOT / src_rel
            current_hash = _sha256(src) if src.exists() else None
            current_label = src_rel

        if not dest.exists():
            state = "MISSING — was removed from the project"
        elif _sha256(dest) != manifest_hash:
            state = "locally modified — left as-is"
        elif current_hash is not None and current_hash != manifest_hash:
            state = f"upstream updated — diff against {current_label} and review"
        else:
            state = "unchanged"
        print(f"  {dest_rel}: {state}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", nargs="?", help="target project folder (e.g. project/bar)")
    ap.add_argument("--platform", help="comma-separated platform keys, e.g. claude,local:qwen3 "
                                        "(skips the interactive survey)")
    ap.add_argument("--fleet", action="store_true", help="also copy orchestrator/fleet tooling")
    ap.add_argument("--framework", help="language/framework to optimize code conventions for (e.g. node, "
                                         "python, rust); skips detection and the prompt")
    ap.add_argument("--orchestrator",
                    help="preferred orchestrator token for this project (e.g. claude:opus, grok); "
                         "written into ANCHOR-CONVENTIONS.md — lesser models recommend this for "
                         "planning/fleet work")
    ap.add_argument("--set-orchestrator", metavar="TOKEN",
                    help="update only the project's preferred orchestrator (ANCHOR-CONVENTIONS.md "
                         "+ manifest); does not re-scaffold. Example: claude:opus")
    ap.add_argument("--list", action="store_true", help="print available platform keys and exit")
    ap.add_argument("--dry-run", action="store_true", help="show the copy plan / conflicts, write nothing")
    ap.add_argument("--check", action="store_true",
                     help="compare a previously scaffolded project's .anchor-manifest.json against "
                          "current source and the on-disk files; writes nothing")
    args = ap.parse_args()

    if args.list:
        print_platform_list()
        return

    if not args.project_dir:
        raise SystemExit("Missing project directory. Usage: anchor <project-dir> [--platform ...]")

    if args.set_orchestrator is not None:
        set_project_orchestrator(Path(args.project_dir).resolve(), args.set_orchestrator)
        return

    if args.check:
        check_project(Path(args.project_dir).resolve())
        return

    project_dir = Path(args.project_dir).resolve()
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

    total = len(plan) + (1 if conventions is not None else 0) + 1
    print(f"\nCopying {total} file(s) into '{project_dir}':")
    for _, dest in plan:
        print(f"  {dest.relative_to(project_dir)}")
    if conventions is not None:
        print(f"  {conventions[0].relative_to(project_dir)} (generated)")
    print(f"  {MANIFEST_NAME} (generated — compare later with --check)")
    if model_priority:
        print(f"\nModel priority (from config, highest first): {' > '.join(model_priority)}")
    if preferred_orch:
        print(f"Preferred orchestrator: {preferred_orch}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return

    apply_copy(plan)
    if conventions is not None:
        dest, content = conventions
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    manifest = build_manifest(project_dir, plan, conventions, platform_keys, want_fleet,
                              framework, model_priority, preferred_orch)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("\nDone.")


if __name__ == "__main__":
    main()
