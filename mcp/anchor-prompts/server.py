#!/usr/bin/env python3
"""anchor-prompts MCP server — gives any MCP-capable agent (Claude Code, Grok Build, local
agents) the Anchor scaffolding as callable tools, so lesser models don't have to remember
the discipline: they can fetch it.

Run: uv run server.py   (or: pip install "mcp[cli]" pyyaml requests && python server.py)
Claude Code: claude mcp add anchor-prompts -- python /path/to/mcp/anchor-prompts/server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

mcp = FastMCP("anchor-prompts")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@mcp.tool()
def get_doctrine() -> str:
    """The Anchor doctrine: how to approach any task like a Mythos-class model.
    Call this at the start of a session and follow it."""
    return _read("anchor/ANCHOR.md")


@mcp.tool()
def get_system_prompt(model: str = "core") -> str:
    """Get the Mythos-core system prompt, or a model-specific adaptation.
    model: core | qwen3 | gemma3 | mistral-small | deepseek-r1-distill | llama33"""
    if model == "core":
        return _read("anchor/system-prompts/mythos-core.md")
    path = REPO / "platforms" / "local-models" / f"{model}.md"
    if not path.exists():
        return f"Unknown model '{model}'. Options: core, " + ", ".join(
            p.stem for p in (REPO / "platforms/local-models").glob("*.md") if p.stem != "README")
    return path.read_text(encoding="utf-8")


@mcp.tool()
def get_template(name: str) -> str:
    """Fetch a work template to fill in. name: plan | task-spec | review | verification"""
    path = REPO / "anchor" / "templates" / f"{name}.md"
    if not path.exists():
        return "Unknown template. Options: plan, task-spec, review, verification"
    return path.read_text(encoding="utf-8")


@mcp.tool()
def tune_prompt(rough_task: str) -> str:
    """Rewrite a rough task description into a precise Anchor task spec using a cheap
    fleet model. Use before dispatching work to any expensive or weak model."""
    from anchor_client import Fleet  # lazy: fleet may not be configured
    from prompt_tuner import tune
    try:
        return tune(rough_task, Fleet())
    except Exception as e:
        return (f"Fleet unavailable ({e}). Fill this template yourself instead:\n\n"
                + _read("anchor/templates/task-spec.md"))


@mcp.tool()
def preflight_check(task_spec: str) -> str:
    """Deterministically check a task spec for the sections the doctrine requires.
    Returns PASS or the list of gaps. Run before executing any spec."""
    required = ["## Goal", "## Files in scope", "## Acceptance criteria", "## Definition of done"]
    gaps = [s for s in required if s.lower() not in task_spec.lower()]
    todos = task_spec.count("TODO(")
    if not gaps and todos == 0:
        return "PASS — spec is executable."
    lines = []
    if gaps:
        lines.append("MISSING SECTIONS: " + ", ".join(gaps))
    if todos:
        lines.append(f"UNRESOLVED TODOs: {todos} — resolve with the task owner before executing.")
    lines.append("Do not execute this spec. Return it for completion (Anchor rule 1).")
    return "\n".join(lines)


@mcp.prompt()
def plan_task(goal: str) -> str:
    """Prompt scaffold: produce an Anchor plan for a goal."""
    return (f"{_read('anchor/system-prompts/mythos-core.md')}\n\n"
            f"Your ONLY output is a plan following this template — do not implement.\n\n"
            f"{_read('anchor/templates/plan.md')}\n\nGOAL: {goal}")


@mcp.prompt()
def critique_work(spec: str, work: str) -> str:
    """Prompt scaffold: review completed work against its spec, fresh-context critic style."""
    return (f"{_read('anchor/system-prompts/mythos-core.md')}\n\n"
            f"You are the critic. Review only; do not fix.\n\n"
            f"{_read('anchor/templates/review.md')}\n\nSPEC:\n{spec}\n\nWORK:\n{work}")


if __name__ == "__main__":
    mcp.run()
