from pathlib import Path

import pytest
from plan_lease import (
    ClaimError,
    active_lease,
    claim,
    claim_and_move,
    claimed_rels,
    in_progress_owned_by,
    release,
)


def _plans(tmp_path: Path) -> Path:
    plans = tmp_path / ".plans"
    for lane in (
        "bugs",
        "features",
        "in-progress",
        "ambiguous",
        "blocked",
        "drafts",
        "completed",
    ):
        (plans / lane).mkdir(parents=True)
    return plans


def _write_plan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Plan: t\n\n- **Preferred models:** mid\n\n"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def test_claim_success_and_double_claim_fails(tmp_path):
    plans = _plans(tmp_path)
    rel = "features/foo.md"
    _write_plan(plans / rel)
    lease = claim(plans, rel, "agent-a", ttl_seconds=60)
    assert lease.agent_id == "agent-a"
    assert active_lease(plans, rel) is not None
    assert rel in claimed_rels(plans)

    with pytest.raises(ClaimError, match="already claimed"):
        claim(plans, rel, "agent-b", ttl_seconds=60)


def test_claim_and_move_to_in_progress(tmp_path):
    plans = _plans(tmp_path)
    _write_plan(plans / "features" / "foo.md")
    lease, dest = claim_and_move(plans, "features/foo.md", "agent-a", ttl_seconds=60)
    assert lease.plan_rel == "in-progress/foo.md"
    assert lease.origin_rel == "features/foo.md"
    assert dest.name == "foo.md"
    assert dest.parent.name == "in-progress"
    assert not (plans / "features" / "foo.md").exists()
    assert (plans / "in-progress" / "foo.md").is_file()
    assert in_progress_owned_by(plans, "agent-a") == ["in-progress/foo.md"]
    assert in_progress_owned_by(plans, "agent-b") == []


def test_other_agent_cannot_claim_in_progress(tmp_path):
    plans = _plans(tmp_path)
    _write_plan(plans / "features" / "foo.md")
    claim_and_move(plans, "features/foo.md", "agent-a", ttl_seconds=60)
    with pytest.raises(ClaimError, match="owned by"):
        claim_and_move(plans, "in-progress/foo.md", "agent-b", ttl_seconds=60)


def test_same_agent_resume_in_progress(tmp_path):
    plans = _plans(tmp_path)
    _write_plan(plans / "features" / "foo.md")
    claim_and_move(plans, "features/foo.md", "agent-a", ttl_seconds=60)
    lease, dest = claim_and_move(plans, "in-progress/foo.md", "agent-a", ttl_seconds=120)
    assert lease.agent_id == "agent-a"
    assert dest.name == "foo.md"


def test_stale_lease_reclaim(tmp_path):
    plans = _plans(tmp_path)
    rel = "features/foo.md"
    _write_plan(plans / rel)
    claim(plans, rel, "agent-a", ttl_seconds=1)
    path = plans / ".leases" / "features__foo.md.json"
    path.write_text(
        '{"plan": "features/foo.md", "agent_id": "agent-a", '
        '"claimed_at": 1, "expires_at": 2}\n',
        encoding="utf-8",
    )
    assert active_lease(plans, rel) is None
    lease = claim(plans, rel, "agent-b", ttl_seconds=60)
    assert lease.agent_id == "agent-b"


def test_release(tmp_path):
    plans = _plans(tmp_path)
    rel = "features/foo.md"
    _write_plan(plans / rel)
    claim(plans, rel, "agent-a", ttl_seconds=60)
    assert release(plans, rel, agent_id="agent-a") is True
    assert active_lease(plans, rel) is None


def test_park_ambiguous_and_blocked(tmp_path):
    from plan_lease import park

    plans = _plans(tmp_path)
    _write_plan(plans / "features" / "half.md")
    dest = park(plans, "features/half.md", "ambiguous")
    assert dest.parent.name == "ambiguous"
    assert not (plans / "features" / "half.md").exists()

    _write_plan(plans / "bugs" / "stuck.md")
    claim_and_move(plans, "bugs/stuck.md", "agent-a", ttl_seconds=60)
    dest2 = park(plans, "in-progress/stuck.md", "blocked", agent_id="agent-a")
    assert dest2.parent.name == "blocked"
    assert active_lease(plans, "in-progress/stuck.md") is None


def test_return_to_ready_from_in_progress(tmp_path):
    from plan_lease import return_to_ready

    plans = _plans(tmp_path)
    _write_plan(plans / "bugs" / "b.md")
    claim_and_move(plans, "bugs/b.md", "agent-a", ttl_seconds=60)
    dest = return_to_ready(plans, "in-progress/b.md", agent_id="agent-a")
    assert dest.parent.name == "bugs"
    assert (plans / "bugs" / "b.md").is_file()


def test_return_to_ready_from_blocked(tmp_path):
    from plan_lease import park, return_to_ready

    plans = _plans(tmp_path)
    _write_plan(plans / "features" / "x.md")
    park(plans, "features/x.md", "blocked")
    dest = return_to_ready(plans, "blocked/x.md", target_lane="features")
    assert dest.parent.name == "features"
