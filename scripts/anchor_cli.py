#!/usr/bin/env python3
"""``anchor plans | work | review | draft | fleet-watch | models`` — CLI adapter over ``anchor_ops``.

Parser, mode detection, interactive prompting, text rendering, exit-code
mapping. Workflow lives in ``anchor_ops``; this file does not list lanes,
claim plans, or run the merge gate.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import plan_lease
import plan_store
from anchor_ops import (
    EXIT_ERROR,
    EXIT_NEEDS_OPERATOR,
    EXIT_NOTHING,
    EXIT_OK,
    READY_LANES,
    SCHEMA_VERSION,
    VERBS,
    CliError,
    Ctx,
    DraftCreateParams,
    DraftListParams,
    DraftPromoteParams,
    FleetWatchParams,
    Mode,
    ModelsListParams,
    ModelsNickParams,
    NeedsOperator,
    ReleaseParams,
    NotDelegated,
    Passthrough,
    PlansBoardParams,
    PlansListParams,
    Result,
    ReviewListParams,
    ReviewParams,
    ReviewPromoteParams,
    WorkClaimParams,
    WorkListParams,
    WorkSlugParams,
    critic_verdict,
    detect_mode,
    kebab_slug,
    pick_review_slug,
    plans_root,
    run,
)

# Re-exports for tests and ``anchor.py``.
__all__ = [
    "EXIT_ERROR", "EXIT_NEEDS_OPERATOR", "EXIT_NOTHING", "EXIT_OK",
    "Mode", "NeedsOperator", "Prompter", "Result", "SCHEMA_VERSION", "VERBS",
    "critic_verdict", "detect_mode", "is_verb_invocation", "main",
    "scaffold_collision_hint",
]

# Scaffolder-only flags. A verb plus one of these is almost always
# `anchor ./work --platform …`, not a workflow invocation.
_SCAFFOLD_ONLY_FLAGS = frozenset({
    "--platform", "--fleet", "--framework", "--orchestrator",
    "--set-orchestrator", "--set-review-batch", "--show-review-batch",
    "--upgrade", "--update", "--check", "--diff", "--dry-run",
    "--force", "--yes", "-y",
})


def is_verb_invocation(argv: list[str]) -> bool:
    """True when ``argv`` names a verb. A project dir called ``work`` is ``./work``."""
    return bool(argv) and argv[0] in VERBS


def scaffold_collision_hint(argv: list[str], *, cwd: Path | None = None) -> str | None:
    """One-line hint when a verb parse failed but the operator meant to scaffold."""
    if not argv or argv[0] not in VERBS:
        return None
    verb = argv[0]
    flags = [a.split("=", 1)[0] for a in argv[1:] if a.startswith("-")]
    meant_scaffold = any(f in _SCAFFOLD_ONLY_FLAGS for f in flags)
    if not meant_scaffold:
        root = cwd if cwd is not None else Path.cwd()
        if not (root / verb).is_dir():
            return None
    return f"did you mean `anchor ./{verb} …` to scaffold the directory?"


# --- prompting (the CLI's Answers adapter) -------------------------------------


@dataclass
class Prompter:
    """The only way a verb may ask anything. Headless, it cannot ask at all."""

    mode: Mode
    read: Callable[[str], str] = input

    def choose(self, step: str, question: str, choices: tuple[str, ...]) -> str:
        detail = f"{question} ({' | '.join(choices)})"
        if not self.mode.interactive:
            raise NeedsOperator(step, detail)
        while True:
            try:
                raw = self.read(f"{detail}: ").strip().lower()
            except EOFError as exc:
                raise NeedsOperator(step, detail) from exc
            if raw in choices:
                return raw
            print(f"  answer one of: {', '.join(choices)}", file=sys.stderr)

    def text(self, step: str, question: str) -> str:
        if not self.mode.interactive:
            raise NeedsOperator(step, question)
        try:
            raw = self.read(f"{question}: ").strip()
        except EOFError as exc:
            raise NeedsOperator(step, question) from exc
        if not raw:
            raise NeedsOperator(step, f"{question} (an empty answer is not an answer)")
        return raw


def _default_agent_id() -> str:
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "user"
    return f"anchor-{user}"


# --- rendering -----------------------------------------------------------------


def _render_text(res: Result, out: TextIO) -> None:
    rows = res.data.get("plans")
    if not isinstance(rows, list):
        rows = res.data.get("endpoints")
    if isinstance(rows, list):
        if not rows:
            print("(none)", file=out)
        cols = res.data.get("columns") or (list(rows[0]) if rows else [])
        if rows:
            print("\t".join(cols), file=out)
            for row in rows:
                print("\t".join(_cell(row.get(c)) for c in cols), file=out)
    text = res.data.get("text")
    skip = {"plans", "endpoints", "columns"}
    if isinstance(text, str) and text:
        print(text, end="" if text.endswith("\n") else "\n", file=out)
        skip |= {"text", "units", "cron"}
    for key, value in res.data.items():
        if key in skip:
            continue
        if isinstance(value, list):
            print(f"{key}:", file=out)
            for item in value:
                print(f"  {item}", file=out)
        else:
            print(f"{key}: {_cell(value)}", file=out)
    for note in res.notes:
        print(note, file=out)
    for p in res.pending:
        detail = p.get("detail") or ""
        if detail.startswith("Run `"):
            print(detail, file=out)
        else:
            print(f"→ needs {p['needs']}: {p['step']} — {detail}", file=out)
    if res.error:
        print(f"error: {res.error}", file=sys.stderr)


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value) or "-"
    return str(value)


# --- delegation (injected into Ctx; never called headless) ---------------------


def delegate(
    mode: Mode,
    *,
    endpoint: str,
    role: str,
    registry: str | None,
    user: str,
) -> tuple[str, str]:
    """Send one judgment step to a configured endpoint. Returns ``(endpoint, text)``."""
    if not mode.interactive and role not in ("critic", "planner"):
        raise NotDelegated("non-interactive run: the calling agent does this step itself")
    try:
        import anchor_client
    except ImportError as exc:
        raise NotDelegated(f"delegation needs the {exc.name!r} package") from exc
    from anchor_ops import MYTHOS_CORE

    reg = Path(registry) if registry else anchor_client.DEFAULT_REGISTRY
    if not reg.is_file():
        raise NotDelegated(f"no endpoint registry at {reg}")
    try:
        fleet = anchor_client.Fleet(reg, overlay_root=Path.cwd())
    except Exception as exc:
        raise NotDelegated(f"cannot load {reg}: {exc}") from exc
    if not fleet.endpoints:
        raise NotDelegated(f"no endpoints configured in {reg}")
    if endpoint == "auto":
        try:
            ep = fleet.pick(role)
        except LookupError as exc:
            raise NotDelegated(str(exc)) from exc
    else:
        try:
            ep = fleet.lookup(endpoint)
        except LookupError:
            raise NotDelegated(f"no endpoint named {endpoint!r} in {reg}")
    # Critic must emit a Verdict in the completion budget. Mythos-core +
    # thinking-on burns NVIDIA Lightning's max_tokens on hidden reasoning
    # (HTTP 200, finish_reason=length, empty content). Planner drafts still
    # load doctrine and think.
    thinking = role != "critic"
    if role == "critic":
        system = (
            "You are a code critic. Do not implement. Follow the review "
            "template in the user message. End with ## Verdict and exactly "
            "one of ACCEPT, REVISE, or ESCALATE."
        )
    else:
        try:
            system = anchor_client.load_prompt(MYTHOS_CORE)
        except OSError as exc:
            raise NotDelegated(f"doctrine {MYTHOS_CORE} not found: {exc}") from exc
    try:
        text = ep.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            thinking=thinking,
            max_tokens=8192,
        )
    except Exception as exc:
        raise NotDelegated(f"{ep.name}: {exc}") from exc
    return ep.name, text


# --- parser --------------------------------------------------------------------


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", default=".", help="project root containing .plans/ (default: cwd)")
    p.add_argument("--json", action="store_true", help="machine-readable output (schema_version 1)")
    p.add_argument("--non-interactive", action="store_true",
                   help="never prompt; JSON output; stop with exit 3 where an answer is needed")


def _delegation(p: argparse.ArgumentParser, role: str, *, opt_out: bool = False) -> None:
    extra = "; alias of the default critic" if opt_out else ""
    p.add_argument("--delegate", nargs="?", const="auto", metavar="ENDPOINT",
                   help=f"send the judgment step to ENDPOINT from the registry "
                        f"(bare flag: first endpoint for the '{role}' role; "
                        f"critic/planner also run headless)"
                        f"{extra}")
    if opt_out:
        p.add_argument("--no-delegate", action="store_true",
                       help="skip the critic chat (package + operator decision only)")
    p.add_argument("--registry", help="endpoints.yaml (default: scripts/endpoints.yaml)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="anchor",
        description="Anchor's plan workflow. Scaffolding is `anchor <project-dir> [flags]`.",
        epilog="exit codes: 0 done · 1 nothing to do · 2 usage/hard error · "
               "3 an operator answer (or harness step) is required",
    )
    sub = ap.add_subparsers(
        dest="verb", required=True, metavar="{plans,work,review,draft,fleet-watch,models,release}",
    )

    p = sub.add_parser("plans", help="list plans in every lane")
    _common(p)
    p.add_argument("--lane", action="append", help="only this lane (repeatable)")
    p.add_argument("--board", action="store_true", help="hand off to plan_board (one frame)")

    p = sub.add_parser("work", help="list, claim, heartbeat, finish ready plans")
    _common(p)
    p.add_argument("slug", nargs="?", help="claim this plan (default: highest-priority fit)")
    p.add_argument("--list", action="store_true", help="ready plans with your fit; claim nothing")
    p.add_argument("--agent-id", help="lease identity (default: anchor-$USER)")
    p.add_argument("--tier", help="your fit tier: small|mid|reasoner|frontier")
    p.add_argument("--model", help="your model name, for Preferred-models matching")
    p.add_argument("--effort", help="current reasoning effort (Grok family maps it to a tier)")
    p.add_argument("--endpoint", help="take model+tier from this registry endpoint")
    p.add_argument("--registry", help="endpoints.yaml for --endpoint")
    p.add_argument("--no-fit-check", action="store_true", help="ignore Preferred models")
    p.add_argument("--run", action="store_true",
                   help="execute after claim (default); kept as an explicit alias")
    p.add_argument("--no-run", action="store_true",
                   help="claim only; do not start orchestrate.py")
    p.add_argument("--no-finish", action="store_true",
                   help="with --run, leave the plan in in-progress/ even when "
                        "orchestrate exits 0")
    p.add_argument("--no-commit", action="store_true",
                   help="with --run, skip commit-prep + feature-branch commit")
    p.add_argument("--heartbeat", metavar="SLUG", help="extend your lease on SLUG")
    p.add_argument("--finish", metavar="SLUG", help="your in-progress SLUG → review-needed/")
    p.add_argument("--return", dest="return_ready", metavar="SLUG",
                   help="release your in-progress SLUG back to its ready lane")

    p = sub.add_parser("review", help="list review-needed plans; decide one")
    _common(p)
    p.add_argument("slug", nargs="?", help="review this plan (default: highest-priority in review-needed/)")
    p.add_argument("--list", action="store_true", help="list review-needed plans")
    p.add_argument(
        "--promote", action="store_true",
        help="promote integration → mainline when the review queue is empty",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--approve", action="store_true",
                   help="survey Approve: FF-merge feature → integration and archive")
    g.add_argument("--needs-work", action="store_true",
                   help="return the plan to bugs/ or features/")
    g.add_argument("--skip", action="store_true", dest="review_skip",
                   help="leave the plan in review-needed/")
    g.add_argument("--defer", action="store_true",
                   help="move the plan to blocked/")
    p.add_argument("--force-approve", action="store_true",
                   help="with --approve: merge even if the critic is REVISE/UNKNOWN/ESCALATE")
    p.add_argument("--notes", help="with --needs-work or --defer: required notes")
    p.add_argument("--to", choices=("bugs", "features"),
                   help="with --needs-work: ready lane (default: bugs)")
    _delegation(p, "critic", opt_out=True)

    p = sub.add_parser("draft", help="list drafts; scaffold or promote one")
    _common(p)
    p.add_argument("words", nargs="*", help="brief (spaces ok) or existing slug; kebab slug is derived")
    p.add_argument("--list", action="store_true", help="list drafts")
    p.add_argument("--title", help="plan title (default: the slug)")
    p.add_argument("--goal", help="one-paragraph Goal to seed the draft")
    p.add_argument("--local", action="store_true", default=True, help="private *.local.md (default)")
    p.add_argument("--shared", action="store_true", help="tracked drafts/<slug>.md instead of .local.md")
    p.add_argument("--promote", metavar="SLUG", help="move drafts/SLUG to a ready lane")
    p.add_argument("--to", choices=READY_LANES, help="with --promote: the ready lane")
    _delegation(p, "planner", opt_out=True)

    p = sub.add_parser("fleet-watch", help="inspect or emit per-project plan daemons")
    _common(p)
    p.add_argument("--project", help="project root (alias of --root)")
    p.add_argument("--status", action="store_true", help="inspect .plans/ and installed timers")
    p.add_argument("--list", action="store_true", help="work_once --list for this project")
    p.add_argument("--once", action="store_true", help="work_once --once (one pull)")
    p.add_argument("--triage", action="store_true", help="mechanical take/skip/reject")
    p.add_argument("--emit", choices=("systemd", "cron", "both"),
                   help="print unit files / crontab lines (does not install)")
    p.add_argument("--install-user", action="store_true",
                   help="write systemd user units (interactive operator only)")
    p.add_argument("--yes", action="store_true",
                   help="with --install-user, skip the confirm (still requires a TTY)")
    p.add_argument("--worker", action="append", default=[], metavar="SPEC",
                   help="tier=mid,agent=id,interval=5m[,watch=0] (repeatable)")
    p.add_argument("--tier", help="for --list/--once/--triage")
    p.add_argument("--agent-id", help="for --list/--once/--triage")
    p.add_argument("--endpoint", help="registry endpoint for --list/--once")
    p.add_argument("--model", help="model name for --list/--once")
    p.add_argument("--registry", help="endpoints.yaml for --endpoint")
    p.add_argument("--run", action="store_true",
                   help="with --once, execute (omit to pass --no-run to work_once)")
    p.add_argument("--load-watcher", action="store_true",
                   help="also emit the inference_load --watch unit")
    p.add_argument(
        "--write-dir",
        help="write emitted units into this directory (interactive operator only)",
    )
    p.add_argument("--python", help="interpreter for ExecStart")

    p = sub.add_parser("models", help="list configured endpoints; assign nicknames")
    _common(p)
    p.add_argument("action", nargs="?", choices=("list", "nick"), default="list")
    p.add_argument("alias", nargs="?", help="with nick: the short name")
    p.add_argument("--endpoint", help="canonical registry name to nickname")
    p.add_argument("--machine", help="operator machine label (flippy, rack, …)")
    p.add_argument("--effort", help="default reasoning effort for this nickname")
    p.add_argument("--overlay", help="write nicknames here (default: ~/.config/anchor/endpoints.local.yaml)")
    p.add_argument("--registry", help="shared endpoints.yaml to resolve --endpoint")
    p.add_argument("--list", action="store_true", help="same as `models list`")

    p = sub.add_parser(
        "release",
        help="unmerged-work report, plan-diff, tag; never merges",
    )
    _common(p)
    p.add_argument("--dry-run", action="store_true",
                   help="print the report and suggested tag; do not write git")
    p.add_argument("--yes", action="store_true",
                   help="TTY: fold CHANGELOG, bump pyproject, annotated tag (no push)")
    p.add_argument("--push", action="store_true",
                   help="TTY: git push the release base and tag (never --force)")
    p.add_argument("--base", help="release base branch (default: dev, else main)")
    p.add_argument("--since", type=float, default=30.0, metavar="DAYS",
                   help="recency window in days (default 30)")
    p.add_argument("--all-pending", action="store_true",
                   help="list every branch ahead of its merge target")
    p.add_argument("--skip-review", action="store_true",
                   help="skip the plan-diff critic (warns)")
    p.add_argument("--force-omit-finished", action="store_true",
                   help="tag even if completed/review-needed work is still off-base")
    p.add_argument("--force-tag", action="store_true",
                   help="tag even if plan-diff is HOLD")
    p.add_argument("--bump", choices=("patch", "minor", "major"),
                   help="semver bump when --tag is omitted")
    p.add_argument("--tag", help="exact tag name (must match the repo scheme)")
    _delegation(p, "critic", opt_out=True)
    return ap


def _cli_action(args: argparse.Namespace) -> str:
    """Sub-action for the JSON envelope, including the CliError path."""
    verb = args.verb
    if verb == "work":
        if getattr(args, "list", False):
            return "list"
        if getattr(args, "heartbeat", None):
            return "heartbeat"
        if getattr(args, "finish", None):
            return "finish"
        if getattr(args, "return_ready", None):
            return "return"
        return "claim"
    if verb == "review":
        if getattr(args, "promote", False):
            return "promote"
        if getattr(args, "list", False):
            return "list"
        return "review"
    if getattr(args, "list", False):
        return "list"
    if verb == "plans" and getattr(args, "board", False):
        return "board"
    if verb == "models":
        if getattr(args, "list", False) or args.action == "list":
            return "list"
        return args.action or "list"
    if verb == "release":
        if getattr(args, "yes", False) or getattr(args, "push", False):
            return "ship"
        return "report"
    return verb


def _bind_project_root(args: argparse.Namespace) -> None:
    """Walk up from ``--root`` (default cwd) to the nearest ``.plans/`` tree."""
    raw = getattr(args, "root", None)
    if raw is None:
        raw = getattr(args, "project", None)
    if raw is None:
        return
    found = plan_store.discover_project_root(Path(raw))
    if found is not None:
        args.root = str(found)
        if hasattr(args, "project"):
            args.project = str(found)


def _dispatch(args: argparse.Namespace, answers: Prompter, ctx: Ctx) -> Result:
    _bind_project_root(args)
    verb = args.verb
    if verb == "plans":
        if args.board:
            return run(
                "plans.board",
                PlansBoardParams(root=args.root, as_json=args.json or not ctx.mode.interactive),
                answers, ctx,
            )
        lanes = tuple(args.lane) if args.lane else None
        return run("plans.list", PlansListParams(root=args.root, lanes=lanes), answers, ctx)
    if verb == "work":
        worker = dict(tier=args.tier, model=args.model, effort=args.effort,
                      endpoint=args.endpoint, registry=args.registry)
        if args.list:
            return run("work.list", WorkListParams(root=args.root, **worker), answers, ctx)
        if args.heartbeat:
            return run("work.heartbeat", WorkSlugParams(root=args.root, slug=args.heartbeat), answers, ctx)
        if args.finish:
            return run("work.finish", WorkSlugParams(root=args.root, slug=args.finish), answers, ctx)
        if args.return_ready:
            return run("work.return", WorkSlugParams(root=args.root, slug=args.return_ready), answers, ctx)
        return run("work.claim", WorkClaimParams(
            root=args.root, slug=args.slug, no_fit_check=args.no_fit_check,
            run=not args.no_run, no_finish=args.no_finish,
            no_commit=getattr(args, "no_commit", False), **worker,
        ), answers, ctx)
    if verb == "models":
        if args.list or args.action == "list" or not args.alias:
            if args.action == "nick" and not args.alias:
                raise CliError("models nick needs an alias")
            return run(
                "models.list",
                ModelsListParams(root=args.root, registry=args.registry),
                answers, ctx,
            )
        if not args.endpoint:
            raise CliError("models nick needs --endpoint <canonical-name>")
        return run(
            "models.nick",
            ModelsNickParams(
                root=args.root,
                alias=args.alias,
                endpoint=args.endpoint,
                machine=args.machine,
                effort=args.effort,
                overlay=args.overlay,
                registry=args.registry,
            ),
            answers, ctx,
        )
    if verb == "review":
        if args.promote:
            return run(
                "review.promote", ReviewPromoteParams(root=args.root), answers, ctx,
            )
        if args.list:
            return run("review.list", ReviewListParams(root=args.root), answers, ctx)
        no_delegate = bool(getattr(args, "no_delegate", False))
        delegate = None if no_delegate else (args.delegate or "auto")
        slug = args.slug
        if not slug:
            slug = pick_review_slug(plans_root(args.root))
            if not slug:
                return run(
                    "review.list",
                    ReviewListParams(root=args.root, suggest_promote=True),
                    answers, ctx,
                )
        decision = None
        if args.approve:
            decision = "approve"
        elif args.needs_work:
            decision = "needs-work"
        elif getattr(args, "review_skip", False):
            decision = "skip"
        elif args.defer:
            decision = "defer"
        return run("review.review", ReviewParams(
            root=args.root, slug=slug, delegate=delegate,
            registry=args.registry, no_delegate=no_delegate,
            decision=decision,
            force_approve=bool(args.force_approve),
            notes=args.notes,
            to=args.to or ("bugs" if args.needs_work else None),
        ), answers, ctx)
    if verb == "fleet-watch":
        root = args.project or args.root
        fw = FleetWatchParams(
            root=root,
            workers=tuple(args.worker or ()),
            emit=args.emit,
            yes=args.yes,
            triage=args.triage,
            run=args.run,
            tier=args.tier,
            agent_id=args.agent_id,
            endpoint=args.endpoint,
            model=args.model,
            registry=args.registry,
            python=args.python,
            write_dir=args.write_dir,
            load_watcher=args.load_watcher,
        )
        if args.install_user:
            return run("fleet-watch.install", fw, answers, ctx)
        if args.write_dir:
            wr = run("fleet-watch.write", fw, answers, ctx)
            if wr.exit_code != EXIT_OK or not args.emit:
                return wr
        if args.emit:
            return run("fleet-watch.emit", fw, answers, ctx)
        if args.once or args.triage:
            return run("fleet-watch.once", fw, answers, ctx)
        if args.list:
            return run("fleet-watch.list", fw, answers, ctx)
        return run("fleet-watch.status", fw, answers, ctx)
    if verb == "release":
        no_delegate = bool(getattr(args, "no_delegate", False))
        delegate = None if no_delegate else getattr(args, "delegate", None)
        rp = ReleaseParams(
            root=args.root,
            dry_run=bool(args.dry_run),
            yes=bool(args.yes),
            push=bool(args.push),
            base=args.base,
            since=None if args.all_pending else args.since,
            all_pending=bool(args.all_pending),
            skip_review=bool(args.skip_review),
            force_omit_finished=bool(args.force_omit_finished),
            force_tag=bool(args.force_tag),
            bump=args.bump,
            tag=args.tag,
            delegate=delegate,
            registry=getattr(args, "registry", None),
            no_delegate=no_delegate,
        )
        if args.yes or args.push:
            return run("release.ship", rp, answers, ctx)
        return run("release.report", rp, answers, ctx)
    if args.promote:
        return run("draft.promote", DraftPromoteParams(root=args.root, slug=args.promote, to=args.to), answers, ctx)
    words = tuple(getattr(args, "words", ()) or ())
    if args.list or (not words and not getattr(args, "slug", None)):
        return run("draft.list", DraftListParams(root=args.root), answers, ctx)
    brief = " ".join(words)
    slug = kebab_slug(brief)
    goal = args.goal or (brief if " " in brief or len(words) > 1 else args.goal)
    no_delegate = bool(getattr(args, "no_delegate", False))
    delegate = None if no_delegate else (args.delegate or "auto")
    local = not bool(getattr(args, "shared", False))
    return run("draft.create", DraftCreateParams(
        root=args.root, slug=slug, title=args.title, goal=goal,
        local=local, delegate=delegate, registry=args.registry,
    ), answers, ctx)


def main(
    argv: list[str],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    env: dict[str, str] | None = None,
    read: Callable[[str], str] = input,
) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        if exc.code == 2:
            hint = scaffold_collision_hint(argv)
            if hint:
                print(hint, file=sys.stderr)
        raise
    mode = detect_mode(args.non_interactive, stdin=stdin, stdout=stdout, env=env)
    out = stdout or sys.stdout
    as_json = args.json or not mode.interactive
    action = _cli_action(args)
    agent_id = getattr(args, "agent_id", None) or _default_agent_id()
    ctx = Ctx(mode=mode, agent_id=agent_id)
    ctx.delegate = lambda endpoint, role, registry, user: delegate(
        mode, endpoint=endpoint, role=role, registry=registry, user=user,
    )
    from work_once import run_orchestrate

    ctx.run_orchestrate = run_orchestrate
    if mode.interactive and not as_json:
        ctx.display = lambda msg: print(msg, file=sys.stderr)
    try:
        res = _dispatch(args, Prompter(mode, read), ctx)
    except Passthrough as p:
        return p.code
    except NeedsOperator as exc:
        res = Result(args.verb, action, exit_code=EXIT_NEEDS_OPERATOR)
        res.need(exc.step, "operator", exc.detail)
    except (CliError, plan_store.PlanMoveError, plan_lease.ClaimError, FileExistsError) as exc:
        res = Result(args.verb, action, exit_code=EXIT_ERROR, error=str(exc))
    if as_json:
        print(json.dumps(res.to_json(mode), indent=2, default=str), file=out)
    else:
        _render_text(res, out)
    return res.exit_code
