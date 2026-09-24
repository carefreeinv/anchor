#!/usr/bin/env python3
"""``anchor plans | work | review | draft`` — Anchor's plan workflow from a terminal.

Reached through ``scripts/anchor.py`` (and ``bin/anchor``) when the first argument
is one of those verbs; every other invocation is the scaffolder, unchanged.

The verbs do the **deterministic** parts of the workflow themselves — listing,
picking, claiming, lane moves, the merge gate — by calling the modules that
already own those rules (``plan_store``, ``plan_select``, ``plan_lease``,
``work_once``, ``merge_feature``). The CLI contains no model and no copy of a
lane, fit or ``Depends on`` rule. Steps that need judgment (writing plan prose,
a critic pass, executing a plan) are either **delegated** to a configured
endpoint through ``anchor_client`` — interactive runs only, and only when asked
with ``--delegate`` — or reported back as ``pending``.

Two modes, one code path:

* **interactive** — a human at a TTY. Verbs may ask; output is human-readable.
* **non-interactive** — ``--non-interactive``, ``ANCHOR_NONINTERACTIVE=1``, or
  stdin/stdout not a TTY (ambiguous environments are treated as headless).
  Nothing prompts, output is always JSON, nothing merges, nothing delegates: a
  step that needs an operator's answer exits ``3`` naming the answer, and a step
  that needs a model is listed under ``pending`` for the calling agent to do.

No flag stands in for an operator answer. ``anchor review`` merges only after
the operator answers Approve in this session, only through ``merge_feature``'s
gate, only by fast-forward onto the integration branch, never onto ``main``.

Exit codes: 0 done · 1 nothing to do · 2 usage or hard error ·
3 stopped: an operator answer (or a harness-only step) is required.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import plan_lease
import plan_store

SCHEMA_VERSION = 1
VERBS = ("plans", "work", "review", "draft")

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


def is_verb_invocation(argv: list[str]) -> bool:
    """True when ``argv`` names a verb. A project dir called ``work`` is ``./work``."""
    return bool(argv) and argv[0] in VERBS


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
    """Interactive only when nothing says otherwise and both ends are a TTY.

    Every uncertainty resolves to non-interactive: that direction can only
    stop and hand back, never ask or act on a guess.
    """
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


class NeedsOperator(Exception):
    """A step needs a human answer that this run cannot get."""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__(detail)
        self.step = step
        self.detail = detail


class CliError(Exception):
    """A usage or hard error: exit 2 with this message."""


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


# --- results -------------------------------------------------------------------


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


# --- shared helpers --------------------------------------------------------------


def _plans_root(args: argparse.Namespace) -> Path:
    root = Path(args.root).expanduser().resolve()
    plans = plan_store.plans_root_for(root)
    if not plans.is_dir():
        raise CliError(f"no .plans/ tree under {root}")
    return plans


def _title(ref: plan_store.PlanRef) -> str:
    from plan_select import parse_title, strip_code_fences

    text, err = plan_store.read_text(ref)
    if err is not None or text is None:
        return ref.name
    return parse_title(strip_code_fences(text), ref.name)


def _default_agent_id() -> str:
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "user"
    return f"anchor-{user}"


def _one(plans: Path, lane: str, slug: str) -> plan_store.PlanRef:
    hits = plan_store.lookup(plans, lane, slug)
    if not hits:
        raise CliError(f"no plan {slug!r} in {lane}/")
    if len(hits) > 1:
        raise CliError(f"ambiguous slug {slug!r} in {lane}/: {', '.join(h.rel for h in hits)}")
    return hits[0]


def _lane_commit_hint(res: Result, slug: str, lane: str, why: str) -> None:
    res.notes.append(
        f"lane move not committed; if .plans/ is tracked: "
        f'git add .plans/ && git commit -m "Plans: {slug} → {lane} ({why})" -- .plans/'
    )


# --- delegation -------------------------------------------------------------------


class NotDelegated(Exception):
    """Delegation did not happen; the message says why (never a silent skip)."""


def delegate(
    mode: Mode,
    *,
    endpoint: str,
    role: str,
    registry: str | None,
    user: str,
) -> tuple[str, str]:
    """Send one judgment step to a configured endpoint. Returns ``(endpoint, text)``.

    Refuses when non-interactive: the caller is already a model, and a model
    starting another model is never automatic.
    """
    if not mode.interactive:
        raise NotDelegated("non-interactive run: the calling agent does this step itself")
    try:
        import anchor_client
    except ImportError as exc:
        raise NotDelegated(f"delegation needs the {exc.name!r} package") from exc
    reg = Path(registry) if registry else anchor_client.DEFAULT_REGISTRY
    if not reg.is_file():
        raise NotDelegated(f"no endpoint registry at {reg}")
    fleet = anchor_client.Fleet(reg)
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
    system = anchor_client.load_prompt(MYTHOS_CORE)
    try:
        text = ep.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            thinking=True,
        )
    except Exception as exc:  # network/model failure: report, never pretend
        raise NotDelegated(f"{ep.name}: {exc}") from exc
    return ep.name, text


# --- verb: plans -------------------------------------------------------------------


def cmd_plans(args: argparse.Namespace, mode: Mode, _ask: Prompter) -> Result:
    if args.board:
        import plan_board

        argv = ["--project", str(Path(args.root).resolve())]
        if not mode.interactive or args.json:
            argv.append("--json")
        raise _Passthrough(plan_board.main(argv))
    plans = _plans_root(args)
    lanes = args.lane or plan_store.lane_names(plans)
    res = Result("plans", "list")
    res.data["columns"] = ["rel", "lane", "slug", "title"]
    res.data["plans"] = [
        {"rel": r.rel, "lane": r.lane, "slug": r.slug, "title": _title(r)}
        for r in plan_store.list_lanes(plans, lanes)
    ]
    res.data["counts"] = {lane: plan_store.count(plans, lane) for lane in lanes}
    return res


class _Passthrough(Exception):
    """A verb handed the whole run to an existing script; carry its exit code."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


# --- verb: work ----------------------------------------------------------------------


def _worker(args: argparse.Namespace):
    from work_once import resolve_worker

    return resolve_worker(args)


def cmd_work(args: argparse.Namespace, mode: Mode, _ask: Prompter) -> Result:
    from plan_select import inventory

    plans = _plans_root(args)
    agent_id = args.agent_id or _default_agent_id()

    if args.list:
        res = Result("work", "list")
        records = inventory(plans, _worker(args), agent_id=agent_id)
        res.data["columns"] = [
            "rel", "lane", "priority", "value", "preferred", "fit", "deps", "assignee", "owner",
        ]
        res.data["plans"] = [
            {
                "rel": r.rel,
                "lane": r.lane,
                "slug": r.slug,
                "priority": r.priority,
                "value": r.value,
                "preferred": r.preferred,
                "fit": r.fit.value,
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

    if args.heartbeat:
        lease = plan_lease.renew(plans, _own_rel(plans, args.heartbeat), agent_id)
        res = Result("work", "heartbeat")
        res.data.update(plan=lease.plan_rel, agent_id=agent_id, expires_at=lease.expires_at)
        return res

    if args.finish:
        rel = _own_rel(plans, args.finish)
        dest = plan_lease.finish_to_review(plans, rel, agent_id)
        ref = plan_store.ref_for_path(plans, dest)
        res = Result("work", "finish")
        res.data.update(plan=ref.rel if ref else str(dest), agent_id=agent_id)
        res.need("review", NEEDS_OPERATOR, f"sign-off: anchor review {ref.slug if ref else ''}".strip())
        _lane_commit_hint(res, ref.slug if ref else rel, "review-needed", "anchor work --finish")
        return res

    if args.return_ready:
        rel = _own_rel(plans, args.return_ready)
        dest = plan_lease.return_to_ready(plans, rel, agent_id=agent_id)
        ref = plan_store.ref_for_path(plans, dest)
        res = Result("work", "return")
        res.data.update(plan=ref.rel if ref else str(dest), agent_id=agent_id)
        return res

    return _work_claim(args, mode, plans, agent_id)


def _own_rel(plans: Path, slug: str) -> str:
    return _one(plans, "in-progress", slug).rel


def _work_claim(args: argparse.Namespace, mode: Mode, plans: Path, agent_id: str) -> Result:
    from work_once import pick_claim_one

    res = Result("work", "claim")
    ns = argparse.Namespace(
        slug=args.slug,
        path=None,
        no_fit_check=args.no_fit_check,
        no_dep_check=False,
        allow_assigned=False,
        agent_id=agent_id,
        lease_ttl=plan_lease.DEFAULT_TTL_SECONDS,
    )
    try:
        dest = pick_claim_one(plans, _worker(args), ns)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    if dest is None:
        res.exit_code = EXIT_NOTHING
        res.notes.append("nothing claimed (see stderr for why)")
        return res
    ref = plan_store.ref_for_path(plans, dest)
    rel = ref.rel if ref else str(dest)
    res.data.update(plan=rel, path=str(dest), agent_id=agent_id)
    detail = (
        f"implement the plan's Steps: /work {rel} in your coding harness; "
        f"then anchor work --finish {ref.slug if ref else rel}"
    )
    if args.run:
        if not mode.interactive:
            res.notes.append("--run ignored: non-interactive runs never start a model")
            res.need("execute", NEEDS_MODEL, detail)
            return res
        from work_once import run_orchestrate

        code = run_orchestrate(dest, [])
        res.data["orchestrate_exit"] = code
        if code != 0:
            res.exit_code = EXIT_ERROR
            res.error = f"orchestrate.py exited {code}; plan stays in in-progress/"
        return res
    res.need("execute", NEEDS_MODEL, detail)
    return res


# --- verb: review --------------------------------------------------------------------


def _review_package(root: Path, slug: str) -> dict[str, Any]:
    """Facts the operator decides on — all deterministic, all from git."""
    import merge_feature as mf

    branch = f"feature/{slug}"
    pkg: dict[str, Any] = {"branch": None, "target": None, "head": None,
                           "fast_forward": None, "already_merged": None, "changed": []}
    try:
        if branch not in mf.local_branches(root):
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


def cmd_review(args: argparse.Namespace, mode: Mode, ask: Prompter) -> Result:
    import pending_merges

    plans = _plans_root(args)
    root = plans.parent
    refs = plan_store.list_lane(plans, "review-needed")

    if args.list or not args.slug:
        res = Result("review", "list")
        res.data["columns"] = ["rel", "slug", "title", "held"]
        res.data["plans"] = [
            {"rel": r.rel, "slug": r.slug, "title": _title(r),
             "held": pending_merges.is_held(r.path)}
            for r in refs
        ]
        if not refs:
            res.exit_code = EXIT_NOTHING
        return res

    ref = _one(plans, "review-needed", args.slug)
    res = Result("review", "review")
    pkg = _review_package(root, ref.slug)
    res.data.update(plan=ref.rel, title=_title(ref), **pkg)

    if args.delegate:
        _critic(args, mode, ref, pkg, root, res)
    else:
        res.need("critic", NEEDS_MODEL,
                 "AI critic pass over the plan's Done when and the branch diff")

    try:
        return _decide(res, ask, root, plans, ref, pkg)
    except NeedsOperator as exc:
        # Stop with everything gathered so far, plus the answer that is missing.
        res.exit_code = EXIT_NEEDS_OPERATOR
        res.need(exc.step, NEEDS_OPERATOR, exc.detail)
        return res


def _decide(res: Result, ask: Prompter, root: Path, plans: Path, ref, pkg) -> Result:
    choice = ask.choose("review-decision", f"Decision for {ref.rel}", REVIEW_CHOICES)
    res.data["decision"] = choice
    res.pending = [p for p in res.pending if p["step"] != "critic"]
    if choice == "skip":
        return res
    if choice == "approve":
        return _approve(res, root, plans, ref, pkg)
    if choice == "needs-work":
        lane = ask.choose("needs-work-lane", "Return it as", READY_LANES)
        notes = ask.text("needs-work-notes", "Actionable notes (required)")
        _append_section(ref, "Review notes", notes)
        new = plan_store.move(plans, ref.rel, lane)
        res.data["moved_to"] = new.rel
        _lane_commit_hint(res, ref.slug, lane, "anchor review needs-work")
        return res
    blocker = ask.text("defer-blocker", "What blocks it (required)")
    _append_section(ref, "Blocked", blocker)
    new = plan_store.move(plans, ref.rel, "blocked")
    res.data["moved_to"] = new.rel
    _lane_commit_hint(res, ref.slug, "blocked", "anchor review defer")
    return res


def _critic(args, mode, ref, pkg, root, res: Result) -> None:
    import subprocess

    text, _err = plan_store.read_text(ref)
    diff = ""
    if pkg.get("head") and pkg.get("target"):
        p = subprocess.run(
            ["git", "-C", str(root), "diff", f"{pkg['target']}...{pkg['head']}"],
            capture_output=True, text=True, check=False,
        )
        diff = p.stdout[:60000]
    try:
        import anchor_client

        template = anchor_client.load_prompt("anchor/templates/review.md")
    except (ImportError, OSError):
        template = ""
    user = (
        "You are the critic. Review only; do not fix. Judge whether the Done when "
        f"items hold.\n\nTEMPLATE:\n{template}\n\nPLAN:\n{text or ''}\n\nDIFF:\n{diff}"
    )
    try:
        name, out = delegate(mode, endpoint=args.delegate, role="critic",
                             registry=args.registry, user=user)
    except NotDelegated as exc:
        res.notes.append(f"critic not delegated: {exc}")
        res.need("critic", NEEDS_MODEL,
                 "AI critic pass over the plan's Done when and the branch diff")
        return
    res.data["critic"] = {"endpoint": name, "text": out}
    if mode.interactive and not args.json:
        print(f"--- critic ({name}) ---\n{out}\n---", file=sys.stderr)


def _approve(res: Result, root: Path, plans: Path, ref, pkg: dict[str, Any]) -> Result:
    import merge_feature as mf

    if pkg["branch"] and not pkg["already_merged"]:
        if not pkg["fast_forward"]:
            res.exit_code = EXIT_NEEDS_OPERATOR
            res.need(
                "merge-commit", NEEDS_HARNESS,
                f"{pkg['branch']} is not a fast-forward of {pkg['target']}: a merge commit "
                f"needs /commit-prep on the merged tree — finish with /review {ref.slug}",
            )
            return res
        # Same gate /work uses. Scope = everything the operator was shown;
        # provenance = the head they were shown, so nothing moved since.
        verdict, outcome = mf.run(
            root, ref.slug, tuple(pkg["changed"]),
            expect_head=pkg["head"], target=pkg["target"], title=res.data.get("title", ""),
        )
        res.data["merge"] = {"ok": verdict.ok, "reason": verdict.reason,
                             "message": verdict.message, "outcome": outcome}
        if not verdict.ok or outcome in (None, mf.STAGED):
            res.exit_code = EXIT_ERROR
            res.error = f"merge refused: {verdict.message}"
            return res
    new = plan_store.move(plans, ref.rel, "completed")
    res.data["moved_to"] = new.rel
    _lane_commit_hint(res, ref.slug, "completed", "anchor review approve")
    return res


def _append_section(ref: plan_store.PlanRef, heading: str, body: str) -> None:
    text, err = plan_store.read_text(ref)
    if err is not None or text is None:
        raise CliError(f"cannot read {ref.rel}: {err}")
    ref.path.write_text(text.rstrip("\n") + f"\n\n## {heading}\n{body}\n", encoding="utf-8")


# --- verb: draft ----------------------------------------------------------------------

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


def cmd_draft(args: argparse.Namespace, mode: Mode, ask: Prompter) -> Result:
    plans = _plans_root(args)

    if args.promote:
        ref = _one(plans, "drafts", args.promote)
        lane = args.to or ask.choose("promote-lane", f"Promote {ref.rel} to", READY_LANES)
        new = plan_store.move(plans, ref.rel, lane)
        res = Result("draft", "promote")
        res.data.update(plan=new.rel)
        _lane_commit_hint(res, ref.slug, lane, "anchor draft --promote")
        return res

    if args.list or not args.slug:
        res = Result("draft", "list")
        res.data["columns"] = ["rel", "slug", "title"]
        res.data["plans"] = [
            {"rel": r.rel, "slug": r.slug, "title": _title(r)}
            for r in plan_store.list_lane(plans, "drafts")
        ]
        if not res.data["plans"]:
            res.exit_code = EXIT_NOTHING
        return res

    taken = plan_store.find_slug(plans, args.slug, dated=False)
    if taken:
        raise CliError(f"slug {args.slug!r} already used: {', '.join(r.rel for r in taken)}")
    goal = args.goal or "TODO — the outcome, in one paragraph."
    text = DRAFT_SKELETON.format(title=args.title or args.slug, slug=args.slug, goal=goal)
    res = Result("draft", "create")
    prose_step = "write the plan's Goal, Steps and Done when (template: anchor/templates/plan.md)"

    if args.delegate:
        text = _delegated_draft(args, mode, text, res) or text
    else:
        res.need("plan-prose", NEEDS_MODEL, prose_step)

    ref = plan_store.create(plans, "drafts", args.slug, text, local=args.local)
    res.data.update(plan=ref.rel, path=str(ref.path))
    res.notes.append(f"promote when ready: anchor draft --promote {args.slug} --to features|bugs")
    return res


def _delegated_draft(args, mode: Mode, skeleton: str, res: Result) -> str | None:
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
        name, out = delegate(mode, endpoint=args.delegate, role="planner",
                             registry=args.registry, user=user)
    except NotDelegated as exc:
        res.notes.append(f"plan prose not delegated: {exc}")
        res.need("plan-prose", NEEDS_MODEL, "write the plan's Goal, Steps and Done when")
        return None
    # Deterministic acceptance check: a plan missing a required section is
    # not written over the skeleton.
    missing = [s for s in REQUIRED_SECTIONS if s not in out]
    if missing:
        res.notes.append(f"{name} draft rejected (missing {', '.join(missing)}); kept skeleton")
        res.need("plan-prose", NEEDS_MODEL, "write the plan's Goal, Steps and Done when")
        return None
    res.data["delegated_to"] = name
    return out.strip() + "\n"


# --- parser + dispatch -------------------------------------------------------------------


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


COMMANDS: dict[str, Callable[[argparse.Namespace, Mode, Prompter], Result]] = {
    "plans": cmd_plans,
    "work": cmd_work,
    "review": cmd_review,
    "draft": cmd_draft,
}


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
    try:
        res = COMMANDS[args.verb](args, mode, Prompter(mode, read))
    except _Passthrough as p:
        return p.code
    except NeedsOperator as exc:
        res = Result(args.verb, action, exit_code=EXIT_NEEDS_OPERATOR)
        res.need(exc.step, NEEDS_OPERATOR, exc.detail)
    except (CliError, plan_store.PlanMoveError, plan_lease.ClaimError, FileExistsError) as exc:
        res = Result(args.verb, action, exit_code=EXIT_ERROR, error=str(exc))
    if as_json:
        print(json.dumps(res.to_json(mode), indent=2, default=str), file=out)
    else:
        _render_text(res, out)
    return res.exit_code
