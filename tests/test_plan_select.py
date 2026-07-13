from pathlib import Path

import plan_select as ps
from plan_lease import claim_and_move
from plan_select import Fit, Worker, classify_fit, inventory_ready, select_one


def _plan(
    path: Path,
    *,
    value: str = "medium",
    preferred: str = "mid",
    title: str = "t",
    priority: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prio_line = f"- **Priority:** {priority}\n" if priority is not None else ""
    path.write_text(
        f"# Plan: {title}\n\n"
        f"- **Value:** {value}\n"
        f"{prio_line}"
        f"- **Preferred models:** {preferred}\n\n"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def _tree(tmp_path: Path) -> Path:
    plans = tmp_path / ".plans"
    for lane in ("bugs", "features", "in-progress", "drafts", "completed"):
        (plans / lane).mkdir(parents=True)
    return plans


def test_priority_bugs_before_features_then_value(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "low.md", value="low", preferred="mid")
    _plan(plans / "features" / "high.md", value="high", preferred="mid")
    _plan(plans / "bugs" / "zzz.md", value="low", preferred="mid")
    worker = Worker("test", "mid")
    recs = inventory_ready(plans, worker)
    assert [r.rel for r in recs] == [
        "bugs/zzz.md",
        "features/high.md",
        "features/low.md",
    ]


def test_parse_priority_tolerant():
    from plan_select import parse_priority

    assert parse_priority("- **Priority:** P1\n") == "P1"
    assert parse_priority("- **priority:** p3\n") == "P3"
    assert parse_priority("- **Priority:** 2\n") == "P2"
    assert parse_priority("- **Priority:** P1 — foundational\n") == "P1"
    assert parse_priority("- **Priority:** `P1`\n") == "P1"
    assert parse_priority("no priority header at all") == "P2"
    assert parse_priority("- **Priority:** banana\n") == "P2"


def test_priority_orders_within_lane_and_bugs_first(tmp_path):
    plans = _tree(tmp_path)
    # Same lane: P1 beats P2 even though the P2 plan has higher Value.
    _plan(plans / "features" / "p2high.md", value="high", preferred="mid", priority="P2")
    _plan(plans / "features" / "p1low.md", value="low", preferred="mid", priority="P1")
    # A P1 bug still precedes any feature (lane is authoritative over priority).
    _plan(plans / "bugs" / "p1bug.md", value="low", preferred="mid", priority="P1")
    recs = inventory_ready(plans, Worker("t", "mid"))
    assert [r.rel for r in recs] == [
        "bugs/p1bug.md",
        "features/p1low.md",
        "features/p2high.md",
    ]


def test_missing_priority_defaults_p2(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "noprio.md", value="high", preferred="mid")  # no Priority
    _plan(plans / "features" / "p1.md", value="low", preferred="mid", priority="P1")
    recs = inventory_ready(plans, Worker("t", "mid"))
    # Explicit P1 sorts before default-P2, regardless of Value.
    assert [r.rel for r in recs] == ["features/p1.md", "features/noprio.md"]
    noprio = next(r for r in recs if r.rel == "features/noprio.md")
    assert noprio.priority == "P2"


def test_fit_skip_overqualified_and_underqualified():
    assert classify_fit(Worker("fable", "frontier"), "small, mid") == Fit.OVERQUALIFIED
    assert classify_fit(Worker("haiku", "small"), "reasoner, frontier") == Fit.UNDERQUALIFIED
    assert classify_fit(Worker("sonnet", "mid"), "mid, reasoner") == Fit.GOOD
    assert classify_fit(Worker("Grok 4.5", "mid"), "Grok 4.5, Qwen3 32B") == Fit.GOOD
    assert classify_fit(Worker("unknown", "mid"), None) == Fit.UNKNOWN


def test_select_skips_poor_fit_unless_no_fit_check(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "hard.md", preferred="reasoner, frontier")
    _plan(plans / "features" / "easy.md", preferred="small")
    small = Worker("tiny", "small")
    picked = select_one(plans, small)
    assert picked is not None
    assert picked.rel == "features/easy.md"

    only_hard = _tree(tmp_path / "only")
    _plan(only_hard / "features" / "hard.md", preferred="reasoner")
    assert select_one(only_hard, small) is None
    assert select_one(only_hard, small, no_fit_check=True) is not None


def test_refuse_drafts_and_completed_paths(tmp_path):
    plans = _tree(tmp_path)
    draft = plans / "drafts" / "nope.md"
    _plan(draft, preferred="mid")
    done = plans / "completed" / "done.md"
    _plan(done, preferred="mid")

    import pytest

    with pytest.raises(ValueError, match="drafts"):
        ps.assert_ready_path(draft, plans)
    with pytest.raises(ValueError, match="completed"):
        ps.resolve_target(plans, path=done)


def test_slug_matches_local_and_tracked(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "foo.local.md", preferred="mid", title="local")
    rec = ps.resolve_target(plans, slug="foo")
    assert rec is not None
    assert rec.slug == "foo"
    assert rec.rel == "features/foo.local.md"


def test_inventory_ignores_drafts(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "drafts" / "secret.md", preferred="mid")
    _plan(plans / "features" / "ready.md", preferred="mid")
    recs = inventory_ready(plans, Worker("x", "mid"))
    assert len(recs) == 1
    assert recs[0].rel == "features/ready.md"


def test_bare_pick_is_ready_only_never_resumes(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "ready.md", preferred="mid")
    _plan(plans / "features" / "taken.md", preferred="mid")
    claim_and_move(plans, "features/taken.md", "agent-a", ttl_seconds=600)
    worker = Worker("test", "mid")

    # Neither agent bare-picks in-progress. Both get the remaining ready plan —
    # even agent-a, the owner: resume is an explicit named claim, not a bare pick.
    for aid in ("agent-b", "agent-a"):
        pick = select_one(plans, worker, agent_id=aid)
        assert pick is not None and pick.rel == "features/ready.md"

    # With every ready plan now claimed, bare pick returns nothing — the owner
    # does NOT fall back to resuming its own in-progress plan.
    claim_and_move(plans, "features/ready.md", "agent-b", ttl_seconds=600)
    assert select_one(plans, worker, agent_id="agent-a") is None


def test_resolve_own_in_progress_ok_and_unleased_refuses(tmp_path):
    import pytest

    plans = _tree(tmp_path)
    _plan(plans / "features" / "y.md", preferred="mid")
    claim_and_move(plans, "features/y.md", "agent-a", ttl_seconds=600)

    # Owner may resume its own in-progress plan by explicit named path.
    rec = ps.resolve_target(
        plans, path=plans / "in-progress" / "y.md", agent_id="agent-a"
    )
    assert rec is not None and rec.rel == "in-progress/y.md"

    # Drop the lease → in-progress with no active lease must NOT be silently
    # reclaimed, even by the same agent id (recovery is explicit).
    from plan_lease import release

    release(plans, "in-progress/y.md", force=True)
    with pytest.raises(ValueError, match="no active lease"):
        ps.resolve_target(
            plans, path=plans / "in-progress" / "y.md", agent_id="agent-a"
        )


def test_resolve_foreign_in_progress_refuses(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "x.md", preferred="mid")
    claim_and_move(plans, "features/x.md", "agent-a", ttl_seconds=600)
    import pytest

    with pytest.raises(ValueError, match="owned by"):
        ps.resolve_target(
            plans,
            path=plans / "in-progress" / "x.md",
            agent_id="agent-b",
        )
