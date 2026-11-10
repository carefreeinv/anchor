#!/usr/bin/env python3
"""Transport-neutral operations for ``anchor plans | work | review | draft``.

The CLI and (later) the MCP server are adapters over this module. Workflow
rules stay in ``plan_store`` / ``plan_select`` / ``plan_lease`` / ``work_once`` /
``merge_feature``; handlers call those modules and never re-derive them.

Adapters supply an ``Answers`` port and a ``Ctx``. Headless and MCP adapters
pass an ``Answers`` that never answers and omit ``ctx.delegate``.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TextIO

import plan_finish_gate
import plan_lease
import plan_store

SCHEMA_VERSION = 1
VERBS = ("plans", "work", "review", "draft", "fleet-watch", "models", "release")

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_ERROR = 2
EXIT_NEEDS_OPERATOR = 3

NEEDS_MODEL = "model"
NEEDS_OPERATOR = "operator"
NEEDS_HARNESS = "harness"

REVIEW_CHOICES = ("approve", "needs-work", "skip", "defer")
READY_LANES = ("bugs", "features")
MYTHOS_CORE = "anchor/system-prompts/mythos-core.md"

DelegateFn = Callable[[str, str, str | None, str], tuple[str, str]]
RunOrchFn = Callable[[Path, list[str]], int]
DisplayFn = Callable[[str], None]


# --- mode ----------------------------------------------------------------------


@dataclass(frozen=True)
class Mode:
    interactive: bool
    reason: str

    @property
    def name(self) -> str:
        return "interactive" if self.interactive else "non-interactive"


def detect_mode(
    flag: bool,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    env: dict[str, str] | None = None,
) -> Mode:
    """Interactive only when nothing says otherwise and both ends are a TTY."""
    env = os.environ if env is None else env
    if flag:
        return Mode(False, "--non-interactive")
    if env.get("ANCHOR_NONINTERACTIVE", "") not in ("", "0"):
        return Mode(False, "ANCHOR_NONINTERACTIVE")
    try:
        tty_in = bool((stdin or sys.stdin).isatty())
        tty_out = bool((stdout or sys.stdout).isatty())
    except (AttributeError, ValueError, OSError):
        return Mode(False, "stdio not inspectable")
    if not tty_in:
        return Mode(False, "stdin is not a terminal")
    if not tty_out:
        return Mode(False, "stdout is not a terminal")
    return Mode(True, "terminal")


# --- errors / result / ports ---------------------------------------------------


class NeedsOperator(Exception):
    """A step needs a human answer that this run cannot get."""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__(detail)
        self.step = step
        self.detail = detail


class CliError(Exception):
    """A usage or hard error: exit 2 with this message."""


class NotDelegated(Exception):
    """Delegation did not happen; the message says why (never a silent skip)."""


class Passthrough(Exception):
    """A verb handed the whole run to an existing script; carry its exit code."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Result:
    verb: str
    action: str
    exit_code: int = EXIT_OK
    data: dict[str, Any] = field(default_factory=dict)
    pending: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def need(self, step: str, needs: str, detail: str) -> None:
        self.pending.append({"step": step, "needs": needs, "detail": detail})

    def to_json(self, mode: Mode) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "verb": self.verb,
            "action": self.action,
            "mode": mode.name,
            "exit_code": self.exit_code,
            "ok": self.exit_code == EXIT_OK,
            "result": self.data,
            "pending": self.pending,
            "notes": self.notes,
            "error": self.error,
        }


def next_command(argv: str, purpose: str) -> str:
    """One copy-pasteable TTY/JSON hint: ``Run `argv` to purpose.``"""
    return f"Run `{argv.strip()}` to {purpose.rstrip('.')}."


class Answers(Protocol):
    """The only way an operation may ask anything. Headless implementations raise."""

    def choose(self, step: str, question: str, choices: tuple[str, ...]) -> str: ...
    def text(self, step: str, question: str) -> str: ...


@dataclass
class NeverAnswers:
    """MCP / test adapter: every question is ``NeedsOperator``."""

    def choose(self, step: str, question: str, choices: tuple[str, ...]) -> str:
        raise NeedsOperator(step, f"{question} ({' | '.join(choices)})")

    def text(self, step: str, question: str) -> str:
        raise NeedsOperator(step, question)


@dataclass
class Ctx:
    mode: Mode
    agent_id: str
    delegate: DelegateFn | None = None
    run_orchestrate: RunOrchFn | None = None
    display: DisplayFn | None = None


@dataclass(frozen=True)
class Operation:
    name: str
    verb: str
    action: str
    mutates: bool
    requires: str | None
    handler: Callable[[Any, Answers, Ctx], Result]


REGISTRY: dict[str, Operation] = {}


def _op(
    name: str, *, mutates: bool, requires: str | None,
) -> Callable[[Callable[..., Result]], Callable[..., Result]]:
    verb, _, action = name.partition(".")

    def wrap(fn: Callable[..., Result]) -> Callable[..., Result]:
        REGISTRY[name] = Operation(
            name=name, verb=verb, action=action, mutates=mutates,
            requires=requires, handler=fn,
        )
        return fn

    return wrap


def run(name: str, params: Any, answers: Answers, ctx: Ctx) -> Result:
    return REGISTRY[name].handler(params, answers, ctx)


def operations() -> list[Operation]:
    return list(REGISTRY.values())


# --- params --------------------------------------------------------------------


@dataclass(frozen=True)
class PlansListParams:
    root: str
    lanes: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PlansBoardParams:
    root: str
    as_json: bool = False


@dataclass(frozen=True)
class WorkListParams:
    root: str
    tier: str | None = None
    model: str | None = None
    effort: str | None = None
    endpoint: str | None = None
    registry: str | None = None


@dataclass(frozen=True)
class WorkClaimParams:
    root: str
    slug: str | None = None
    no_fit_check: bool = False
    no_dep_check: bool = False
    recover: bool = False
    run: bool = False
    no_finish: bool = False
    no_commit: bool = False
    tier: str | None = None
    model: str | None = None
    effort: str | None = None
    endpoint: str | None = None
    registry: str | None = None


@dataclass(frozen=True)
class WorkSlugParams:
    root: str
    slug: str


@dataclass(frozen=True)
class ModelsListParams:
    root: str
    registry: str | None = None


@dataclass(frozen=True)
class ModelsNickParams:
    root: str
    alias: str
    endpoint: str
    machine: str | None = None
    effort: str | None = None
    overlay: str | None = None
    registry: str | None = None


@dataclass(frozen=True)
class ReviewListParams:
    root: str
    suggest_promote: bool = False


@dataclass(frozen=True)
class ReviewPromoteParams:
    root: str


@dataclass(frozen=True)
class ReviewParams:
    root: str
    slug: str | None = None
    delegate: str | None = None
    registry: str | None = None
    no_delegate: bool = False


@dataclass(frozen=True)
class DraftListParams:
    root: str


@dataclass(frozen=True)
class DraftCreateParams:
    root: str
    slug: str
    title: str | None = None
    goal: str | None = None
    local: bool = True
    delegate: str | None = None
    registry: str | None = None


@dataclass(frozen=True)
class DraftPromoteParams:
    root: str
    slug: str
    to: str | None = None


@dataclass(frozen=True)
class ReleaseParams:
    root: str
    dry_run: bool = False
    yes: bool = False
    push: bool = False
    base: str | None = None
    since: float | None = 30.0
    all_pending: bool = False
    skip_review: bool = False
    force_omit_finished: bool = False
    force_tag: bool = False
    bump: str | None = None
    tag: str | None = None
    delegate: str | None = None
    registry: str | None = None
    no_delegate: bool = False


@dataclass(frozen=True)
class FleetWatchParams:
    """Inspect / emit / install per-project fleet daemons.

    Exposure: status, list, once, emit — CLI + MCP (harness). install —
    operator-only; never an MCP tool that writes systemd units. ``--yes`` is
    not an answer substitute: headless install returns needs_operator even
    with yes=True.
    """

    root: str
    workers: tuple[str, ...] = ()
    emit: str | None = None
    yes: bool = False
    triage: bool = False
    run: bool = False
    tier: str | None = None
    agent_id: str | None = None
    endpoint: str | None = None
    model: str | None = None
    registry: str | None = None
    python: str | None = None
    write_dir: str | None = None
    load_watcher: bool = False


# --- shared helpers ------------------------------------------------------------


def plans_root(root: str) -> Path:
    path = Path(root).expanduser().resolve()
    found = plan_store.discover_project_root(path)
    if found is None:
        raise CliError(f"no .plans/ tree under {path} (walked parents)")
    return plan_store.plans_root_for(found)


def _title(ref: plan_store.PlanRef) -> str:
    from plan_select import parse_title, strip_code_fences

    text, err = plan_store.read_text(ref)
    if err is not None or text is None:
        return ref.name
    return parse_title(strip_code_fences(text), ref.name)


def _one(plans: Path, lane: str, slug: str) -> plan_store.PlanRef:
    hits = plan_store.lookup(plans, lane, slug)
    if not hits:
        raise CliError(f"no plan {slug!r} in {lane}/")
    if len(hits) > 1:
        raise CliError(f"ambiguous slug {slug!r} in {lane}/: {', '.join(h.rel for h in hits)}")
    return hits[0]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    )


def commit_lane_move(root: str | Path, slug: str, lane: str, why: str) -> dict[str, Any]:
    """Light-path commit of a lane move. Never a bare ``git commit``.

    Outcomes: ``committed``, ``untracked``, ``refused-merge-in-progress``,
    ``refused-foreign-staged``.
    """
    root = Path(root).expanduser().resolve()
    msg = f"Plans: {slug} → {lane} ({why})"
    if _git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return {"outcome": "untracked", "message": msg}
    if _git(root, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0:
        return {"outcome": "refused-merge-in-progress", "message": msg}
    staged = [
        p for p in _git(root, "diff", "--cached", "--name-only").stdout.splitlines() if p
    ]
    foreign = [p for p in staged if p != ".plans" and not p.startswith(".plans/")]
    if foreign:
        return {
            "outcome": "refused-foreign-staged",
            "message": msg,
            "paths": foreign,
        }
    add = _git(root, "add", "--", ".plans/")
    if add.returncode != 0:
        return {"outcome": "untracked", "message": msg}
    cached = [
        p for p in _git(root, "diff", "--cached", "--name-only", "--", ".plans/").stdout.splitlines()
        if p
    ]
    if not cached:
        return {"outcome": "untracked", "message": msg}
    commit = _git(root, "commit", "-m", msg, "--", ".plans/")
    if commit.returncode != 0:
        raise CliError(
            f"plans-only commit failed: {(commit.stderr or commit.stdout).strip() or commit.returncode}"
        )
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    return {"outcome": "committed", "message": msg, "sha": sha}


def _record_lane_commit(res: Result, root: str, slug: str, lane: str, why: str) -> None:
    out = commit_lane_move(root, slug, lane, why)
    res.data["lane_commit"] = out
    outcome = out["outcome"]
    if outcome == "committed":
        return
    if outcome == "untracked":
        res.notes.append("lane move (untracked)")
        return
    res.notes.append(f"lane move not committed: {outcome}")


def _worker(params: WorkListParams | WorkClaimParams):
    from types import SimpleNamespace

    from work_once import resolve_worker

    return resolve_worker(SimpleNamespace(
        effort=params.effort, endpoint=params.endpoint, registry=params.registry,
        model=params.model, tier=params.tier, root=params.root,
    ))


def _try_delegate(ctx: Ctx, *, endpoint: str, role: str, registry: str | None, user: str) -> tuple[str, str]:
    if ctx.delegate is None:
        raise NotDelegated("no delegate hook on this transport")
    if not ctx.mode.interactive and role not in ("critic", "planner"):
        raise NotDelegated("non-interactive run: the calling agent does this step itself")
    return ctx.delegate(endpoint, role, registry, user)


# --- plans ---------------------------------------------------------------------


@_op("plans.list", mutates=False, requires=None)
def op_plans_list(params: PlansListParams, _answers: Answers, _ctx: Ctx) -> Result:
    plans = plans_root(params.root)
    lanes = list(params.lanes) if params.lanes else plan_store.lane_names(plans)
    res = Result("plans", "list")
    res.data["columns"] = ["rel", "lane", "slug", "title"]
    res.data["plans"] = [
        {"rel": r.rel, "lane": r.lane, "slug": r.slug, "title": _title(r)}
        for r in plan_store.list_lanes(plans, lanes)
    ]
    res.data["counts"] = {lane: plan_store.count(plans, lane) for lane in lanes}
    return res


@_op("plans.board", mutates=False, requires=None)
def op_plans_board(params: PlansBoardParams, _answers: Answers, ctx: Ctx) -> Result:
    import plan_board

    root = Path(params.root).resolve()
    plans = root / ".plans"
    argv = ["--project", str(root), "--once"]
    if not ctx.mode.interactive or params.as_json:
        if not plans.is_dir():
            res = Result("plans", "board", exit_code=EXIT_NOTHING)
            res.error = f"no .plans/ directory under {root}"
            return res
        payload = plan_board.board_status_payload(plans, root)
        res = Result("plans", "board")
        res.data["board"] = payload
        return res
    raise Passthrough(plan_board.main(argv))


# --- models --------------------------------------------------------------------


def _models_fleet(root: str, registry: str | None):
    from anchor_client import DEFAULT_REGISTRY, Fleet

    path = Path(registry) if registry else DEFAULT_REGISTRY
    return Fleet(path, overlay_root=Path(root), probe_health=False)


@_op("models.list", mutates=False, requires=None)
def op_models_list(params: ModelsListParams, _answers: Answers, _ctx: Ctx) -> Result:
    from anchor_client import RegistryConflict

    res = Result("models", "list")
    try:
        fleet = _models_fleet(params.root, params.registry)
    except RegistryConflict as exc:
        raise CliError(str(exc)) from exc
    res.data["columns"] = ["name", "aliases", "machine", "model", "effort", "tier"]
    res.data["endpoints"] = [
        {
            "name": ep.name,
            "aliases": list(ep.aliases),
            "machine": ep.machine,
            "model": ep.model,
            "effort": ep.effort,
            "tier": ep.tier,
        }
        for ep in fleet.endpoints
    ]
    return res


@_op("models.nick", mutates=True, requires=None)
def op_models_nick(params: ModelsNickParams, _answers: Answers, _ctx: Ctx) -> Result:
    from anchor_client import (
        DEFAULT_REGISTRY,
        RegistryConflict,
        overlay_paths,
        write_endpoint_nick,
    )

    root = Path(params.root)
    overlay = Path(params.overlay) if params.overlay else (
        Path(os.environ.get("ANCHOR_CONFIG_DIR") or (Path.home() / ".config/anchor"))
        / "endpoints.local.yaml"
    )
    shared = Path(params.registry) if params.registry else DEFAULT_REGISTRY
    if overlay.resolve() == Path(shared).resolve():
        raise CliError("refusing to write nicknames into the shared registry")
    others = [p for p in overlay_paths(root) if p.resolve() != overlay.resolve()]
    res = Result("models", "nick")
    try:
        ep = write_endpoint_nick(
            overlay,
            alias=params.alias,
            endpoint=params.endpoint,
            machine=params.machine,
            effort=params.effort,
            registry_path=shared,
            overlays=others,
        )
    except RegistryConflict as exc:
        raise CliError(str(exc)) from exc
    res.data.update(
        overlay=str(overlay),
        name=ep.name,
        aliases=list(ep.aliases),
        machine=ep.machine,
        model=ep.model,
        effort=ep.effort,
    )
    res.notes.append(f"wrote {overlay}")
    return res


# --- work ----------------------------------------------------------------------


@_op("work.list", mutates=False, requires=None)
def op_work_list(params: WorkListParams, _answers: Answers, ctx: Ctx) -> Result:
    from plan_select import inventory

    plans = plans_root(params.root)
    res = Result("work", "list")
    records = inventory(plans, _worker(params), agent_id=ctx.agent_id)
    res.data["columns"] = [
        "rel", "lane", "priority", "value", "preferred", "fit", "deps", "assignee", "owner",
    ]
    res.data["plans"] = [
        {
            "rel": r.rel, "lane": r.lane, "slug": r.slug, "priority": r.priority,
            "value": r.value, "preferred": r.preferred, "fit": r.fit.value,
            "deps": "met" if r.deps_met else "UNMET:" + ",".join(r.deps_unmet),
            "deps_unmet": list(r.deps_unmet),
            "assignee": "ai" if r.agent_assignable else (r.assignee or "human"),
            "owner": r.owner,
        }
        for r in records
    ]
    if not records:
        res.exit_code = EXIT_NOTHING
    return res


@_op("work.heartbeat", mutates=True, requires=None)
def op_work_heartbeat(params: WorkSlugParams, _answers: Answers, ctx: Ctx) -> Result:
    plans = plans_root(params.root)
    lease = plan_lease.renew(plans, _one(plans, "in-progress", params.slug).rel, ctx.agent_id)
    res = Result("work", "heartbeat")
    res.data.update(plan=lease.plan_rel, agent_id=ctx.agent_id, expires_at=lease.expires_at)
    return res


@_op("work.finish", mutates=True, requires=None)
def op_work_finish(params: WorkSlugParams, _answers: Answers, ctx: Ctx) -> Result:
    plans = plans_root(params.root)
    rel = _one(plans, "in-progress", params.slug).rel
    lease = plan_lease.active_lease(plans, rel)
    if lease is None or lease.agent_id != ctx.agent_id:
        who = f"held by {lease.agent_id!r}" if lease else "has no active lease"
        raise plan_lease.ClaimError(
            f"{rel} {who}; only its lease holder may finish it"
        )
    plan_path = plans / rel
    evidence = plan_finish_gate.check_finish(params.root, plan_path)
    if not evidence.ok:
        raise plan_lease.ClaimError(
            f"empty-finish refused: {evidence.reason} "
            "(stay in-progress; operator exception in ## Handoff to override)"
        )
    dest = plan_lease.finish_to_review(plans, rel, ctx.agent_id)
    ref = plan_store.ref_for_path(plans, dest)
    res = Result("work", "finish")
    res.data.update(plan=ref.rel if ref else str(dest), agent_id=ctx.agent_id)
    finish_slug = ref.slug if ref else params.slug
    finish_title = _title(ref) if ref else finish_slug
    res.need(
        "review",
        NEEDS_OPERATOR,
        next_command(f"anchor review {finish_slug}", f"review {finish_title}"),
    )
    _record_lane_commit(
        res, params.root, ref.slug if ref else rel, "review-needed", "anchor work --finish",
    )
    return res


@_op("work.complete", mutates=True, requires=None)
def op_work_complete(params: WorkSlugParams, _answers: Answers, ctx: Ctx) -> Result:
    """Move in-progress → review-needed without the finish-gate (MCP alias)."""
    plans = plans_root(params.root)
    rel = _one(plans, "in-progress", params.slug).rel
    plan_lease._assert_owner_if_in_progress(plans, rel, ctx.agent_id)
    plan_lease.release(plans, rel, force=True)
    dest_rel, dest_path = plan_lease._move_file(plans, rel, "review-needed")
    res = Result("work", "complete")
    res.data.update(
        action="move_to_review_needed",
        plan_rel=dest_rel,
        path=str(dest_path),
        agent_id=ctx.agent_id,
    )
    res.need(
        "review",
        NEEDS_OPERATOR,
        next_command(f"anchor review {params.slug}", f"review {params.slug}"),
    )
    return res


@_op("work.return", mutates=True, requires=None)
def op_work_return(params: WorkSlugParams, _answers: Answers, ctx: Ctx) -> Result:
    plans = plans_root(params.root)
    rel = _one(plans, "in-progress", params.slug).rel
    dest = plan_lease.return_to_ready(plans, rel, agent_id=ctx.agent_id)
    ref = plan_store.ref_for_path(plans, dest)
    res = Result("work", "return")
    res.data.update(plan=ref.rel if ref else str(dest), agent_id=ctx.agent_id)
    if ref:
        _record_lane_commit(res, params.root, ref.slug, ref.lane, "anchor work --return")
    return res


@_op("work.claim", mutates=True, requires=NEEDS_MODEL)
def op_work_claim(params: WorkClaimParams, _answers: Answers, ctx: Ctx) -> Result:
    import argparse

    from work_once import pick_claim_one

    plans = plans_root(params.root)
    res = Result("work", "claim")
    if params.recover and params.slug:
        rec = _one(plans, "in-progress", params.slug)
        lease, dest = plan_lease.claim_and_move(
            plans, rec.rel, ctx.agent_id, recover=True,
        )
        res.data.update(
            plan=lease.plan_rel, path=str(dest), agent_id=ctx.agent_id,
        )
        return res
    ns = argparse.Namespace(
        slug=params.slug, path=None, no_fit_check=params.no_fit_check,
        no_dep_check=params.no_dep_check, recover=params.recover,
        allow_assigned=False, agent_id=ctx.agent_id,
        lease_ttl=plan_lease.DEFAULT_TTL_SECONDS,
    )
    try:
        dest = pick_claim_one(plans, _worker(params), ns)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    if dest is None:
        res.exit_code = EXIT_NOTHING
        res.notes.append("nothing claimed (see stderr for why)")
        return res
    ref = plan_store.ref_for_path(plans, dest)
    rel = ref.rel if ref else str(dest)
    res.data.update(plan=rel, path=str(dest), agent_id=ctx.agent_id)
    if ref:
        _record_lane_commit(res, params.root, ref.slug, "in-progress", "anchor work claim")
    slug = ref.slug if ref else params.slug or rel
    title = _title(ref) if ref else slug
    detail = next_command(
        f"anchor work --finish {slug}",
        f"park {title} in review-needed",
    )
    if params.run:
        if ctx.run_orchestrate is None:
            res.notes.append("execute skipped: no orchestrate hook on this transport")
            res.need("execute", NEEDS_MODEL, detail)
            return res
        from work_once import orchestrate_identity_args, orchestrate_worktree_args, plan_slug

        extra = orchestrate_identity_args(params)
        slug = (ref.slug if ref else None) or params.slug or plan_slug(dest)
        extra = extra + orchestrate_worktree_args(params.root, ctx.agent_id, slug)
        code = ctx.run_orchestrate(dest, extra)
        res.data["orchestrate_exit"] = code
        if code != 0:
            res.exit_code = EXIT_ERROR
            res.error = f"orchestrate.py exited {code}; plan stays in in-progress/"
            res.need(
                "execute",
                NEEDS_MODEL,
                next_command(f"anchor work {slug}", f"resume {title}"),
            )
            return res
        from commit_prep import after_run_success

        wt = None
        if "--worktree" in extra:
            i = extra.index("--worktree")
            if i + 1 < len(extra):
                wt = Path(extra[i + 1])
        prep = after_run_success(
            wt,
            slug,
            dest,
            no_commit=params.no_commit,
        )
        if not prep.ok:
            res.exit_code = EXIT_ERROR
            res.error = f"commit-prep red: {prep.error}; plan stays in in-progress/"
            res.need(
                "execute",
                NEEDS_MODEL,
                next_command(f"anchor work {slug}", f"resume {title}"),
            )
            return res
        if prep.sha:
            res.data["commit"] = prep.sha
        if params.no_finish:
            res.notes.append("--no-finish: plan stays in in-progress/")
            res.need(
                "review",
                NEEDS_OPERATOR,
                next_command(
                    f"anchor work --finish {slug}",
                    f"park {title} in review-needed",
                ),
            )
            return res
        try:
            parked = plan_lease.finish_to_review(plans, rel, ctx.agent_id)
            parked_ref = plan_store.ref_for_path(plans, parked)
            res.data["plan"] = parked_ref.rel if parked_ref else str(parked)
            parked_slug = parked_ref.slug if parked_ref else slug
            parked_title = _title(parked_ref) if parked_ref else title
            res.need(
                "review",
                NEEDS_OPERATOR,
                next_command(
                    f"anchor review {parked_slug}",
                    f"review {parked_title}",
                ),
            )
            _record_lane_commit(
                res, params.root,
                parked_ref.slug if parked_ref else rel,
                "review-needed",
                "anchor work --run",
            )
        except plan_lease.ClaimError as exc:
            res.notes.append(f"auto-finish skipped: {exc}")
        return res
    res.need("execute", NEEDS_MODEL, detail)
    return res


# --- review --------------------------------------------------------------------


def _review_package(root: Path, slug: str) -> dict[str, Any]:
    import merge_feature as mf

    branch = f"feature/{slug}"
    pkg: dict[str, Any] = {"branch": None, "target": None, "head": None,
                           "fast_forward": None, "already_merged": None, "changed": [],
                           "remote_only": []}
    try:
        if branch not in mf.local_branches(root):
            pkg["remote_only"] = _remote_branches(root, branch)
            return pkg
        target = mf.resolve_target(root)
        head = mf.head_sha(root, branch)
        pkg.update(branch=branch, target=target or None, head=head)
        if target:
            base = mf.merge_base(root, target, branch)
            pkg["changed"] = list(mf.changed_files(root, base, head))
            pkg["fast_forward"] = mf.is_ancestor(root, target, branch)
            pkg["already_merged"] = mf.is_ancestor(root, branch, target)
    except (mf.GitError, OSError):
        pass
    return pkg


def _remote_branches(root: Path, branch: str) -> list[str]:
    import subprocess

    p = subprocess.run(
        ["git", "-C", str(root), "for-each-ref", "--format=%(refname:short)",
         f"refs/remotes/*/{branch}"],
        capture_output=True, text=True, check=False,
    )
    return [line for line in p.stdout.splitlines() if line.strip()] if p.returncode == 0 else []


def critic_verdict(text: str) -> str:
    """ACCEPT | REVISE | ESCALATE from a critic reply.

    ``## Verdict`` headings are the current verdict. Empty headings are
    skipped so a duplicated ``## Verdict`` / ``## Verdict ACCEPT`` pair
    (Lightning) is ACCEPT. Option lists and ``~~strike~~`` are ignored; of
    what remains in the **last non-empty** verdict section, the most
    cautious word wins (ESCALATE > REVISE > ACCEPT). If every verdict
    heading is empty, UNKNOWN — a prior-round ``verdict: ACCEPT`` outside
    those sections is not used. Without a heading, labeled ``Verdict:``
    lines (then any remaining word) are used the same way.
    """
    import re

    rank = {"ESCALATE": 3, "REVISE": 2, "ACCEPT": 1}
    cleaned = re.sub(r"~~[^~]*~~", " ", text)
    cleaned = re.sub(
        r"\bACCEPT(?:\s*\([^)]*\))?\s*\|\s*REVISE(?:\s*\([^)]*\))?\s*\|\s*ESCALATE"
        r"(?:\s*\([^)]*\))?",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    def _pick(words: set[str]) -> str:
        if not words:
            return "UNKNOWN"
        return max(words, key=lambda w: rank[w])

    def _words(blob: str) -> set[str]:
        return {
            w.upper()
            for w in re.findall(r"\b(ACCEPT|REVISE|ESCALATE)\b", blob, re.IGNORECASE)
        }

    heading_re = re.compile(
        r"^##[^\n]*\bverdict\b[^\n]*",
        re.IGNORECASE | re.MULTILINE,
    )
    last_nonempty: set[str] | None = None
    had_heading = False
    matches = list(heading_re.finditer(cleaned))
    for i, m in enumerate(matches):
        had_heading = True
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        nxt_h = re.search(r"^##\s", cleaned[m.end():end], re.MULTILINE)
        stop = m.end() + nxt_h.start() if nxt_h else end
        words = _words(cleaned[m.start():stop])
        if words:
            last_nonempty = words
    if had_heading:
        return _pick(last_nonempty or set())
    labeled = {
        m.group(1).upper()
        for m in re.finditer(r"verdict\W{0,12}(ACCEPT|REVISE|ESCALATE)", cleaned, re.IGNORECASE)
    }
    if labeled:
        return _pick(labeled)
    return _pick(_words(cleaned))


def _promote_hint(root: str) -> tuple[str, str, int] | None:
    import pending_merges

    try:
        return pending_merges.promotion_ahead(root)
    except pending_merges.GitError:
        return None


@_op("review.list", mutates=False, requires=None)
def op_review_list(params: ReviewListParams, _answers: Answers, _ctx: Ctx) -> Result:
    import pending_merges

    plans = plans_root(params.root)
    refs = plan_store.list_lane(plans, "review-needed")
    res = Result("review", "list")
    res.data["columns"] = ["rel", "slug", "title", "held"]
    res.data["plans"] = [
        {"rel": r.rel, "slug": r.slug, "title": _title(r),
         "held": pending_merges.is_held(r.path)}
        for r in refs
    ]
    if refs:
        return res
    promo = _promote_hint(params.root) if params.suggest_promote else None
    if promo:
        integ, main, n = promo
        res.exit_code = EXIT_ERROR
        res.error = (
            f"nothing in review-needed/; {integ} is {n} commit(s) ahead of {main}. "
            f"Run `anchor review --promote` to promote {integ} → {main}."
        )
        res.data["promote"] = {
            "integration": integ, "mainline": main, "ahead": n,
        }
        return res
    res.exit_code = EXIT_NOTHING
    return res


@_op("review.promote", mutates=False, requires=NEEDS_OPERATOR)
def op_review_promote(params: ReviewPromoteParams, answers: Answers, _ctx: Ctx) -> Result:
    """Empty-queue promotion: integration → mainline. Does not merge headless."""
    res = Result("review", "promote")
    promo = _promote_hint(params.root)
    if not promo:
        res.exit_code = EXIT_NOTHING
        res.error = (
            "nothing to promote: integration is not ahead of mainline "
            "(or this is not a git repo with both branches)"
        )
        return res
    integ, main, n = promo
    res.data["promote"] = {
        "integration": integ, "mainline": main, "ahead": n,
    }
    choice = answers.choose(
        "promote-decision",
        f"Promote {integ} → {main} ({n} commit(s) ahead)?",
        ("promote", "skip"),
    )
    res.data["decision"] = choice
    if choice != "promote":
        res.notes.append("not promoted; branches unchanged")
        return res
    res.need(
        "promote-merge",
        NEEDS_OPERATOR,
        f"merge {integ} → {main} (fast-forward preferred); "
        f"git checkout {main} && git merge --ff-only {integ}",
    )
    return res


def pick_review_slug(plans: Path) -> str | None:
    """Highest-priority review-needed slug (Priority → Value → oldest mtime)."""
    from plan_select import parse_priority, parse_value

    refs = plan_store.list_lane(plans, "review-needed")
    if not refs:
        return None
    pri = {"P1": 0, "P2": 1, "P3": 2}
    val = {"high": 0, "medium": 1, "low": 2}

    def key(ref):
        text = ref.path.read_text(encoding="utf-8")
        return (
            pri.get(parse_priority(text), 1),
            val.get(parse_value(text), 1),
            ref.path.stat().st_mtime,
            ref.path.name,
        )

    return min(refs, key=key).slug


def kebab_slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:72] or "draft")


@_op("review.review", mutates=True, requires=NEEDS_OPERATOR)
def op_review(params: ReviewParams, answers: Answers, ctx: Ctx) -> Result:
    plans = plans_root(params.root)
    root = plans.parent
    slug = params.slug or pick_review_slug(plans)
    if not slug:
        raise CliError("nothing in review-needed/")
    ref = _one(plans, "review-needed", slug)
    res = Result("review", "review")
    pkg = _review_package(root, ref.slug)
    res.data.update(plan=ref.rel, title=_title(ref), **pkg)

    if params.no_delegate:
        res.need("critic", NEEDS_MODEL,
                 "AI critic pass over the plan's Done when and the branch diff")
        res.notes.append("critic not delegated: MCP prepare-only")
    else:
        _critic(params, ctx, ref, pkg, root, res)

    try:
        return _decide(res, answers, root, plans, ref, pkg)
    except NeedsOperator as exc:
        res.exit_code = EXIT_NEEDS_OPERATOR
        res.need(exc.step, NEEDS_OPERATOR, exc.detail)
        return res


def _decide(res: Result, answers: Answers, root: Path, plans: Path, ref, pkg) -> Result:
    choice = answers.choose("review-decision", f"Decision for {ref.rel}", REVIEW_CHOICES)
    res.data["decision"] = choice
    res.pending = [p for p in res.pending if p["step"] != "critic"]
    if choice == "skip":
        return res
    if choice == "approve":
        verdict = (res.data.get("critic") or {}).get("verdict")
        if verdict in ("REVISE", "ESCALATE", "UNKNOWN"):
            sure = answers.choose(
                "approve-despite-critic",
                f"The critic's verdict is {verdict}. Approve despite critic concerns?",
                ("yes", "no"),
            )
            if sure != "yes":
                res.data["decision"] = "skip"
                res.notes.append("not approved: critic concerns stand; plan left in review-needed/")
                return res
        return _approve(res, root, plans, ref, pkg)
    if choice == "needs-work":
        lane = answers.choose("needs-work-lane", "Return it as", READY_LANES)
        notes = answers.text("needs-work-notes", "Actionable notes (required)")
        _append_section(ref, "Review notes", notes)
        new = plan_store.move(plans, ref.rel, lane)
        res.data["moved_to"] = new.rel
        _record_lane_commit(res, str(root), ref.slug, lane, "anchor review needs-work")
        return res
    blocker = answers.text("defer-blocker", "What blocks it (required)")
    _append_section(ref, "Blocked", blocker)
    new = plan_store.move(plans, ref.rel, "blocked")
    res.data["moved_to"] = new.rel
    _record_lane_commit(res, str(root), ref.slug, "blocked", "anchor review defer")
    return res


CRITIC_DIFF_CHUNK = 8000
CRITIC_VERIFY_CAP = 2000
CRITIC_PRIOR_CAP = 2500
CRITIC_PYTEST_TIMEOUT = 60.0


def diff_chunks(diff: str, limit: int = CRITIC_DIFF_CHUNK) -> list[str]:
    """Split a unified diff into bounded pieces, preferring file boundaries.

    A 60k dump plus mythos-core overflows Lightning's completion budget
    (empty body, finish_reason=length). File-sized chunks keep each critic
    call inside a 30B window; a single oversized file is hard-sliced.
    """
    if not diff:
        return [""]
    if len(diff) <= limit:
        return [diff]
    parts = re.split(r"(?m)(?=^diff --git )", diff if diff.endswith("\n") else diff + "\n")
    parts = [p for p in parts if p.strip()]
    chunks: list[str] = []
    buf = ""
    for part in parts:
        if buf and len(buf) + len(part) > limit:
            chunks.append(buf)
            buf = part
        else:
            buf += part
    if buf:
        chunks.append(buf)
    out: list[str] = []
    for chunk in chunks:
        if len(chunk) <= limit:
            out.append(chunk)
            continue
        for i in range(0, len(chunk), limit):
            out.append(chunk[i : i + limit])
    return out or [""]


def critic_changed_stat(root: Path, target: str, head: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(root), "diff", "--stat", f"{target}...{head}"],
        capture_output=True, text=True, check=False,
    )
    return (p.stdout or p.stderr or "").strip() or "(empty)"


def critic_docs_sync(root: Path, timeout: float = 30.0) -> str:
    script = Path(root) / "scripts" / "check_docs_sync.py"
    if not script.is_file():
        return "check_docs_sync.py: not present in this project (skipped)"
    try:
        p = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(root), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"check_docs_sync.py: {exc}"
    body = ((p.stdout or "") + (p.stderr or "")).strip()
    if len(body) > CRITIC_VERIFY_CAP:
        body = body[:CRITIC_VERIFY_CAP] + "\n…"
    return f"check_docs_sync.py exit {p.returncode}\n{body}"


_OPS_TRANSPORT_TEST = "tests/test_anchor_ops_transport.py"


def critic_pytest_paths(
    pkg: dict[str, Any], root: Path | None = None,
) -> list[str]:
    """``tests/*.py`` paths from the review range (posix, no pycache).

    A change to ``scripts/anchor_ops.py`` also schedules the ops transport
    sweep when that test file exists on disk (new ``@_op`` names live there).
    """
    out: list[str] = []
    seen: set[str] = set()
    ops_touched = False
    for rel in pkg.get("changed") or []:
        n = str(rel).replace("\\", "/")
        if n == "scripts/anchor_ops.py":
            ops_touched = True
        if not n.startswith("tests/") or not n.endswith(".py"):
            continue
        if "/__pycache__/" in n or n in seen:
            continue
        seen.add(n)
        out.append(n)
    if ops_touched and _OPS_TRANSPORT_TEST not in seen:
        if root is not None and (Path(root) / _OPS_TRANSPORT_TEST).is_file():
            out.append(_OPS_TRANSPORT_TEST)
    return out


def critic_pytest_touched(
    root: Path, pkg: dict[str, Any], timeout: float = CRITIC_PYTEST_TIMEOUT,
) -> str:
    """Scoped pytest on tests/ files in ``pkg['changed']``.

    Timeout is reported in VERIFICATION; it is not a Done-when REVISE
    (last-slice instruct REVISEs on pytest exit non-zero only).
    """
    paths = critic_pytest_paths(pkg, root)
    if not paths:
        return "pytest skipped (no tests/ in range)"
    listed = ", ".join(paths)
    try:
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=line", *paths],
            cwd=str(root), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            f"pytest TIMEOUT after {int(timeout)}s ({listed}) — evidence "
            "only; do not REVISE solely for TIMEOUT"
        )
    except OSError as exc:
        return f"pytest: {exc}"
    body = ((p.stdout or "") + (p.stderr or "")).strip()
    if len(body) > CRITIC_VERIFY_CAP:
        body = body[:CRITIC_VERIFY_CAP] + "\n…"
    return f"pytest exit {p.returncode} ({listed})\n{body}"


# NVIDIA Build prepended onto a non-empty LAN `found` list (the false-ACCEPT
# fleet-order defect). Append-only `if not found: found.append(fb)` is fine.
_PREPEND_BUILD_RE = re.compile(
    r"found\s*=\s*\[\s*(?:fb|fallback)\s*,\s*\*\s*found\s*\]"
    r"|found\s*=\s*\[\s*(?:fb|fallback)\s*\]\s*\+\s*found"
)


_PICK_ORDER_SKIP_FILES = frozenset({
    "scripts/anchor_ops.py",
    "anchor_ops.py",
})


def _added_product_py_lines(diff: str):
    """Yield ``+`` body lines from non-test ``.py`` product files in a unified diff.

    Skips ``+++`` headers, ``tests/``, and the critic packaging module (its
    regex / prompt strings quote the prepend pattern without introducing it).
    """
    path = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            m = re.search(r" b/(.+)$", line)
            path = m.group(1) if m else ""
            continue
        if line.startswith("+++ "):
            rest = line[4:].strip()
            if rest.startswith("b/"):
                path = rest[2:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        norm = path.lstrip("./")
        if not norm.endswith(".py"):
            continue
        if norm.startswith("tests/") or "/tests/" in norm:
            continue
        base = norm.rsplit("/", 1)[-1]
        if norm in _PICK_ORDER_SKIP_FILES or base in _PICK_ORDER_SKIP_FILES:
            continue
        yield line[1:]


def critic_pick_order_note(diff: str) -> str | None:
    """Flag invented executor order: Build prepended while LAN `found` is kept."""
    if not diff:
        return None
    if not any(_PREPEND_BUILD_RE.search(ln) for ln in _added_product_py_lines(diff)):
        return None
    return (
        "PICK-ORDER: DIFF prepends NVIDIA Build onto a non-empty `found` list "
        "(`found = [fb, *found]`). Fleet.pick uses Build only when the LAN "
        "executor list is empty (append). This is a Done-when failure — REVISE."
    )


def critic_verification_block(root: Path, pkg: dict[str, Any], diff: str) -> str:
    """Evidence the review template asks for — missing logs were a false REVISE."""
    parts: list[str] = []
    head, target = pkg.get("head"), pkg.get("target")
    if head and target:
        parts.append(
            "CHANGED FILES (full range, not this chunk):\n"
            + critic_changed_stat(Path(root), str(target), str(head))
        )
    parts.append(critic_docs_sync(Path(root)))
    parts.append(critic_pytest_touched(Path(root), pkg))
    pick = critic_pick_order_note(diff)
    if pick:
        parts.append(pick)
    return "\n\n".join(parts)


CRITIC_PICK_ORDER = (
    "Pick-order: Fleet.executor_candidates must match Fleet.pick — NVIDIA Build "
    "only when the LAN executor list is empty (append, never prepend). "
    "`found = [fb, *found]` with a non-empty LAN list is a defect; note it in "
    "this slice (last slice: REVISE)."
)


def critic_instruct(index: int, total: int, *, last: bool) -> str:
    base = (
        "You are the critic. Review only; do not fix. Judge whether the "
        "Done when items hold. " + CRITIC_PICK_ORDER
    )
    if not last:
        return (
            f"{base} This is diff chunk {index}/{total}. List defects in THIS "
            "slice only. Write 'no defects in this slice' if none. Do not emit "
            "a Verdict. Do not mark Done when as failed because other files are "
            "in later slices."
        )
    return (
        f"{base} This is the last diff chunk ({index}/{total}). Emit the full "
        "review template and one ## Verdict for the WHOLE plan, using PLAN + "
        "VERIFICATION + CHANGED FILES + earlier slice notes + this DIFF. "
        "Do not REVISE because: this slice is tests or docs only; a Changed "
        "File is absent from this DIFF; an earlier slice said Partial/Pending; "
        "or verification was not pasted into the DIFF hunks. REVISE if "
        "VERIFICATION shows pytest exit non-zero. A pytest TIMEOUT is "
        "evidence, not a Done-when failure — do not REVISE solely for "
        "TIMEOUT. Do not ACCEPT solely because docs-sync is OK (or skipped). "
        "REVISE for a PICK-ORDER note in VERIFICATION. REVISE only for a "
        "concrete Done-when failure with evidence."
    )


def build_critic_user(
    *,
    instruct: str,
    template: str,
    plan_body: str,
    verification: str,
    prior: str,
    chunk: str,
) -> str:
    return (
        f"{instruct}\n\nTEMPLATE:\n{template}\n\nPLAN:\n{plan_body}\n\n"
        f"VERIFICATION:\n{verification}\n{prior}\n\nDIFF:\n{chunk}"
    )


def _critic(params: ReviewParams, ctx: Ctx, ref, pkg, root: Path, res: Result) -> None:
    text, _err = plan_store.read_text(ref)
    diff = ""
    if pkg.get("head") and pkg.get("target"):
        p = subprocess.run(
            ["git", "-C", str(root), "diff", f"{pkg['target']}...{pkg['head']}"],
            capture_output=True, text=True, check=False,
        )
        diff = p.stdout
    try:
        import anchor_client

        template = anchor_client.load_prompt("anchor/templates/review.md")
    except (ImportError, OSError):
        template = ""
    plan_body = (text or "")[:8000]
    verification = critic_verification_block(root, pkg, diff)
    chunks = diff_chunks(diff)
    pieces: list[str] = []
    name = params.delegate or "auto"
    try:
        for i, chunk in enumerate(chunks, 1):
            last = i == len(chunks)
            prior = ""
            if pieces:
                joined = "\n---\n".join(pieces[-3:])
                if len(joined) > CRITIC_PRIOR_CAP:
                    joined = joined[:CRITIC_PRIOR_CAP] + "\n…"
                prior = (
                    "\n\nEARLIER SLICE NOTES (not a verdict; defects in those "
                    "slices only):\n" + joined
                )
            user = build_critic_user(
                instruct=critic_instruct(i, len(chunks), last=last),
                template=template,
                plan_body=plan_body,
                verification=verification,
                prior=prior,
                chunk=chunk,
            )
            name, out = _try_delegate(
                ctx, endpoint=params.delegate or "auto", role="critic",
                registry=params.registry, user=user,
            )
            pieces.append(out)
    except NotDelegated as exc:
        res.notes.append(f"critic not delegated: {exc}")
        res.need("critic", NEEDS_MODEL,
                 "AI critic pass over the plan's Done when and the branch diff")
        return
    out = pieces[-1] if pieces else ""
    if len(pieces) > 1:
        out = "\n\n".join(
            [f"## Chunk {i}\n{p}" for i, p in enumerate(pieces, 1)]
        )
    res.data["critic"] = {
        "endpoint": name,
        "verdict": critic_verdict(pieces[-1] if pieces else ""),
        "text": out,
        "chunks": len(pieces),
    }
    if ctx.display is not None:
        ctx.display(f"--- critic ({name}) ---\n{out}\n---")


def _approve(res: Result, root: Path, plans: Path, ref, pkg: dict[str, Any]) -> Result:
    import merge_feature as mf

    if pkg.get("remote_only"):
        res.exit_code = EXIT_NEEDS_OPERATOR
        res.need(
            "local-branch", NEEDS_OPERATOR,
            f"feature/{ref.slug} exists only as {', '.join(pkg['remote_only'])}: "
            f"check it out locally (git switch feature/{ref.slug}) and re-run — "
            "approving now would archive the plan without merging it",
        )
        return res
    if pkg["branch"] and not pkg["already_merged"]:
        not_ff = (
            f"{pkg['branch']} is not a fast-forward of {pkg['target']}: a merge commit "
            f"needs /commit-prep on the merged tree — finish with /review {ref.slug}"
        )
        if not pkg["fast_forward"]:
            res.exit_code = EXIT_NEEDS_OPERATOR
            res.need("merge-commit", NEEDS_HARNESS, not_ff)
            return res
        verdict, outcome = mf.run(
            root, ref.slug, tuple(pkg["changed"]),
            expect_head=pkg["head"], target=pkg["target"], title=res.data.get("title", ""),
            ff_only=True,
        )
        res.data["merge"] = {"ok": verdict.ok, "reason": verdict.reason,
                             "message": verdict.message, "outcome": outcome}
        if verdict.reason == "not-fast-forward" or outcome == mf.NOT_FAST_FORWARD:
            res.exit_code = EXIT_NEEDS_OPERATOR
            res.need("merge-commit", NEEDS_HARNESS, not_ff)
            return res
        if not verdict.ok or outcome is None:
            res.exit_code = EXIT_ERROR
            res.error = f"merge refused: {verdict.message}"
            return res
    new = plan_store.move(plans, ref.rel, "completed")
    res.data["moved_to"] = new.rel
    _record_lane_commit(res, str(root), ref.slug, "completed", "anchor review approve")
    return res


def _append_section(ref: plan_store.PlanRef, heading: str, body: str) -> None:
    text, err = plan_store.read_text(ref)
    if err is not None or text is None:
        raise CliError(f"cannot read {ref.rel}: {err}")
    ref.path.write_text(text.rstrip("\n") + f"\n\n## {heading}\n{body}\n", encoding="utf-8")


# --- draft ---------------------------------------------------------------------

DRAFT_SKELETON = """# Plan: {title}

- **Value:** medium
- **Priority:** P2
- **Slug:** {slug}
- **Preferred models:** mid
- **Assignee:** ai
- **Depends on:** none

## Goal
{goal}

## Steps
| # | Task | Touches | Verify by | Route to |
|---|------|---------|-----------|----------|
| 1 | TODO | | | |

## Done when
- TODO
"""

REQUIRED_SECTIONS = ("## Goal", "## Steps", "## Done when")


@_op("draft.list", mutates=False, requires=None)
def op_draft_list(params: DraftListParams, _answers: Answers, _ctx: Ctx) -> Result:
    plans = plans_root(params.root)
    res = Result("draft", "list")
    res.data["columns"] = ["rel", "slug", "title"]
    res.data["plans"] = [
        {"rel": r.rel, "slug": r.slug, "title": _title(r)}
        for r in plan_store.list_lane(plans, "drafts")
    ]
    if not res.data["plans"]:
        res.exit_code = EXIT_NOTHING
    return res


@_op("draft.create", mutates=True, requires=NEEDS_MODEL)
def op_draft_create(params: DraftCreateParams, _answers: Answers, ctx: Ctx) -> Result:
    plans = plans_root(params.root)
    taken = plan_store.find_slug(plans, params.slug, dated=False)
    if taken:
        raise CliError(f"slug {params.slug!r} already used: {', '.join(r.rel for r in taken)}")
    goal = params.goal or "TODO — the outcome, in one paragraph."
    text = DRAFT_SKELETON.format(title=params.title or params.slug, slug=params.slug, goal=goal)
    res = Result("draft", "create")
    prose_step = "write the plan's Goal, Steps and Done when (template: anchor/templates/plan.md)"

    if params.delegate:
        text = _delegated_draft(params, ctx, text, res) or text
    else:
        res.need("plan-prose", NEEDS_MODEL, prose_step)

    ref = plan_store.create(plans, "drafts", params.slug, text, local=params.local)
    res.data.update(plan=ref.rel, path=str(ref.path))
    res.need(
        "promote",
        NEEDS_OPERATOR,
        next_command(
            f"anchor draft --promote {params.slug}",
            f"promote {params.title or params.slug}",
        ),
    )
    return res


@_op("draft.promote", mutates=True, requires=NEEDS_OPERATOR)
def op_draft_promote(params: DraftPromoteParams, answers: Answers, _ctx: Ctx) -> Result:
    plans = plans_root(params.root)
    ref = _one(plans, "drafts", params.slug)
    lane = params.to or answers.choose("promote-lane", f"Promote {ref.rel} to", READY_LANES)
    new = plan_store.move(plans, ref.rel, lane)
    res = Result("draft", "promote")
    res.data.update(plan=new.rel)
    _record_lane_commit(res, params.root, ref.slug, lane, "anchor draft --promote")
    res.need(
        "execute",
        NEEDS_MODEL,
        next_command(f"anchor work {new.slug}", f"work {_title(new)}"),
    )
    return res


def _delegated_draft(params: DraftCreateParams, ctx: Ctx, skeleton: str, res: Result) -> str | None:
    try:
        import anchor_client

        template = anchor_client.load_prompt("anchor/templates/plan.md")
    except (ImportError, OSError):
        template = ""
    user = (
        "Write ONE complete plan file following this template. Output only the "
        f"markdown.\n\nTEMPLATE:\n{template}\n\nSTARTING POINT:\n{skeleton}"
    )
    try:
        name, out = _try_delegate(ctx, endpoint=params.delegate or "auto", role="planner",
                                  registry=params.registry, user=user)
    except NotDelegated as exc:
        res.notes.append(f"plan prose not delegated: {exc}")
        res.need("plan-prose", NEEDS_MODEL, "write the plan's Goal, Steps and Done when")
        return None
    missing = [s for s in REQUIRED_SECTIONS if s not in out]
    if missing:
        res.notes.append(f"{name} draft rejected (missing {', '.join(missing)}); kept skeleton")
        res.need("plan-prose", NEEDS_MODEL, "write the plan's Goal, Steps and Done when")
        return None
    res.data["delegated_to"] = name
    return out.strip() + "\n"


# --- fleet-watch ---------------------------------------------------------------


def _fw_scripts():
    import fleet_watch as fw

    return fw, Path(fw.SCRIPTS_DIR)


@_op("fleet-watch.status", mutates=False, requires=None)
def op_fleet_watch_status(params: FleetWatchParams, _answers: Answers, _ctx: Ctx) -> Result:
    import io

    fw, scripts = _fw_scripts()
    buf = io.StringIO()
    with _redirect_stdout(buf):
        code = fw.cmd_status(Path(params.root), scripts)
    res = Result("fleet-watch", "status", exit_code=code)
    res.data["output"] = buf.getvalue()
    return res


@_op("fleet-watch.list", mutates=False, requires=None)
def op_fleet_watch_list(params: FleetWatchParams, _answers: Answers, _ctx: Ctx) -> Result:
    return _fw_list_or_once(params, mode="list")


@_op("fleet-watch.once", mutates=True, requires=NEEDS_HARNESS)
def op_fleet_watch_once(params: FleetWatchParams, _answers: Answers, _ctx: Ctx) -> Result:
    return _fw_list_or_once(params, mode="triage" if params.triage else "once")


def _fw_emit_payload(params: FleetWatchParams):
    fw, scripts = _fw_scripts()
    if not params.workers:
        raise CliError("--emit / --write-dir needs at least one --worker")
    workers = [fw.parse_worker(w) for w in params.workers]
    project = Path(params.root)
    python = params.python or fw.DEFAULT_PYTHON
    files = fw.emit_systemd(
        project, scripts, workers, python=python, load_watcher=params.load_watcher,
    )
    emit = params.emit
    cron: list[str] = []
    if emit in ("cron", "both"):
        cron = fw.emit_cron_lines(
            project, scripts, workers, python=python, load_watcher=params.load_watcher,
        )
    text = fw.format_emit_text(files, cron, emit)
    return fw, files, cron, text


@_op("fleet-watch.emit", mutates=False, requires=NEEDS_HARNESS)
def op_fleet_watch_emit(params: FleetWatchParams, _answers: Answers, _ctx: Ctx) -> Result:
    _fw, files, cron, text = _fw_emit_payload(params)
    res = Result("fleet-watch", "emit")
    if params.emit in ("systemd", "both"):
        res.data["units"] = [{"name": n, "content": c} for n, c in files]
    if cron:
        res.data["cron"] = cron
    res.data["text"] = text
    return res


@_op("fleet-watch.write", mutates=True, requires=NEEDS_OPERATOR)
def op_fleet_watch_write(params: FleetWatchParams, _answers: Answers, ctx: Ctx) -> Result:
    if not ctx.mode.interactive:
        res = Result("fleet-watch", "write", exit_code=EXIT_NEEDS_OPERATOR)
        res.need(
            "write-dir",
            NEEDS_OPERATOR,
            "writing unit files to --write-dir needs an interactive operator",
        )
        return res
    if not params.write_dir:
        raise CliError("--write-dir needs a directory")
    _fw, files, _cron, _text = _fw_emit_payload(params)
    out = Path(params.write_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in files:
        dest = out / name
        dest.write_text(content, encoding="utf-8")
        written.append(str(dest))
    res = Result("fleet-watch", "write")
    res.data["written"] = written
    return res


@_op("fleet-watch.install", mutates=True, requires=NEEDS_OPERATOR)
def op_fleet_watch_install(params: FleetWatchParams, answers: Answers, ctx: Ctx) -> Result:
    if not ctx.mode.interactive:
        res = Result("fleet-watch", "install", exit_code=EXIT_NEEDS_OPERATOR)
        res.need(
            "install-user",
            NEEDS_OPERATOR,
            "writing systemd user units needs an interactive operator ( --yes is not a substitute )",
        )
        return res
    if not params.workers:
        raise CliError("--install-user needs at least one --worker")
    if not params.yes:
        choice = answers.choose(
            "install-user",
            "Write and enable systemd user units for this project?",
            ("yes", "no"),
        )
        if choice != "yes":
            raise CliError("install cancelled")
    fw, scripts = _fw_scripts()
    workers = [fw.parse_worker(w) for w in params.workers]
    python = params.python or fw.DEFAULT_PYTHON
    files = fw.emit_systemd(
        Path(params.root), scripts, workers, python=python,
        load_watcher=params.load_watcher,
    )
    code = fw.install_user_units(files, yes=True)
    res = Result("fleet-watch", "install", exit_code=code)
    res.data["units"] = [n for n, _ in files]
    return res


def _fw_list_or_once(params: FleetWatchParams, *, mode: str) -> Result:
    import argparse
    import io

    if not params.tier and not params.endpoint:
        raise CliError(f"--{mode} needs --tier or --endpoint")
    fw, scripts = _fw_scripts()
    ns = argparse.Namespace(
        tier=params.tier,
        agent_id=params.agent_id,
        endpoint=params.endpoint,
        model=params.model,
        registry=params.registry,
        run=params.run,
        python=params.python or fw.DEFAULT_PYTHON,
    )
    buf = io.StringIO()
    with _redirect_stdout(buf):
        code = fw.cmd_list_or_once(Path(params.root), scripts, ns, mode=mode)
    res = Result("fleet-watch", mode, exit_code=code)
    res.data["output"] = buf.getvalue()
    return res


def _redirect_stdout(buf):
    import contextlib

    return contextlib.redirect_stdout(buf)


_SEMVER_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _git_out(root: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    )
    if p.returncode != 0:
        raise CliError((p.stderr or p.stdout or "git failed").strip())
    return p.stdout.strip()


def _release_base(root: Path, override: str | None) -> str:
    import pending_merges as pm

    if override:
        return override
    branches = set(pm.local_branches(root))
    return (
        pm._first_existing(pm.INTEGRATION_ORDER, branches)
        or pm._first_existing(pm.MAINLINE_ORDER, branches)
        or "HEAD"
    )


def _last_semver_tag(root: Path) -> str | None:
    p = subprocess.run(
        ["git", "-C", str(root), "tag", "--sort=-v:refname"],
        capture_output=True, text=True, check=False,
    )
    if p.returncode != 0:
        return None
    for line in p.stdout.splitlines():
        if _SEMVER_TAG_RE.match(line.strip()):
            return line.strip()
    return None


def _bump_tag(last: str | None, level: str, *, v_prefix: bool) -> str:
    major = minor = patch = 0
    if last:
        m = _SEMVER_TAG_RE.match(last)
        if m:
            major, minor, patch = (int(x) for x in m.groups())
    if level == "major":
        major, minor, patch = major + 1, 0, 0
    elif level == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    body = f"{major}.{minor}.{patch}"
    return f"v{body}" if v_prefix else body


def _changelog_wants_minor(root: Path) -> bool:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        return False
    return bool(re.search(r"^### Added\s*$", m.group(1), re.M))


def _fold_changelog(root: Path, version: str) -> bool:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    bare = version.lstrip("v")
    from datetime import date
    today = date.today().isoformat()
    if re.search(rf"^## \[{re.escape(bare)}\]", text, re.M):
        return False
    repl = f"## [Unreleased]\n\n## [{bare}] - {today}"
    new, n = re.subn(r"^## \[Unreleased\]\s*$", repl, text, count=1, flags=re.M)
    if n != 1:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def _bump_pyproject(root: Path, version: str) -> bool:
    path = root / "pyproject.toml"
    if not path.is_file():
        return False
    bare = version.lstrip("v")
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"',
        f'version = "{bare}"',
        text,
        count=1,
    )
    if n != 1:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def _release_report_data(params: ReleaseParams) -> dict[str, Any]:
    import pending_merges as pm

    root = Path(params.root)
    try:
        base = _release_base(root, params.base)
    except pm.GitError as exc:
        raise CliError(str(exc)) from exc
    since = None if params.all_pending else params.since
    try:
        pending = pm.find_pending(root, since_days=since)
    except pm.GitError as exc:
        raise CliError(str(exc)) from exc
    rows = []
    finished_off = []
    for item in pending:
        lane = item.plan_lane
        rows.append({
            "branch": item.branch,
            "target": item.target,
            "ahead": item.ahead,
            "plan_lane": lane,
            "plan_slug": item.plan_slug,
            "completed_plan": item.completed_plan,
        })
        if lane in ("completed", "review-needed") or item.completed_plan:
            finished_off.append(item.branch)
    last = _last_semver_tag(root)
    v_prefix = (last or "v0.0.0").startswith("v")
    level = params.bump or ("minor" if _changelog_wants_minor(root) else "patch")
    suggested = params.tag or _bump_tag(last, level, v_prefix=v_prefix)
    membership: list[str] = []
    try:
        import release_progress as rp

        rels = rp.scan_releases(plan_store.plans_root_for(root))
        for info in list(rels.values())[:8]:
            membership.append(rp.format_line(info))
    except Exception:
        pass
    return {
        "base": base,
        "last_tag": last,
        "suggested_tag": suggested,
        "bump": level,
        "pending": rows,
        "finished_off_base": finished_off,
        "membership": membership,
        "columns": ["branch", "target", "ahead", "plan_lane", "plan_slug"],
    }


def _plan_diff_verdict(
    params: ReleaseParams, ctx: Ctx, data: dict[str, Any],
) -> str:
    if params.skip_review or params.no_delegate:
        return "PASS_WITH_NOTES"
    if not ctx.mode.interactive and not params.delegate:
        return "SKIPPED"
    if ctx.delegate is None:
        return "SKIPPED"
    root = Path(params.root)
    last = data.get("last_tag") or ""
    base = data["base"]
    rng = f"{last}..{base}" if last else base
    log = subprocess.run(
        ["git", "-C", str(root), "log", "--oneline", rng],
        capture_output=True, text=True, check=False,
    ).stdout
    stat = subprocess.run(
        ["git", "-C", str(root), "diff", "--stat", rng],
        capture_output=True, text=True, check=False,
    ).stdout
    blob = (log + "\n" + stat)[:8000]
    user = (
        "You are reviewing a release. Do not implement. "
        "Judge commits already on the release base since the last tag. "
        "End with ## Verdict and exactly one of PASS, PASS WITH NOTES, or HOLD.\n\n"
        f"BASE: {base}\nLAST TAG: {last or '(none)'}\n\n{blob}"
    )
    try:
        _name, out = _try_delegate(
            ctx, endpoint=params.delegate or "auto", role="critic",
            registry=params.registry, user=user,
        )
    except NotDelegated:
        return "SKIPPED"
    upper = out.upper()
    if re.search(r"\bHOLD\b", upper):
        return "HOLD"
    if "PASS WITH NOTES" in upper or "PASS_WITH_NOTES" in upper:
        return "PASS_WITH_NOTES"
    if re.search(r"\bPASS\b", upper):
        return "PASS"
    return "PASS_WITH_NOTES"


@_op("release.report", mutates=False, requires=None)
def op_release_report(params: ReleaseParams, _answers: Answers, ctx: Ctx) -> Result:
    data = _release_report_data(params)
    res = Result("release", "report")
    res.data.update(data)
    res.data["plans"] = data["pending"]
    verdict = _plan_diff_verdict(params, ctx, data)
    res.data["review"] = verdict
    if params.skip_review:
        res.notes.append("plan-diff skipped (--skip-review)")
    finished = data["finished_off_base"]
    if finished:
        res.exit_code = EXIT_NEEDS_OPERATOR
        res.need(
            "finished-off-base",
            NEEDS_OPERATOR,
            "finished work is not on the release base: " + ", ".join(finished)
            + " — land it with /review or pass --force-omit-finished",
        )
        return res
    if params.dry_run:
        res.notes.append(
            f"dry-run: would suggest {data['suggested_tag']} on {data['base']}"
        )
        return res
    res.need(
        "ship",
        NEEDS_OPERATOR,
        next_command(
            f"anchor release --yes --skip-review --tag {data['suggested_tag']}",
            f"tag {data['suggested_tag']} on a TTY (never merges)",
        ),
    )
    res.exit_code = EXIT_NEEDS_OPERATOR
    return res


@_op("release.ship", mutates=True, requires=NEEDS_OPERATOR)
def op_release_ship(params: ReleaseParams, _answers: Answers, ctx: Ctx) -> Result:
    res = Result("release", "ship")
    if not ctx.mode.interactive:
        res.exit_code = EXIT_NEEDS_OPERATOR
        res.need(
            "ship",
            NEEDS_OPERATOR,
            "tag and push need an interactive operator (--yes / --push are not substitutes)",
        )
        return res
    data = _release_report_data(params)
    res.data.update(data)
    finished = data["finished_off_base"]
    if finished and not params.force_omit_finished:
        res.exit_code = EXIT_NEEDS_OPERATOR
        res.need(
            "finished-off-base",
            NEEDS_OPERATOR,
            "finished work is not on the release base: " + ", ".join(finished),
        )
        return res
    verdict = _plan_diff_verdict(params, ctx, data)
    res.data["review"] = verdict
    if verdict == "HOLD" and not params.force_tag:
        res.exit_code = EXIT_NEEDS_OPERATOR
        res.need(
            "hold",
            NEEDS_OPERATOR,
            "plan-diff HOLD blocks the tag; pass --force-tag to override",
        )
        return res
    root = Path(params.root)
    base = data["base"]
    head = _git_out(root, "rev-parse", "HEAD")
    try:
        base_sha = _git_out(root, "rev-parse", base)
    except CliError as exc:
        raise CliError(f"unknown --base {base!r}: {exc}") from exc
    if head != base_sha:
        raise CliError(
            f"HEAD is not the release base {base} (checkout {base} or pass --base)"
        )
    tag = params.tag or data["suggested_tag"]
    if params.yes:
        _fold_changelog(root, tag)
        _bump_pyproject(root, tag)
        prep_script = Path(__file__).resolve().parent / "commit_prep.py"
        if prep_script.is_file() and (root / "tests").is_dir():
            prep = subprocess.run(
                [sys.executable, str(prep_script), "--root", str(root)],
                capture_output=True, text=True, check=False,
            )
            if prep.returncode != 0:
                res.exit_code = EXIT_ERROR
                res.error = f"commit-prep failed ({prep.returncode})"
                res.notes.append((prep.stdout or prep.stderr or "")[-2000:])
                return res
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=False, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", f"Release {tag}"],
            check=False, capture_output=True,
        )
        tagged = subprocess.run(
            ["git", "-C", str(root), "tag", "-a", tag, "-m", f"Release {tag}"],
            capture_output=True, text=True, check=False,
        )
        if tagged.returncode != 0:
            raise CliError(tagged.stderr.strip() or f"git tag {tag} failed")
        res.data["tag"] = tag
    if params.push:
        has = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
            capture_output=True, check=False,
        )
        if has.returncode != 0:
            raise CliError(f"no tag {tag} at HEAD; run --yes first")
        pushed = subprocess.run(
            ["git", "-C", str(root), "push", "origin", base, tag],
            capture_output=True, text=True, check=False,
        )
        if pushed.returncode != 0:
            raise CliError(pushed.stderr.strip() or "git push failed")
        res.data["pushed"] = [base, tag]
    if not params.yes and not params.push:
        res.exit_code = EXIT_NEEDS_OPERATOR
        res.need("ship", NEEDS_OPERATOR, "pass --yes to tag or --push to publish")
    return res

