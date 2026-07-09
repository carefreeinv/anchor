#!/usr/bin/env python3
"""Configure and emit durable plan-watchers for a project.

Wraps work_once.py for multi-tier pullers and prints (or installs) systemd
**user** timers that survive reboot (with linger). Also emits crontab lines
as a fallback.

Usage:
  # Inspect project + backlog for a worker
  python fleet_watch.py --project /path/to/app --status
  python fleet_watch.py --project /path/to/app --list --tier mid --agent-id mid-1

  # Dry-run one claim (same as work_once --once)
  python fleet_watch.py --project /path/to/app --once --tier mid --agent-id mid-1

  # Print systemd user units + enable commands (does not install)
  python fleet_watch.py --project /path/to/app --emit systemd \\
    --worker tier=mid,agent=mid-1,interval=5m \\
    --worker tier=small,agent=swarm-1,interval=10m

  # Install user timers (persist after reboot with linger)
  python fleet_watch.py --project /path/to/app --install-user \\
    --worker tier=mid,agent=mid-1,interval=5m --yes

  # Crontab lines only
  python fleet_watch.py --project /path/to/app --emit cron \\
    --worker tier=mid,agent=mid-1,interval=5m
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_PYTHON = sys.executable
DEFAULT_INTERVAL = "5m"

_INTERVAL_RE = re.compile(
    r"^(?:(?P<days>\d+)d)?(?:(?P<hours>\d+)h)?(?:(?P<mins>\d+)m)?(?:(?P<secs>\d+)s)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkerSpec:
    tier: str | None
    agent_id: str
    interval: str  # human form e.g. 5m
    endpoint: str | None = None
    model: str | None = None
    registry: str | None = None
    run: bool = False

    def unit_stem(self, project_slug: str) -> str:
        safe_agent = re.sub(r"[^a-zA-Z0-9_.@-]+", "-", self.agent_id)
        return f"anchor-watch-{project_slug}-{safe_agent}"


def parse_interval_to_systemd(interval: str) -> str:
    """Convert 5m / 10min / 1h / 30s / 300 → systemd time (e.g. 5min)."""
    raw = interval.strip().lower().replace(" ", "")
    if raw.isdigit():
        return f"{int(raw)}s"
    # 5min / 10mins
    m = re.fullmatch(r"(\d+)(min|mins|m|h|hr|hrs|hours|s|sec|secs|d|day|days)", raw)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit in {"m", "min", "mins"}:
            return f"{n}min"
        if unit in {"h", "hr", "hrs", "hours"}:
            return f"{n}h"
        if unit in {"s", "sec", "secs"}:
            return f"{n}s"
        if unit in {"d", "day", "days"}:
            return f"{n}d"
    # compound 1h30m
    m2 = _INTERVAL_RE.fullmatch(raw)
    if m2 and any(m2.groupdict().values()):
        parts = []
        if m2.group("days"):
            parts.append(f"{int(m2.group('days'))}d")
        if m2.group("hours"):
            parts.append(f"{int(m2.group('hours'))}h")
        if m2.group("mins"):
            parts.append(f"{int(m2.group('mins'))}min")
        if m2.group("secs"):
            parts.append(f"{int(m2.group('secs'))}s")
        return "".join(parts) if parts else "5min"
    return raw  # pass through for systemd


def parse_interval_to_cron_step_minutes(interval: str) -> int | None:
    """Best-effort minutes for cron */N; None if not a simple minute interval."""
    sysd = parse_interval_to_systemd(interval)
    m = re.fullmatch(r"(\d+)min", sysd)
    if m:
        return max(1, int(m.group(1)))
    m = re.fullmatch(r"(\d+)h", sysd)
    if m:
        return max(1, int(m.group(1)) * 60)
    m = re.fullmatch(r"(\d+)s", sysd)
    if m:
        secs = int(m.group(1))
        return max(1, (secs + 59) // 60)
    return None


def parse_worker(spec: str) -> WorkerSpec:
    """Parse tier=mid,agent=mid-1,interval=5m,endpoint=h100,run=1."""
    parts: dict[str, str] = {}
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise SystemExit(
                f"worker spec needs key=value pairs, got {chunk!r} in {spec!r}"
            )
        k, v = chunk.split("=", 1)
        parts[k.strip().lower()] = v.strip()
    agent = parts.get("agent") or parts.get("agent-id") or parts.get("agent_id")
    if not agent:
        raise SystemExit(f"worker spec requires agent=… : {spec!r}")
    tier = parts.get("tier")
    endpoint = parts.get("endpoint")
    if not tier and not endpoint:
        raise SystemExit(f"worker spec requires tier=… or endpoint=… : {spec!r}")
    return WorkerSpec(
        tier=tier,
        agent_id=agent,
        interval=parts.get("interval", DEFAULT_INTERVAL),
        endpoint=endpoint,
        model=parts.get("model"),
        registry=parts.get("registry"),
        run=parts.get("run", "").lower() in {"1", "true", "yes", "on"},
    )


def project_slug(project: Path) -> str:
    name = project.resolve().name
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-").lower()
    return slug or "project"


def resolve_scripts(scripts: Path | None) -> Path:
    d = (scripts or SCRIPTS_DIR).resolve()
    if not (d / "work_once.py").is_file():
        raise SystemExit(f"work_once.py not found under {d}")
    return d


def work_once_cmd(
    scripts: Path,
    project: Path,
    worker: WorkerSpec,
    *,
    python: str,
    extra: list[str] | None = None,
) -> list[str]:
    cmd = [
        python,
        str(scripts / "work_once.py"),
        "--root",
        str(project.resolve()),
        "--once",
        "--agent-id",
        worker.agent_id,
    ]
    if worker.endpoint:
        cmd.extend(["--endpoint", worker.endpoint])
    if worker.tier:
        cmd.extend(["--tier", worker.tier])
    if worker.model:
        cmd.extend(["--model", worker.model])
    if worker.registry:
        cmd.extend(["--registry", worker.registry])
    elif worker.endpoint:
        reg = scripts / "endpoints.yaml"
        if reg.is_file():
            cmd.extend(["--registry", str(reg)])
    if worker.run:
        cmd.append("--run")
    if extra:
        cmd.extend(extra)
    return cmd


def cmd_status(project: Path, scripts: Path) -> int:
    plans = project / ".plans"
    print(f"project:  {project.resolve()}")
    print(f"scripts:  {scripts}")
    print(f".plans/:  {'OK' if plans.is_dir() else 'MISSING'}")
    if plans.is_dir():
        for lane in (
            "bugs",
            "features",
            "in-progress",
            "ambiguous",
            "blocked",
            "drafts",
            "completed",
        ):
            d = plans / lane
            n = len(list(d.glob("*.md"))) if d.is_dir() else 0
            print(f"  {lane:12s} {n} plan(s)" + ("" if d.is_dir() else " (no dir)"))
    conv = project / "ANCHOR-CONVENTIONS.md"
    if conv.is_file():
        text = conv.read_text(encoding="utf-8")
        m = re.search(
            r"\*\*Preferred orchestrator:\*\*\s*`?([^`\n]+)`?",
            text,
        )
        if m:
            print(f"orchestrator: {m.group(1).strip()}")
        else:
            print("orchestrator: (not set in ANCHOR-CONVENTIONS.md)")
    else:
        print("orchestrator: (no ANCHOR-CONVENTIONS.md)")

    # User systemd units for this project
    user_dir = Path.home() / ".config" / "systemd" / "user"
    slug = project_slug(project)
    prefix = f"anchor-watch-{slug}-"
    if user_dir.is_dir():
        units = sorted(user_dir.glob(f"{prefix}*.timer"))
        if units:
            print("user timers:")
            for u in units:
                print(f"  {u.name}")
        else:
            print(f"user timers: none matching {prefix}*.timer")
    else:
        print("user timers: ~/.config/systemd/user not present")

    # linger
    try:
        out = subprocess.run(
            ["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.stdout.strip():
            print(f"linger:    {out.stdout.strip()}  (Linger=yes needed for reboot without login)")
    except (OSError, subprocess.TimeoutExpired):
        print("linger:    (loginctl unavailable)")

    print(
        "\nTip: persistent user timers need:\n"
        "  loginctl enable-linger $USER\n"
        "  systemctl --user daemon-reload && systemctl --user enable --now <timer>"
    )
    return 0 if plans.is_dir() else 2


def cmd_list_or_once(
    project: Path,
    scripts: Path,
    args: argparse.Namespace,
    *,
    once: bool,
) -> int:
    worker = WorkerSpec(
        tier=args.tier,
        agent_id=args.agent_id or f"watch-{os.environ.get('USER', 'agent')}",
        interval=DEFAULT_INTERVAL,
        endpoint=args.endpoint,
        model=args.model,
        registry=args.registry,
        run=args.run,
    )
    if once:
        cmd = work_once_cmd(
            scripts, project, worker, python=args.python
        )
    else:
        cmd = [
            args.python,
            str(scripts / "work_once.py"),
            "--root",
            str(project.resolve()),
            "--list",
            "--agent-id",
            worker.agent_id,
        ]
        if worker.tier:
            cmd.extend(["--tier", worker.tier])
        if worker.endpoint:
            cmd.extend(["--endpoint", worker.endpoint])
        if worker.model:
            cmd.extend(["--model", worker.model])
        if worker.registry:
            cmd.extend(["--registry", worker.registry])
        elif worker.endpoint:
            reg = scripts / "endpoints.yaml"
            if reg.is_file():
                cmd.extend(["--registry", str(reg)])
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.call(cmd, env={**os.environ, "PYTHONPATH": str(scripts)})


def render_service_unit(
    project: Path,
    scripts: Path,
    worker: WorkerSpec,
    *,
    python: str,
) -> str:
    cmd = work_once_cmd(scripts, project, worker, python=python)
    # systemd ExecStart wants argv-style; quote paths with spaces
    exec_start = " ".join(_shell_quote(c) for c in cmd)
    desc = f"Anchor plan watcher {worker.agent_id} ({worker.tier or worker.endpoint})"
    return f"""# Generated by fleet_watch.py — do not hand-edit without need
[Unit]
Description={desc}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={_shell_quote(str(project.resolve()))}
Environment=PYTHONPATH={_shell_quote(str(scripts))}
ExecStart={exec_start}
# work_once exit 1 = idle backlog (not a failure)
SuccessExitStatus=0 1

[Install]
WantedBy=default.target
"""


def render_timer_unit(worker: WorkerSpec, service_name: str) -> str:
    interval = parse_interval_to_systemd(worker.interval)
    return f"""# Generated by fleet_watch.py
[Unit]
Description=Timer for {service_name}

[Timer]
OnBootSec=2min
OnUnitActiveSec={interval}
Persistent=true
Unit={service_name}

[Install]
WantedBy=timers.target
"""


def _shell_quote(s: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=@%+-]+", s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def emit_systemd(
    project: Path,
    scripts: Path,
    workers: list[WorkerSpec],
    *,
    python: str,
) -> list[tuple[str, str]]:
    """Return list of (filename, content) for service+timer pairs."""
    slug = project_slug(project)
    files: list[tuple[str, str]] = []
    for w in workers:
        stem = w.unit_stem(slug)
        svc = f"{stem}.service"
        tmr = f"{stem}.timer"
        files.append((svc, render_service_unit(project, scripts, w, python=python)))
        files.append((tmr, render_timer_unit(w, svc)))
    return files


def emit_cron_lines(
    project: Path,
    scripts: Path,
    workers: list[WorkerSpec],
    *,
    python: str,
) -> list[str]:
    lines = [
        f"# Anchor fleet_watch for {project.resolve()} — add to crontab -e",
    ]
    for w in workers:
        mins = parse_interval_to_cron_step_minutes(w.interval)
        schedule = f"*/{mins} * * * *" if mins else "*/5 * * * *"
        cmd = work_once_cmd(scripts, project, w, python=python)
        # log to project-local file
        log = project / ".plans" / f"watch-{w.agent_id}.log"
        line = (
            f"{schedule}  cd {_shell_quote(str(project.resolve()))} && "
            f"PYTHONPATH={_shell_quote(str(scripts))} "
            f"{' '.join(_shell_quote(c) for c in cmd)} "
            f">>{_shell_quote(str(log))} 2>&1"
        )
        lines.append(line)
    return lines


def install_user_units(
    files: list[tuple[str, str]],
    *,
    yes: bool,
) -> int:
    user_dir = Path.home() / ".config" / "systemd" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    timers: list[str] = []
    for name, content in files:
        dest = user_dir / name
        if dest.exists() and not yes:
            print(f"refusing to overwrite {dest} (pass --yes)", file=sys.stderr)
            return 2
        dest.write_text(content, encoding="utf-8")
        print(f"wrote {dest}")
        if name.endswith(".timer"):
            timers.append(name)
    if not shutil.which("systemctl"):
        print("systemctl not found; units written but not enabled", file=sys.stderr)
        return 0
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    for t in timers:
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", t],
            check=False,
        )
        print(f"enabled --now {t}")
    print(
        "\nFor timers to fire after reboot without an interactive login:\n"
        "  loginctl enable-linger $USER\n"
        "Check: systemctl --user list-timers 'anchor-watch-*'"
    )
    return 0


def print_enable_commands(files: list[tuple[str, str]]) -> None:
    timers = [n for n, _ in files if n.endswith(".timer")]
    print("\n# --- install (user systemd; survives reboot with linger) ---")
    print("mkdir -p ~/.config/systemd/user")
    for name, _ in files:
        print(f"# write unit body to ~/.config/systemd/user/{name}")
    print("systemctl --user daemon-reload")
    for t in timers:
        print(f"systemctl --user enable --now {t}")
    print("loginctl enable-linger $USER   # important for reboot persistence")
    print("systemctl --user list-timers 'anchor-watch-*'")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--project",
        "-p",
        required=True,
        help="project root that contains .plans/",
    )
    ap.add_argument(
        "--scripts",
        default=None,
        help="directory with work_once.py (default: this script's directory)",
    )
    ap.add_argument("--python", default=DEFAULT_PYTHON, help="python for ExecStart")
    ap.add_argument("--status", action="store_true", help="inspect project + installed timers")
    ap.add_argument("--list", action="store_true", help="run work_once --list for project")
    ap.add_argument("--once", action="store_true", help="run work_once --once for project")
    ap.add_argument("--tier", help="worker tier for --list/--once")
    ap.add_argument("--agent-id", help="agent id for --list/--once")
    ap.add_argument("--endpoint", help="endpoint name for --list/--once")
    ap.add_argument("--model", help="model name for --list/--once")
    ap.add_argument("--registry", help="endpoints.yaml path")
    ap.add_argument("--run", action="store_true", help="with --once, pass --run to work_once")
    ap.add_argument(
        "--worker",
        action="append",
        default=[],
        metavar="SPEC",
        help="worker tier=mid,agent=id,interval=5m[,endpoint=name][,run=1] (repeatable)",
    )
    ap.add_argument(
        "--emit",
        choices=("systemd", "cron", "both"),
        help="print unit files and/or crontab lines to stdout",
    )
    ap.add_argument(
        "--install-user",
        action="store_true",
        help="write systemd user units under ~/.config/systemd/user and enable timers",
    )
    ap.add_argument(
        "--yes",
        action="store_true",
        help="overwrite existing unit files when installing",
    )
    ap.add_argument(
        "--write-dir",
        help="write emitted unit files into this directory instead of stdout",
    )
    args = ap.parse_args(argv)

    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        print(f"project not a directory: {project}", file=sys.stderr)
        return 2
    scripts = resolve_scripts(Path(args.scripts) if args.scripts else None)

    if args.status:
        return cmd_status(project, scripts)

    if args.list:
        if not args.tier and not args.endpoint:
            ap.error("--list needs --tier or --endpoint")
        return cmd_list_or_once(project, scripts, args, once=False)

    if args.once:
        if not args.tier and not args.endpoint:
            ap.error("--once needs --tier or --endpoint")
        return cmd_list_or_once(project, scripts, args, once=True)

    if args.emit or args.install_user or args.write_dir:
        if not args.worker:
            ap.error("--emit / --install-user / --write-dir require at least one --worker")
        workers = [parse_worker(w) for w in args.worker]
        files = emit_systemd(project, scripts, workers, python=args.python)

        if args.write_dir:
            out = Path(args.write_dir)
            out.mkdir(parents=True, exist_ok=True)
            for name, content in files:
                (out / name).write_text(content, encoding="utf-8")
                print(f"wrote {out / name}")

        if args.emit in ("systemd", "both"):
            for name, content in files:
                print(f"### {name}")
                print(content)
            print_enable_commands(files)

        if args.emit in ("cron", "both"):
            print("### crontab")
            for line in emit_cron_lines(project, scripts, workers, python=args.python):
                print(line)

        if args.install_user:
            return install_user_units(files, yes=args.yes)

        if args.write_dir and not args.emit:
            print_enable_commands(files)

        return 0

    ap.print_help()
    print(
        "\nExamples:\n"
        f"  {Path(sys.argv[0]).name} --project ~/app --status\n"
        f"  {Path(sys.argv[0]).name} --project ~/app --emit systemd "
        f"--worker tier=mid,agent=mid-1,interval=5m\n"
        f"  {Path(sys.argv[0]).name} --project ~/app --install-user --yes "
        f"--worker tier=mid,agent=mid-1,interval=5m\n",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
