#!/usr/bin/env python3
"""Per-agent git worktrees so parallel workers do not share one HEAD.

Leases under ``.plans/.leases/`` coordinate *which plan* an agent owns.
Worktrees coordinate *where that agent edits code* — one checkout (and thus one
branch tip) per ``agent_id``.

Layout (default)::

  <project>/var/worktrees/<safe-agent-id>/   # git worktree path (var/ gitignored)
  <project>/var/worktrees/registry.json      # local map agent_id → path/branch

Integration branch::

  prefer existing ``dev``, else ``develop``;
  if neither exists, create ``dev`` from ``main`` (else ``master``).

Usage::

  python scripts/worktree_for_agent.py ensure --project . --agent-id mid-1
  python scripts/worktree_for_agent.py ensure --project . --agent-id mid-1 \\
      --slug fix-login
  python scripts/worktree_for_agent.py list --project .
  python scripts/worktree_for_agent.py path --project . --agent-id mid-1
  python scripts/worktree_for_agent.py remove --project . --agent-id mid-1

Exit codes: 0 ok, 1 nothing / missing, 2 usage or hard error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

INTEGRATION_CANDIDATES = ("dev", "develop")
TRUNK_CANDIDATES = ("main", "master")
DEFAULT_REL_ROOT = Path("var") / "worktrees"
REGISTRY_NAME = "registry.json"


class WorktreeError(Exception):
    """User-facing failure (missing git, no trunk, etc.)."""


@dataclass
class WorktreeRecord:
    agent_id: str
    path: str
    branch: str
    integration: str
    project: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> WorktreeRecord:
        return cls(
            agent_id=str(data["agent_id"]),
            path=str(data["path"]),
            branch=str(data["branch"]),
            integration=str(data.get("integration") or ""),
            project=str(data.get("project") or ""),
        )


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=capture,
        check=check,
    )


def safe_agent_id(agent_id: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", (agent_id or "").strip())
    s = s.strip(".-") or "agent"
    return s[:80]


def resolve_project(project: str | Path | None = None) -> Path:
    if project:
        root = Path(project).expanduser().resolve()
        if not root.is_dir():
            raise WorktreeError(f"project is not a directory: {root}")
        return root
    try:
        r = _run(["git", "rev-parse", "--show-toplevel"])
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorktreeError(
            "not inside a git repo; pass --project /path/to/repo"
        ) from exc
    return Path(r.stdout.strip()).resolve()


def assert_git_repo(project: Path) -> None:
    try:
        _run(["git", "rev-parse", "--git-dir"], cwd=project)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorktreeError(f"not a git repository: {project}") from exc


def _local_branches(project: Path) -> set[str]:
    r = _run(["git", "branch", "--format=%(refname:short)"], cwd=project)
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def _remote_branches(project: Path, remote: str = "origin") -> set[str]:
    try:
        r = _run(
            ["git", "branch", "-r", "--format=%(refname:short)"],
            cwd=project,
            check=False,
        )
    except OSError:
        return set()
    out: set[str] = set()
    prefix = f"{remote}/"
    for ln in r.stdout.splitlines():
        name = ln.strip()
        if name.startswith(prefix) and "->" not in name:
            out.add(name[len(prefix) :])
    return out


def _ref_exists(project: Path, ref: str) -> bool:
    r = _run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=project,
        check=False,
    )
    return r.returncode == 0


def ensure_integration_branch(
    project: Path,
    *,
    push: bool = False,
) -> tuple[str, bool]:
    """Return (branch_name, created). Prefer dev/develop; else create dev from trunk."""
    assert_git_repo(project)
    local = _local_branches(project)
    remote = _remote_branches(project)

    for name in INTEGRATION_CANDIDATES:
        if name in local or _ref_exists(project, name):
            return name, False
        if name in remote:
            _run(
                ["git", "branch", "--track", name, f"origin/{name}"],
                cwd=project,
                check=False,
            )
            if name in _local_branches(project) or _ref_exists(project, name):
                return name, False
            # fallback: create local from origin without --track issues
            _run(["git", "branch", name, f"origin/{name}"], cwd=project)
            return name, False

    trunk: str | None = None
    for name in TRUNK_CANDIDATES:
        if name in local or _ref_exists(project, name):
            trunk = name
            break
        if name in remote:
            trunk = f"origin/{name}"
            break
    if not trunk:
        raise WorktreeError(
            "no integration branch (dev/develop) and no trunk (main/master); "
            "cannot create dev — stop and ask a human"
        )

    # Create local dev from trunk
    if _ref_exists(project, "dev"):
        return "dev", False
    _run(["git", "branch", "dev", trunk], cwd=project)
    created = True
    if push:
        r = _run(
            ["git", "push", "-u", "origin", "dev"],
            cwd=project,
            check=False,
        )
        if r.returncode != 0:
            # Non-fatal: local dev still usable
            pass
    return "dev", created


def worktrees_root(project: Path) -> Path:
    return (project / DEFAULT_REL_ROOT).resolve()


def _ensure_var_gitignored(project: Path) -> None:
    """Append ``var/`` to root .gitignore if missing (scaffold/config also do this)."""
    gi = project / ".gitignore"
    if gi.is_file():
        text = gi.read_text(encoding="utf-8")
        for raw in text.splitlines():
            line = raw.strip()
            if line in {"var/", "/var/", "var", "/var", "var/**", "/var/**", "**/var/"}:
                return
        if text and not text.endswith("\n"):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        text += "# Anchor local state (worktrees, caches) — never commit\nvar/\n"
        gi.write_text(text, encoding="utf-8")
    else:
        gi.write_text(
            "# Anchor local state (worktrees, caches) — never commit\nvar/\n",
            encoding="utf-8",
        )


def registry_path(project: Path) -> Path:
    return worktrees_root(project) / REGISTRY_NAME


def load_registry(project: Path) -> dict[str, WorktreeRecord]:
    path = registry_path(project)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, dict):
        return {}
    out: dict[str, WorktreeRecord] = {}
    for k, v in agents.items():
        if isinstance(v, dict):
            try:
                out[str(k)] = WorktreeRecord.from_dict(v)
            except (KeyError, TypeError, ValueError):
                continue
    return out


def save_registry(project: Path, records: dict[str, WorktreeRecord]) -> None:
    root = worktrees_root(project)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": str(project),
        "agents": {k: v.to_dict() for k, v in sorted(records.items())},
    }
    registry_path(project).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def worktree_path_for(project: Path, agent_id: str) -> Path:
    return worktrees_root(project) / safe_agent_id(agent_id)


def list_git_worktrees(project: Path) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain``."""
    r = _run(["git", "worktree", "list", "--porcelain"], cwd=project)
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line[len("worktree ") :].strip()}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD ") :].strip()
        elif line.startswith("branch "):
            ref = line[len("branch ") :].strip()
            cur["branch"] = ref.removeprefix("refs/heads/")
        elif line == "detached":
            cur["branch"] = "(detached)"
        elif line.startswith("bare"):
            cur["bare"] = "1"
    if cur:
        entries.append(cur)
    return entries


def _worktree_registered(project: Path, path: Path) -> bool:
    path = path.resolve()
    for e in list_git_worktrees(project):
        try:
            if Path(e.get("path", "")).resolve() == path:
                return True
        except OSError:
            continue
    return False


def feature_branch_name(slug: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._/-]+", "-", slug.strip())
    s = s.strip("/-") or "work"
    if s.startswith("feature/") or s.startswith("feat/"):
        return s
    return f"feature/{s}"


def agent_base_branch(agent_id: str) -> str:
    """Long-lived branch for this agent's worktree (not the feature branch)."""
    return f"agent/{safe_agent_id(agent_id)}"


def ensure_worktree(
    project: Path,
    agent_id: str,
    *,
    slug: str | None = None,
    push_integration: bool = False,
) -> WorktreeRecord:
    """Create or reuse a worktree for agent_id; optional feature branch for slug."""
    project = project.resolve()
    assert_git_repo(project)
    if not agent_id or not str(agent_id).strip():
        raise WorktreeError("--agent-id is required")

    integration, created_int = ensure_integration_branch(
        project, push=push_integration
    )
    # Ensure var/ exists and is ignored even if project was never re-scaffolded
    worktrees_root(project).mkdir(parents=True, exist_ok=True)
    _ensure_var_gitignored(project)
    path = worktree_path_for(project, agent_id)
    base_branch = agent_base_branch(agent_id)
    records = load_registry(project)

    # Create agent base branch from integration if missing
    if not _ref_exists(project, base_branch):
        _run(["git", "branch", base_branch, integration], cwd=project)

    if path.is_dir() and _worktree_registered(project, path):
        # Already linked
        pass
    elif path.exists() and not _worktree_registered(project, path):
        raise WorktreeError(
            f"path exists but is not a registered git worktree: {path} "
            f"(remove it or choose another agent-id)"
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        # If branch already checked out elsewhere, git worktree add fails —
        # use -B only when creating fresh worktree on new branch tip.
        r = _run(
            ["git", "worktree", "add", str(path), base_branch],
            cwd=project,
            check=False,
        )
        if r.returncode != 0:
            # Branch might be checked out in main tree — force new branch tip
            err = (r.stderr or r.stdout or "").strip()
            if "already used by worktree" in err or "already checked out" in err:
                # Create unique branch from integration
                alt = f"{base_branch}-wt"
                if not _ref_exists(project, alt):
                    _run(["git", "branch", alt, integration], cwd=project)
                base_branch = alt
                r2 = _run(
                    ["git", "worktree", "add", str(path), base_branch],
                    cwd=project,
                    check=False,
                )
                if r2.returncode != 0:
                    raise WorktreeError(
                        f"git worktree add failed: {(r2.stderr or r2.stdout or err).strip()}"
                    )
            else:
                raise WorktreeError(
                    f"git worktree add failed: {err or 'unknown error'}"
                )

    branch = base_branch
    if slug:
        feat = feature_branch_name(slug)
        # Create/switch feature branch inside the worktree
        if not _ref_exists(project, feat):
            _run(["git", "branch", feat, integration], cwd=project)
        r = _run(
            ["git", "checkout", feat],
            cwd=path,
            check=False,
        )
        if r.returncode != 0:
            # try create in worktree
            r2 = _run(
                ["git", "checkout", "-B", feat, integration],
                cwd=path,
                check=False,
            )
            if r2.returncode != 0:
                raise WorktreeError(
                    f"could not checkout feature branch {feat!r} in worktree: "
                    f"{(r2.stderr or r2.stdout or r.stderr or '').strip()}"
                )
        branch = feat

    rec = WorktreeRecord(
        agent_id=agent_id,
        path=str(path.resolve()),
        branch=branch,
        integration=integration,
        project=str(project),
    )
    records[agent_id] = rec
    save_registry(project, records)
    # Stash note for callers
    rec_extra = rec
    if created_int:
        # annotate via return only; CLI prints
        pass
    return rec_extra


def remove_worktree(
    project: Path,
    agent_id: str,
    *,
    force: bool = False,
    delete_branch: bool = False,
) -> bool:
    """Remove worktree for agent_id. Returns True if something was removed."""
    project = project.resolve()
    assert_git_repo(project)
    records = load_registry(project)
    path = worktree_path_for(project, agent_id)
    rec = records.get(agent_id)
    if rec:
        path = Path(rec.path)

    removed = False
    if _worktree_registered(project, path) or path.is_dir():
        args = ["git", "worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        r = _run(args, cwd=project, check=False)
        if r.returncode != 0:
            # prune stale
            _run(["git", "worktree", "prune"], cwd=project, check=False)
            if path.is_dir():
                r2 = _run(
                    ["git", "worktree", "remove", "--force", str(path)],
                    cwd=project,
                    check=False,
                )
                if r2.returncode != 0 and path.is_dir():
                    raise WorktreeError(
                        f"could not remove worktree {path}: "
                        f"{(r2.stderr or r.stderr or '').strip()}"
                    )
        removed = True

    if delete_branch and rec and rec.branch.startswith(("feature/", "feat/", "agent/")):
        _run(
            ["git", "branch", "-D", rec.branch],
            cwd=project,
            check=False,
        )

    if agent_id in records:
        del records[agent_id]
        save_registry(project, records)
        removed = True
    return removed


def get_path(project: Path, agent_id: str) -> Path | None:
    records = load_registry(project)
    rec = records.get(agent_id)
    if rec:
        p = Path(rec.path)
        if p.is_dir():
            return p
    p = worktree_path_for(project, agent_id)
    return p if p.is_dir() and _worktree_registered(project, p) else None


def cmd_ensure(args: argparse.Namespace) -> int:
    try:
        project = resolve_project(args.project)
        rec = ensure_worktree(
            project,
            args.agent_id,
            slug=args.slug,
            push_integration=args.push_integration,
        )
    except WorktreeError as e:
        print(f"worktree_for_agent: {e}", file=sys.stderr)
        return 2
    print(f"WORKTREE={rec.path}")
    print(f"BRANCH={rec.branch}")
    print(f"INTEGRATION={rec.integration}")
    print(f"AGENT_ID={rec.agent_id}")
    print(f"PROJECT={rec.project}")
    print(
        f"# cd into worktree: cd {rec.path}\n"
        f"# commit only after /commit-prep; push feature branch only; never auto-merge"
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    try:
        project = resolve_project(args.project)
        assert_git_repo(project)
    except WorktreeError as e:
        print(f"worktree_for_agent: {e}", file=sys.stderr)
        return 2
    records = load_registry(project)
    git_wts = list_git_worktrees(project)
    if not records and len(git_wts) <= 1:
        print("(no agent worktrees registered)")
        return 1
    print(f"{'AGENT_ID':<24} {'BRANCH':<28} PATH")
    for aid, rec in sorted(records.items()):
        print(f"{aid:<24} {rec.branch:<28} {rec.path}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    try:
        project = resolve_project(args.project)
        p = get_path(project, args.agent_id)
    except WorktreeError as e:
        print(f"worktree_for_agent: {e}", file=sys.stderr)
        return 2
    if not p:
        print(f"worktree_for_agent: no worktree for agent {args.agent_id!r}", file=sys.stderr)
        return 1
    print(p)
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    try:
        project = resolve_project(args.project)
        ok = remove_worktree(
            project,
            args.agent_id,
            force=args.force,
            delete_branch=args.delete_branch,
        )
    except WorktreeError as e:
        print(f"worktree_for_agent: {e}", file=sys.stderr)
        return 2
    if not ok:
        print(f"worktree_for_agent: nothing to remove for {args.agent_id!r}", file=sys.stderr)
        return 1
    print(f"removed worktree for agent_id={args.agent_id}")
    return 0


def cmd_ensure_integration(args: argparse.Namespace) -> int:
    try:
        project = resolve_project(args.project)
        name, created = ensure_integration_branch(
            project, push=args.push_integration
        )
    except WorktreeError as e:
        print(f"worktree_for_agent: {e}", file=sys.stderr)
        return 2
    print(f"INTEGRATION={name}")
    print(f"CREATED={'yes' if created else 'no'}")
    return 0


def _add_project_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--project",
        default=None,
        help="project / git root (default: current repo toplevel)",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Per-agent git worktrees for parallel Anchor workers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ens = sub.add_parser("ensure", help="create or reuse worktree for agent-id")
    _add_project_arg(p_ens)
    p_ens.add_argument("--agent-id", required=True)
    p_ens.add_argument(
        "--slug",
        default=None,
        help="optional plan slug → checkout feature/<slug> in the worktree",
    )
    p_ens.add_argument(
        "--push-integration",
        action="store_true",
        help="if creating dev, also try git push -u origin dev",
    )
    p_ens.set_defaults(func=cmd_ensure)

    p_list = sub.add_parser("list", help="list registered agent worktrees")
    _add_project_arg(p_list)
    p_list.set_defaults(func=cmd_list)

    p_path = sub.add_parser("path", help="print worktree path for agent-id")
    _add_project_arg(p_path)
    p_path.add_argument("--agent-id", required=True)
    p_path.set_defaults(func=cmd_path)

    p_rm = sub.add_parser("remove", help="remove worktree for agent-id")
    _add_project_arg(p_rm)
    p_rm.add_argument("--agent-id", required=True)
    p_rm.add_argument("--force", action="store_true")
    p_rm.add_argument(
        "--delete-branch",
        action="store_true",
        help="also delete the agent/feature branch (-D)",
    )
    p_rm.set_defaults(func=cmd_remove)

    p_int = sub.add_parser(
        "ensure-integration",
        help="ensure dev/develop exists (create dev from main/master if needed)",
    )
    _add_project_arg(p_int)
    p_int.add_argument("--push-integration", action="store_true")
    p_int.set_defaults(func=cmd_ensure_integration)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
