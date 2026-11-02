#!/usr/bin/env python3
"""``anchor plans | work | review | draft`` — CLI adapter over ``anchor_ops``.

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
    Mode,
    NeedsOperator,
    NotDelegated,
    Passthrough,
    PlansBoardParams,
    PlansListParams,
    Result,
    ReviewListParams,
    ReviewParams,
    WorkClaimParams,
    WorkListParams,
    WorkSlugParams,
    critic_verdict,
    detect_mode,
    run,
)

# Re-exports for tests and ``anchor.py``.
__all__ = [
    "EXIT_ERROR", "EXIT_NEEDS_OPERATOR", "EXIT_NOTHING", "EXIT_OK",
    "Mode", "NeedsOperator", "Prompter", "Result", "SCHEMA_VERSION", "VERBS",
    "critic_verdict", "detect_mode", "is_verb_invocation", "main",
]


def is_verb_invocation(argv: list[str]) -> bool:
    """True when ``argv`` names a verb. A project dir called ``work`` is ``./work``."""
    return bool(argv) and argv[0] in VERBS


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
    if isinstance(rows, list):
        if not rows:
            print("(no plans)", file=out)
        cols = res.data.get("columns") or (list(rows[0]) if rows else [])
        if rows:
            print("\t".join(cols), file=out)
            for row in rows:
                print("\t".join(_cell(row.get(c)) for c in cols), file=out)
    for key, value in res.data.items():
        if key in ("plans", "columns"):
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
        print(f"→ needs {p['needs']}: {p['step']} — {p['detail']}", file=out)
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
    if not mode.interactive:
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
        fleet = anchor_client.Fleet(reg)
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
        matches = [e for e in fleet.endpoints if e.name == endpoint]
        if not matches:
            raise NotDelegated(f"no endpoint named {endpoint!r} in {reg}")
        ep = matches[0]
    try:
        system = anchor_client.load_prompt(MYTHOS_CORE)
    except OSError as exc:
        raise NotDelegated(f"doctrine {MYTHOS_CORE} not found: {exc}") from exc
    try:
        text = ep.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            thinking=True,
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


def _delegation(p: argparse.ArgumentParser, role: str) -> None:
    p.add_argument("--delegate", nargs="?", const="auto", metavar="ENDPOINT",
                   help=f"interactive only: send the judgment step to ENDPOINT from the "
                        f"registry (bare flag: first endpoint for the '{role}' role)")
    p.add_argument("--registry", help="endpoints.yaml (default: scripts/endpoints.yaml)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="anchor",
        description="Anchor's plan workflow. Scaffolding is `anchor <project-dir> [flags]`.",
        epilog="exit codes: 0 done · 1 nothing to do · 2 usage/hard error · "
               "3 an operator answer (or harness step) is required",
    )
    sub = ap.add_subparsers(dest="verb", required=True, metavar="{plans,work,review,draft}")

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
                   help="interactive only: hand the claimed plan to orchestrate.py")
    p.add_argument("--heartbeat", metavar="SLUG", help="extend your lease on SLUG")
    p.add_argument("--finish", metavar="SLUG", help="your in-progress SLUG → review-needed/")
    p.add_argument("--return", dest="return_ready", metavar="SLUG",
                   help="release your in-progress SLUG back to its ready lane")

    p = sub.add_parser("review", help="list review-needed plans; decide one")
    _common(p)
    p.add_argument("slug", nargs="?", help="review this plan (asks for the decision)")
    p.add_argument("--list", action="store_true", help="list review-needed plans")
    _delegation(p, "critic")

    p = sub.add_parser("draft", help="list drafts; scaffold or promote one")
    _common(p)
    p.add_argument("slug", nargs="?", help="scaffold drafts/<slug>")
    p.add_argument("--list", action="store_true", help="list drafts")
    p.add_argument("--title", help="plan title (default: the slug)")
    p.add_argument("--goal", help="one-paragraph Goal to seed the draft")
    p.add_argument("--local", action="store_true", help="private (untracked) plan")
    p.add_argument("--promote", metavar="SLUG", help="move drafts/SLUG to a ready lane")
    p.add_argument("--to", choices=READY_LANES, help="with --promote: the ready lane")
    _delegation(p, "planner")
    return ap


def _dispatch(args: argparse.Namespace, answers: Prompter, ctx: Ctx) -> Result:
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
            root=args.root, slug=args.slug, no_fit_check=args.no_fit_check, run=args.run, **worker,
        ), answers, ctx)
    if verb == "review":
        if args.list or not args.slug:
            return run("review.list", ReviewListParams(root=args.root), answers, ctx)
        return run("review.review", ReviewParams(
            root=args.root, slug=args.slug, delegate=args.delegate, registry=args.registry,
        ), answers, ctx)
    if args.promote:
        return run("draft.promote", DraftPromoteParams(root=args.root, slug=args.promote, to=args.to), answers, ctx)
    if args.list or not args.slug:
        return run("draft.list", DraftListParams(root=args.root), answers, ctx)
    return run("draft.create", DraftCreateParams(
        root=args.root, slug=args.slug, title=args.title, goal=args.goal,
        local=args.local, delegate=args.delegate, registry=args.registry,
    ), answers, ctx)


def main(
    argv: list[str],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    env: dict[str, str] | None = None,
    read: Callable[[str], str] = input,
) -> int:
    args = build_parser().parse_args(argv)
    mode = detect_mode(args.non_interactive, stdin=stdin, stdout=stdout, env=env)
    out = stdout or sys.stdout
    as_json = args.json or not mode.interactive
    action = "list" if getattr(args, "list", False) else args.verb
    agent_id = getattr(args, "agent_id", None) or _default_agent_id()
    ctx = Ctx(mode=mode, agent_id=agent_id)
    if mode.interactive:
        ctx.delegate = lambda endpoint, role, registry, user: delegate(
            mode, endpoint=endpoint, role=role, registry=registry, user=user,
        )
        from work_once import run_orchestrate

        ctx.run_orchestrate = run_orchestrate
        if not as_json:
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
