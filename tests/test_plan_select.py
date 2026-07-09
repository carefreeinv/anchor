from pathlib import Path

import plan_select as ps
from plan_lease import claim_and_move
from plan_select import Fit, Worker, classify_fit, inventory, inventory_ready, select_one


def _plan(path: Path, *, value: str = "medium", preferred: str = "mid", title: str = "t") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Plan: {title}\n\n"
        f"- **Value:** {value}\n"
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


def test_select_prefers_own_in_progress_and_ignores_others(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "ready.md", preferred="mid")
    _plan(plans / "features" / "taken.md", preferred="mid")
    claim_and_move(plans, "features/taken.md", "agent-a", ttl_seconds=600)
    worker = Worker("test", "mid")

    # agent-b must not see agent-a's in-progress as pickable
    pick_b = select_one(plans, worker, agent_id="agent-b")
    assert pick_b is not None
    assert pick_b.rel == "features/ready.md"

    # agent-a resumes own in-progress first (even if ready work exists)
    pick_a = select_one(plans, worker, agent_id="agent-a")
    assert pick_a is not None
    assert pick_a.rel == "in-progress/taken.md"

    # inventory with agent_id includes own in-progress + ready
    listed = inventory(plans, worker, agent_id="agent-b")
    assert all(r.lane != "in-progress" or r.owner == "agent-b" for r in listed)
    assert not any(r.rel == "in-progress/taken.md" for r in listed)


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
