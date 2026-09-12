#!/usr/bin/env python3
"""Write/refresh a gitignored project-root ``.env`` so bare ``aider`` finds
Ollama, even on WSL where the Windows-side API doesn't answer on guest
``localhost``.

Aider (via litellm) loads a repo-root ``.env`` before probing model info, and
Ollama models read ``OLLAMA_API_BASE`` from it. Without a *guest-reachable*
value there, a plain ``aider`` invocation on WSL fails with:

    OllamaError: ... Connection refused
    Set Ollama API Base via `OLLAMA_API_BASE` environment variable

This reuses ``fit_device.py``'s existing reachable-URL discovery (loopback →
default-gateway → resolv nameserver) rather than re-probing — that plan
(``wsl-ollama-reachable-base-url``) already solved "which URL answers from the
guest"; this script only writes it where Aider reads it.

    python scripts/write_aider_env.py --root .            # write/refresh .env
    python scripts/write_aider_env.py --root . --dry-run   # preview only

Idempotent: re-running after a reboot / gateway change updates only the
``OLLAMA_API_BASE`` line in an existing ``.env``, leaving every other line
(including secrets unrelated to Ollama) untouched. Never commits the file —
also ensures the project's ``.gitignore`` covers it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fit_device import openai_base_url, resolve_register_base_url

OLLAMA_API_BASE_KEY = "OLLAMA_API_BASE"
OPENAI_API_KEY_KEY = "OPENAI_API_KEY"
# Ollama ignores the value but litellm/Aider expect *some* OPENAI_API_KEY to be
# set before it will proceed; a harmless placeholder, never a real secret.
OLLAMA_DUMMY_OPENAI_KEY = "ollama"

ENV_GITIGNORE_COMMENT = "# Anchor-managed: local Ollama endpoint for bare `aider` (never commit)"
ENV_GITIGNORE_ENTRIES = (".env", ".env.*", "!.env.example")


def strip_v1_suffix(base_url: str) -> str:
    """``http://host:port/v1`` -> ``http://host:port`` (Ollama's own API, not
    the OpenAI-compatible one `fit_device` otherwise emits)."""
    u = base_url.rstrip("/")
    if u.endswith("/v1"):
        u = u[: -len("/v1")]
    return u


def resolve_ollama_api_base(*, wsl: bool | None = None) -> dict:
    """Reuse fit_device's reachable-URL discovery; return Ollama-native base.

    Result keys: ``base_url`` (Ollama-native, no ``/v1``), ``ok``, ``reason``,
    ``discovery`` (raw fit_device probe detail, for diagnostics).
    """
    resolved = resolve_register_base_url(None, wsl=wsl, backend="cuda")
    base = resolved.get("base_url") or openai_base_url("127.0.0.1", 11434)
    return {
        "base_url": strip_v1_suffix(base),
        "ok": bool(resolved.get("ok")),
        "reason": resolved.get("reason", ""),
        "discovery": resolved.get("discovery"),
    }


def _upsert_env_var(text: str, key: str, value: str) -> tuple[str, bool]:
    """Set ``key=value`` in a dotenv-style text, replacing an existing bare
    (uncommented) assignment or appending one. Returns (new_text, changed)."""
    lines = text.splitlines()
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            if line.strip() == f"{prefix}{value}":
                return text, False
            lines[i] = f"{prefix}{value}"
            return "\n".join(lines) + ("\n" if text.endswith("\n") or not text else ""), True
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"{prefix}{value}")
    return "\n".join(lines) + "\n", True


def write_env_file(
    project_dir: Path,
    ollama_api_base: str,
    *,
    ensure_openai_key: bool = True,
    dry_run: bool = False,
) -> tuple[Path, bool, str]:
    """Upsert ``OLLAMA_API_BASE`` (and a dummy ``OPENAI_API_KEY`` if entirely
    absent) into ``<project_dir>/.env``. Returns (path, changed, action)."""
    env_path = project_dir / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    text = existing
    changed = False

    text, c1 = _upsert_env_var(text, OLLAMA_API_BASE_KEY, ollama_api_base)
    changed = changed or c1

    if ensure_openai_key and f"{OPENAI_API_KEY_KEY}=" not in text:
        text, c2 = _upsert_env_var(text, OPENAI_API_KEY_KEY, OLLAMA_DUMMY_OPENAI_KEY)
        changed = changed or c2

    if not changed:
        return env_path, False, "unchanged"
    if dry_run:
        return env_path, True, "would-write"
    env_path.write_text(text, encoding="utf-8")
    return env_path, True, ("created" if not existing else "updated")


def _gitignore_covers_env(text: str) -> bool:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in {".env", "/.env", ".env*", "/.env*", "**/.env"}:
            return True
    return False


def ensure_env_gitignored(project_dir: Path, *, dry_run: bool = False) -> str:
    """Ensure project root ``.gitignore`` covers ``.env``. Returns an action
    label: ``created`` | ``updated`` | ``unchanged`` | ``would-update``."""
    gi = project_dir / ".gitignore"
    if gi.is_file():
        text = gi.read_text(encoding="utf-8")
        if _gitignore_covers_env(text):
            return "unchanged"
        if dry_run:
            return "would-update"
        if text and not text.endswith("\n"):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        text += ENV_GITIGNORE_COMMENT + "\n" + "\n".join(ENV_GITIGNORE_ENTRIES) + "\n"
        gi.write_text(text, encoding="utf-8")
        return "updated"
    if dry_run:
        return "would-create"
    gi.write_text(ENV_GITIGNORE_COMMENT + "\n" + "\n".join(ENV_GITIGNORE_ENTRIES) + "\n", encoding="utf-8")
    return "created"


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="write_aider_env.py", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="project root to write .env / .gitignore into")
    ap.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    ap.add_argument("--no-gitignore", action="store_true", help="skip ensuring .gitignore covers .env")
    ap.add_argument("--no-openai-key", action="store_true",
                     help="skip the dummy OPENAI_API_KEY placeholder even if .env has none")
    args = ap.parse_args(argv)

    project_dir = Path(args.root).resolve()
    if not project_dir.is_dir():
        print(f"error: not a directory: {project_dir}", file=sys.stderr)
        return 2

    resolved = resolve_ollama_api_base()
    if not resolved["ok"]:
        print(f"warning: no guest-reachable Ollama API found ({resolved['reason']}); "
              f"writing best-guess {resolved['base_url']} anyway — refresh after Ollama starts",
              file=sys.stderr)

    env_path, changed, action = write_env_file(
        project_dir, resolved["base_url"],
        ensure_openai_key=not args.no_openai_key, dry_run=args.dry_run,
    )
    print(f"{action}: {env_path} ({OLLAMA_API_BASE_KEY}={resolved['base_url']}, "
          f"reason={resolved['reason']})")

    if not args.no_gitignore:
        gi_action = ensure_env_gitignored(project_dir, dry_run=args.dry_run)
        print(f"gitignore: {gi_action} ({project_dir / '.gitignore'})")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
