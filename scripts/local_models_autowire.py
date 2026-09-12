#!/usr/bin/env python3
"""Detect a *confirmed* local-model stack in a scaffolded consumer project
and, on operator confirm, write the machine-local wiring so `aider` (and
other swarm-tier work) can use it immediately — without waiting for the
full ``/local-models-config`` -> ``/local-models-ensure`` convergence
pipeline to land.

This is the middle path between "/local-models only reports + offers a
draft" and a full declare/converge system: **detection never mutates
anything**; only :func:`write_project_stack`, called after an explicit
operator confirm, writes files.

Confirm gates (plan ``local-models-confirmed-stack-autowire`` Step 1):

1. a guest-reachable OpenAI-compatible API answered
   (``fit_device.probe_device()['register_ok']``)
2. that API's ``/models`` actually **lists** the Default-for-wire model id
   (not just "responds") — reachability alone is not "confirmed"
3. optional: ``aider`` on ``$PATH`` (gates the launcher/`.aider.conf.yml`
   part of the write set, not the endpoints/`.env` part)

    python scripts/local_models_autowire.py --detect            # report only
    python scripts/local_models_autowire.py --project . --write  # write set

Reuses ``fit_device.py``'s existing probe/reachability/Default-for-wire
logic and ``write_aider_env.py``'s existing `.env`/`.gitignore` contract —
this module does not reimplement either.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import fit_device
import write_aider_env

# Anchor catalog model.name -> Ollama pull tag. Only entries this repo
# actually documents serving via Ollama (see docs/docs/skills/local-models.md)
# are mapped; an unmapped model cannot pass confirm gate 2 (plan Risk: "Aider
# model ids drift from registry model names -> map explicitly").
OLLAMA_TAG_MAP: dict[str, str] = {
    "qwen3-4b": "qwen3:4b",
    "qwen3-8b": "qwen3:8b",
    "qwen3-14b": "qwen3:14b",
    "qwen3-30b-a3b": "qwen3:30b-a3b",
    "qwen3-32b": "qwen3:32b",
    "gemma3-12b": "gemma3:12b",
    "gemma3-27b": "gemma3:27b",
}

DEFAULT_QUANT = "q4"
DEFAULT_CONTEXT = 8192


def ollama_tag_for(model: fit_device.Model | None) -> str | None:
    return OLLAMA_TAG_MAP.get(model.name) if model else None


def list_served_model_ids(base_url: str, *, timeout: float = 2.0) -> list[str] | None:
    """GET ``<base_url>/models`` and return served model ids, or ``None`` on
    any failure (unreachable, non-JSON, unexpected shape) — never raises."""
    url = base_url.rstrip("/") + "/models"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "anchor-autowire/1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None
    return [e.get("id") for e in entries if isinstance(e, dict) and e.get("id")]


@dataclass(frozen=True)
class ConfirmedStack:
    reachable: bool
    base_url: str | None
    model: fit_device.Model | None
    ollama_tag: str | None
    model_served: bool
    aider_present: bool
    probe: dict

    @property
    def confirmed(self) -> bool:
        """Both hard gates hold: reachable API + that API actually serves the
        Default-for-wire model. `aider_present` is optional/advisory."""
        return self.reachable and self.ollama_tag is not None and self.model_served

    def reasons(self) -> list[str]:
        out = []
        if not self.reachable:
            out.append("no guest-reachable OpenAI-compatible API")
        if self.ollama_tag is None and self.model is not None:
            out.append(f"no known Ollama tag for catalog model {self.model.name!r}")
        elif self.reachable and self.ollama_tag is not None and not self.model_served:
            out.append(f"reachable API does not list model {self.ollama_tag!r}")
        return out


def detect_confirmed_stack(
    *, quant: str = DEFAULT_QUANT, context: int = DEFAULT_CONTEXT
) -> ConfirmedStack:
    probe = fit_device.probe_device()
    reachable = bool(probe.get("register_ok"))
    base_url = probe.get("register_base_url")

    model: fit_device.Model | None = None
    tag: str | None = None
    usable = probe.get("usable_memory_gb")
    if usable:
        fits = fit_device.fitting_models(usable, quant, context)
        if fits:
            model, _pressure = fit_device.default_wire_model(
                fits, quant=quant, context=context,
                free_gb=probe.get("free_memory_gb"),
                available_gb=probe.get("available_memory_gb"),
                profile=probe.get("profile"),
                total_ram_gb=probe.get("total_ram_gb"),
            )
            tag = ollama_tag_for(model)

    served_ids = list_served_model_ids(base_url) if (reachable and base_url) else None
    model_served = bool(
        tag and served_ids and any(sid == tag or sid.startswith(tag + ":") for sid in served_ids)
    )

    return ConfirmedStack(
        reachable=reachable,
        base_url=base_url,
        model=model,
        ollama_tag=tag,
        model_served=model_served,
        aider_present=shutil.which("aider") is not None,
        probe=probe,
    )


# --- write set (C1: only on explicit confirm; C2: machine-local only) ------

ENDPOINTS_OVERLAY_REL = "var/endpoints.local.yaml"
ENDPOINTS_HEADER = (
    "# Anchor-managed: machine-local fleet endpoints (never commit; see var/.gitignore)\n"
)
CONVENTIONS_MARKER = "<!-- anchor:local-models-autowire -->"


def _ensure_project_var_gitignored(project_dir: Path) -> str:
    import anchor as anchor_cli  # local import: heavy module, only needed for writes

    return anchor_cli.ensure_var_gitignored(project_dir)


def write_endpoints_overlay(
    project_dir: Path, stack: ConfirmedStack, *, quant: str = DEFAULT_QUANT,
    context: int = DEFAULT_CONTEXT, dry_run: bool = False,
) -> tuple[Path, bool, str]:
    """Append an endpoint stanza for the confirmed model, unless one with the
    same name already exists (idempotent, C5)."""
    path = project_dir / ENDPOINTS_OVERLAY_REL
    assert stack.model is not None
    stanza = fit_device.endpoint_stanza(
        stack.model, stack.probe.get("backend", "metal"), context,
        name=f"{stack.model.name}-local", base_url=stack.base_url,
    )
    name_line = f"  - name: {stack.model.name}-local"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if name_line in existing:
        return path, False, "unchanged"
    if dry_run:
        return path, True, "would-write"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not existing:
        new_text = ENDPOINTS_HEADER + "endpoints:\n" + stanza + "\n"
    else:
        new_text = existing.rstrip("\n") + "\n" + stanza + "\n"
    path.write_text(new_text, encoding="utf-8")
    return path, True, ("created" if not existing else "updated")


def write_conventions_note(project_dir: Path, stack: ConfirmedStack, *, dry_run: bool = False) -> str:
    """Append an idempotent "local when reachable" paragraph to the project's
    conventions file — only if that file already exists (never invent one;
    this is a small addendum, not a scaffold)."""
    import anchor as anchor_cli

    path = anchor_cli.conventions_path(project_dir)
    if not path.is_file():
        return "skipped (no conventions file)"
    text = path.read_text(encoding="utf-8")
    if CONVENTIONS_MARKER in text:
        return "unchanged"
    if dry_run:
        return "would-update"
    assert stack.model is not None
    note = (
        f"\n{CONVENTIONS_MARKER}\n"
        f"## Local models (autowired)\n\n"
        f"A confirmed local stack ({stack.ollama_tag}, swarm tier) is wired for "
        f"this project via `.env` (`OLLAMA_API_BASE`) and `{ENDPOINTS_OVERLAY_REL}`. "
        f"Use it for lightweight/swarm work only — it is never a frontier or "
        f"orchestrator substitute. Re-run `/local-models` after a reboot or "
        f"network change to refresh the reachable URL.\n"
    )
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + note, encoding="utf-8")
    return "updated"


def write_aider_conf(project_dir: Path, stack: ConfirmedStack, *, dry_run: bool = False) -> tuple[Path, str]:
    """Write/refresh `.aider.conf.yml` `model:` to the Default-for-wire tag —
    never the Max-fit model (C3b)."""
    path = project_dir / ".aider.conf.yml"
    assert stack.ollama_tag is not None
    model_line = f"model: ollama_chat/{stack.ollama_tag}"
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        changed = False
        for i, line in enumerate(lines):
            if line.strip().startswith("model:"):
                if line.strip() == model_line:
                    return path, "unchanged"
                lines[i] = model_line
                changed = True
                break
        if not changed:
            lines.append(model_line)
        text = "\n".join(lines) + "\n"
        action = "updated"
    else:
        text = model_line + "\n"
        action = "created"
    if dry_run:
        return path, f"would-{action}"
    path.write_text(text, encoding="utf-8")
    return path, action


LAUNCHER_TEMPLATE_REL = "hardware/personal-devices/configs/aider-ollama-launcher.sh"
LAUNCHER_DEST_REL = "scripts/aider-ollama.sh"


def copy_launcher_template(anchor_root: Path, project_dir: Path, *, dry_run: bool = False) -> str:
    """Copy the portable Aider+Ollama launcher template into the consumer
    project's own `scripts/`, only when Aider is on PATH (optional
    convenience — `.env` alone is the bare-`aider` fix, per the
    `aider-wsl-ollama-api-base-env` plan's own C1)."""
    src = anchor_root / LAUNCHER_TEMPLATE_REL
    if not src.is_file():
        return f"skipped (template missing: {src})"
    dest = project_dir / LAUNCHER_DEST_REL
    existed = dest.is_file()
    if existed and dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8"):
        return "unchanged"
    if dry_run:
        return "would-write"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    dest.chmod(0o755)
    return "updated" if existed else "created"


def write_project_stack(
    anchor_root: Path, project_dir: Path, stack: ConfirmedStack, *, dry_run: bool = False,
) -> dict:
    """The full write set (C1: caller must have already gotten an explicit
    confirm — this function itself performs no confirmation). Returns one
    action label per file/target; never raises on an unconfirmed stack —
    callers should check ``stack.confirmed`` first."""
    if not stack.confirmed:
        return {"error": f"stack not confirmed: {'; '.join(stack.reasons())}"}

    results: dict[str, str] = {}

    _ensure_project_var_gitignored(project_dir)
    _, _, action = write_endpoints_overlay(project_dir, stack, dry_run=dry_run)
    results["endpoints_overlay"] = action

    ollama_base = write_aider_env.strip_v1_suffix(stack.base_url)
    _, _, env_action = write_aider_env.write_env_file(project_dir, ollama_base, dry_run=dry_run)
    results["env"] = env_action
    results["env_gitignore"] = write_aider_env.ensure_env_gitignored(project_dir, dry_run=dry_run)

    results["conventions"] = write_conventions_note(project_dir, stack, dry_run=dry_run)

    if stack.aider_present:
        _, conf_action = write_aider_conf(project_dir, stack, dry_run=dry_run)
        results["aider_conf"] = conf_action
        results["launcher"] = copy_launcher_template(anchor_root, project_dir, dry_run=dry_run)
    else:
        results["aider_conf"] = "skipped (aider not on PATH)"
        results["launcher"] = "skipped (aider not on PATH)"

    return results


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="local_models_autowire.py", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anchor-root", default=".", help="Anchor checkout (template source)")
    ap.add_argument("--project", default=None, help="consumer project to wire (default: --anchor-root)")
    ap.add_argument("--detect", action="store_true", help="detect only (default behavior; explicit alias)")
    ap.add_argument("--write", action="store_true", help="perform the write set (default: detect only)")
    ap.add_argument("--dry-run", action="store_true", help="with --write, report actions without writing")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)

    anchor_root = Path(args.anchor_root).resolve()

    if args.write and not args.project:
        # C4: never treat the Anchor source tree itself as the wire target by
        # accident — --write requires an explicit --project.
        msg = "refusing --write without --project (would target the Anchor checkout itself)"
        print((json.dumps({"ok": False, "error": msg}) if args.json else f"error: {msg}"), file=sys.stderr)
        return 2

    project_dir = Path(args.project).resolve() if args.project else anchor_root

    stack = detect_confirmed_stack()

    if not args.write:
        out = {
            "confirmed": stack.confirmed,
            "reachable": stack.reachable,
            "base_url": stack.base_url,
            "model": stack.model.name if stack.model else None,
            "ollama_tag": stack.ollama_tag,
            "model_served": stack.model_served,
            "aider_present": stack.aider_present,
            "reasons": stack.reasons(),
        }
        if args.json:
            print(json.dumps(out))
        else:
            verdict = "CONFIRMED" if stack.confirmed else "not confirmed"
            print(f"{verdict}: base_url={stack.base_url} model={stack.model.name if stack.model else None} "
                  f"tag={stack.ollama_tag} served={stack.model_served} aider={stack.aider_present}")
            for r in stack.reasons():
                print(f"  - {r}")
        return 0

    if not stack.confirmed:
        msg = f"refusing to write: {'; '.join(stack.reasons())}"
        print((json.dumps({"ok": False, "error": msg}) if args.json else f"error: {msg}"), file=sys.stderr)
        return 1

    results = write_project_stack(anchor_root, project_dir, stack, dry_run=args.dry_run)
    if args.json:
        print(json.dumps({"ok": True, "actions": results}))
    else:
        for key, action in results.items():
            print(f"{key}: {action}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
