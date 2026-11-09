#!/usr/bin/env python3
"""Measure the Anchor Harness against frozen ceilings in anchor/harness-budget.toml.

Exit 0 when every ceiling holds. Exit 1 and name the budget that broke.
Does not call a model. Stdlib + tomllib only (Python 3.11+) / tomli not required:
the file is parsed with a tiny subset reader so this script stays import-light.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from pathlib import Path

BANNED_ON_IMPORT = frozenset({
    "requests", "yaml", "openai", "torch", "numpy", "httpx", "aiohttp",
})
FIRST_PARTY = frozenset({
    "anchor", "anchor_cli", "anchor_ops", "anchor_client",
    "plan_store", "plan_select", "plan_parse", "plan_lease",
    "plan_finish_gate", "plan_board", "plan_watch", "work_once",
    "worktree_for_agent", "lease_branch", "merge_feature",
    "pending_merges", "release_progress", "scope_gate",
    "fleet_watch", "inference_load", "nvidia_build_probe",
    "fit_device", "write_aider_env",
})


def repo_root() -> Path:
    here = Path(__file__).resolve().parent
    if (here.parent / "anchor" / "harness-budget.toml").is_file():
        return here.parent
    return Path.cwd()


def _parse_toml_subset(text: str) -> dict[str, dict[str, object]]:
    """Enough TOML for this budget file: [section] then key = int|float|str."""
    sections: dict[str, dict[str, object]] = {}
    cur: dict[str, object] | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            cur = sections.setdefault(name, {})
            continue
        if cur is None or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        val = rest.strip()
        if val.startswith('"') and val.endswith('"'):
            cur[key.strip()] = val[1:-1]
        elif "." in val:
            cur[key.strip()] = float(val)
        else:
            cur[key.strip()] = int(val)
    return sections


def load_budget(root: Path) -> dict[str, dict[str, object]]:
    path = root / "anchor" / "harness-budget.toml"
    return _parse_toml_subset(path.read_text(encoding="utf-8"))


def declared_install_deps(root: Path) -> int:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    # Count string items in a [project] dependencies = [ ... ] list if present.
    in_project = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[project]"):
            in_project = True
            continue
        if s.startswith("[") and in_project:
            break
        if in_project and s.startswith("dependencies"):
            # parse the rest of the file until closing
            blob = s.split("=", 1)[1]
            # may be multi-line; collect until we leave
            return max(0, blob.count('"') // 2)
    return 0


def sys_modules_added_and_banned(root: Path) -> tuple[int, int, list[str]]:
    env = {**os.environ, "PYTHONPATH": str(root / "scripts")}
    banned = ",".join(sorted(BANNED_ON_IMPORT))
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        f"sys.path.insert(0, {str(root / 'scripts')!r})\n"
        "import anchor  # noqa: F401\n"
        "after = set(sys.modules) - before\n"
        f"banned = set({banned!r}.split(','))\n"
        "hits = sorted({m.split('.')[0] for m in after if m.split('.')[0] in banned})\n"
        "print(len(after))\n"
        "print(len(hits))\n"
        "print(','.join(hits))\n"
    )
    p = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(root), env=env, capture_output=True, text=True, check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr or p.stdout or "import anchor failed")
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip() != ""]
    added = int(lines[0])
    n_banned = int(lines[1])
    names = [x for x in lines[2].split(",") if x] if len(lines) > 2 else []
    return added, n_banned, names


def generated_tokens_default_path(root: Path) -> int:
    """0 if default CLI paths do not reference Endpoint.chat in argv dispatch.

    Static: ``anchor_ops`` default list/finish ops must not call ``.chat(``.
    Delegation is opt-in (``_try_delegate`` / ``_critic``).
    """
    ops = (root / "scripts" / "anchor_ops.py").read_text(encoding="utf-8")
    tree = ast.parse(ops)
    # If a default list op's body called chat, that would be a finding.
    # We only count a token budget of 0 as "no Endpoint.chat on list helpers".
    chat_in_list = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("op_") and (
            node.name.endswith("_list") or node.name in (
                "op_work_finish", "op_work_return", "op_plans_list",
            )
        ):
            src = ast.get_source_segment(ops, node) or ""
            if ".chat(" in src:
                chat_in_list = True
    return 1 if chat_in_list else 0


def wall(argv: list[str], cwd: Path, timeout: float = 30.0) -> float:
    t0 = time.perf_counter()
    subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, check=False,
        env={**os.environ, "PYTHONPATH": str(cwd / "scripts")},
    )
    return time.perf_counter() - t0


def measure(root: Path) -> dict[str, float]:
    py = sys.executable
    anchor = str(root / "scripts" / "anchor.py")
    added, banned, _ = sys_modules_added_and_banned(root)
    return {
        "declared_install_deps": float(declared_install_deps(root)),
        "banned_modules_on_import_anchor": float(banned),
        "generated_tokens_default_path": float(generated_tokens_default_path(root)),
        "sys_modules_added_on_import_anchor": float(added),
        "help_wall_s": wall([py, anchor, "--help"], root),
        "work_list_wall_s": wall([py, anchor, "work", "--list"], root),
    }


def evaluate(root: Path) -> tuple[int, list[str], dict[str, float]]:
    budget = load_budget(root)
    ceilings = budget.get("ceilings") or {}
    got = measure(root)
    failed: list[str] = []
    for name, got_v in got.items():
        if name not in ceilings:
            continue
        ceil = float(ceilings[name])  # type: ignore[arg-type]
        if got_v > ceil:
            failed.append(f"{name}: {got_v} > ceiling {ceil}")
    return (1 if failed else 0), failed, got


def main(argv: list[str] | None = None) -> int:
    root = repo_root()
    code, failed, got = evaluate(root)
    for k, v in got.items():
        print(f"{k}={v}")
    if failed:
        print("FAILED budgets:")
        for line in failed:
            print(f"  {line}")
        return 1
    print("OK — harness budgets hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
