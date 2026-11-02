"""A non-CLI adapter drives every registered operation; operator steps stop."""
from __future__ import annotations

from pathlib import Path

import anchor_ops as ops
import pytest
from test_anchor_cli import write


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for lane in ("bugs", "features", "in-progress", "review-needed", "drafts",
                 "completed", "ambiguous", "blocked"):
        (root / ".plans" / lane).mkdir(parents=True)
    write(root, "features", "f1")
    write(root, "review-needed", "r1")
    write(root, "drafts", "d1")
    return root


def _ctx() -> ops.Ctx:
    return ops.Ctx(mode=ops.Mode(False, "transport-test"), agent_id="t1")


def _params(name: str, root: Path):
    r = str(root)
    return {
        "plans.list": ops.PlansListParams(root=r),
        "plans.board": ops.PlansBoardParams(root=r, as_json=True),
        "work.list": ops.WorkListParams(root=r, tier="mid"),
        "work.claim": ops.WorkClaimParams(root=r, slug="f1", no_fit_check=True),
        "work.heartbeat": ops.WorkSlugParams(root=r, slug="missing"),
        "work.finish": ops.WorkSlugParams(root=r, slug="missing"),
        "work.return": ops.WorkSlugParams(root=r, slug="missing"),
        "review.list": ops.ReviewListParams(root=r),
        "review.review": ops.ReviewParams(root=r, slug="r1"),
        "draft.list": ops.DraftListParams(root=r),
        "draft.create": ops.DraftCreateParams(root=r, slug="fresh"),
        "draft.promote": ops.DraftPromoteParams(root=r, slug="d1"),
        "fleet-watch.status": ops.FleetWatchParams(root=r),
        "fleet-watch.list": ops.FleetWatchParams(root=r, tier="mid", agent_id="t1"),
        "fleet-watch.once": ops.FleetWatchParams(root=r, tier="mid", agent_id="t1"),
        "fleet-watch.emit": ops.FleetWatchParams(
            root=r, workers=("tier=mid,agent=t1,interval=5m",), emit="systemd",
        ),
        "fleet-watch.install": ops.FleetWatchParams(
            root=r, workers=("tier=mid,agent=t1,interval=5m",), yes=True,
        ),
    }[name]


def test_never_answers_adapter_covers_every_operation(project):
    answers = ops.NeverAnswers()
    ctx = _ctx()
    seen = []
    for op in ops.operations():
        try:
            res = ops.run(op.name, _params(op.name, project), answers, ctx)
        except ops.Passthrough as p:
            seen.append((op.name, "passthrough", p.code))
            continue
        except ops.CliError as exc:
            seen.append((op.name, "error", str(exc)))
            continue
        except ops.NeedsOperator as exc:
            seen.append((op.name, "needs_operator", exc.step))
            continue
        pending = [p["needs"] for p in res.pending]
        seen.append((op.name, res.exit_code, pending))
        if op.requires == ops.NEEDS_OPERATOR and op.mutates:
            assert res.exit_code == ops.EXIT_NEEDS_OPERATOR, op.name
            assert ops.NEEDS_OPERATOR in pending, op.name
    names = {op.name for op in ops.operations()}
    assert {row[0] for row in seen} == names


def test_fleet_watch_install_headless_writes_nothing(project, tmp_path, monkeypatch):
    unit_dir = tmp_path / "systemd-user"
    unit_dir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    answers = ops.NeverAnswers()
    ctx = _ctx()
    res = ops.run(
        "fleet-watch.install",
        ops.FleetWatchParams(
            root=str(project),
            workers=("tier=mid,agent=t1,interval=5m",),
            yes=True,
        ),
        answers,
        ctx,
    )
    assert res.exit_code == ops.EXIT_NEEDS_OPERATOR
    assert list(unit_dir.iterdir()) == []


def test_operator_ops_do_not_merge(project):
    """review.review / draft.promote with NeverAnswers must not move the plan."""
    answers = ops.NeverAnswers()
    ctx = _ctx()
    res = ops.run(
        "review.review",
        ops.ReviewParams(root=str(project), slug="r1"),
        answers,
        ctx,
    )
    assert res.exit_code == ops.EXIT_NEEDS_OPERATOR
    assert (project / ".plans" / "review-needed" / "r1.md").is_file()
    assert not (project / ".plans" / "completed" / "r1.md").exists()
    # promote without --to also stops
    try:
        ops.run(
            "draft.promote",
            ops.DraftPromoteParams(root=str(project), slug="d1"),
            answers,
            ctx,
        )
    except ops.NeedsOperator as exc:
        assert exc.step == "promote-lane"
    else:
        raise AssertionError("promote without --to must ask")
    assert (project / ".plans" / "drafts" / "d1.md").is_file()


def test_headless_refuses_injected_delegate(project):
    """M2: core refuses delegate even when the adapter injected the capability."""
    calls: list[str] = []

    def injected(endpoint, role, registry, user):
        calls.append(role)
        return endpoint, "should not run"

    ctx = ops.Ctx(
        mode=ops.Mode(False, "transport-test"),
        agent_id="t1",
        delegate=injected,
    )
    res = ops.run(
        "review.review",
        ops.ReviewParams(root=str(project), slug="r1", delegate="auto"),
        ops.NeverAnswers(),
        ctx,
    )
    assert calls == []
    assert any("not delegated" in n for n in res.notes)
    assert ops.NEEDS_OPERATOR in [p["needs"] for p in res.pending]


def test_headless_refuses_injected_run(project):
    ran = []

    def orch(_dest, _argv):
        ran.append(True)
        return 0

    ctx = ops.Ctx(
        mode=ops.Mode(False, "transport-test"),
        agent_id="t1",
        run_orchestrate=orch,
    )
    res = ops.run(
        "work.claim",
        ops.WorkClaimParams(root=str(project), slug="f1", no_fit_check=True, run=True),
        ops.NeverAnswers(),
        ctx,
    )
    assert ran == []
    assert any("--run ignored" in n for n in res.notes)
