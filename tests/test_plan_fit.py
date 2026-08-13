import json
from pathlib import Path

import plan_fit
from plan_select import (
    TIER_EFFORT,
    Effort,
    Worker,
    classify_effort,
    inventory_ready,
    normalize_effort,
    plan_effort_tier,
)


def _plan(path: Path, *, preferred: str | None = "mid", value: str = "medium",
          depends: str = "none", assignee: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pref = f"- **Preferred models:** {preferred}\n" if preferred is not None else ""
    asg = f"- **Assignee:** {assignee}\n" if assignee is not None else ""
    path.write_text(
        f"# Plan: {path.stem}\n\n- **Value:** {value}\n{pref}{asg}"
        f"- **Depends on:** {depends}\n\n## Goal\ng\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def _tree(tmp_path: Path) -> Path:
    plans = tmp_path / ".plans"
    for lane in ("bugs", "features", "in-progress", "drafts", "completed"):
        (plans / lane).mkdir(parents=True)
    return plans


# --- effort model -----------------------------------------------------------

def test_effort_band_follows_highest_listed_tier():
    assert plan_effort_tier("small") == "small"
    assert plan_effort_tier("mid, reasoner") == "reasoner"
    assert plan_effort_tier("small, mid") == "mid"
    # Names-only and absent both fall back to mid (a ceiling hint, not a floor).
    assert plan_effort_tier("Claude Sonnet 5") == "mid"
    assert plan_effort_tier(None) == "mid"


def test_effort_verdicts():
    # High effort on a mid plan is overpaying; the fix is the dial, not the plan.
    adv = classify_effort("high", "mid")
    assert adv.verdict is Effort.WASTEFUL and adv.suggested == "low"
    assert adv.should_change and "overpaying" in adv.note()

    # Low effort on reasoner work is underpowered.
    adv = classify_effort("low", "reasoner")
    assert adv.verdict is Effort.UNDERPOWERED and adv.suggested == "high"

    # In-band is silent — nothing to say, nothing to print.
    adv = classify_effort("medium", "mid")
    assert adv.verdict is Effort.OK and not adv.should_change and adv.note() == ""

    # No dial reported (many products expose none) is not an error.
    assert classify_effort(None, "mid").verdict is Effort.UNKNOWN


def test_effort_aliases_and_unknown_names():
    assert normalize_effort("MAX") == "xhigh"
    assert normalize_effort("off") == "none"
    assert normalize_effort("med") == "medium"
    assert normalize_effort("turbo") is None
    assert normalize_effort(None) is None


def test_every_tier_has_an_effort_band():
    from plan_select import FIT_TIERS

    assert set(TIER_EFFORT) == set(FIT_TIERS)


# --- the invariant that makes effort safe -----------------------------------

def test_effort_never_changes_eligibility_for_non_grok(tmp_path):
    """Non-Grok products: effort is a cost dial, not a tier promotion.

    Cranking a mid worker named Claude to xhigh must not make reasoner-only
    plans eligible; dropping a reasoner to none must not disqualify it.
    """
    plans = _tree(tmp_path)
    _plan(plans / "features" / "hard.md", preferred="reasoner")
    mid, reasoner = Worker("Claude Sonnet 5", "mid"), Worker("Claude Opus", "reasoner")

    for effort in (None, "none", "low", "high", "xhigh"):
        take, skip = plan_fit.triage(inventory_ready(plans, mid), mid, effort)
        assert take == [] and len(skip) == 1, f"mid claimed reasoner work at {effort}"

        take, _ = plan_fit.triage(inventory_ready(plans, reasoner), reasoner, effort)
        assert len(take) == 1, f"reasoner refused its own work at {effort}"


def test_grok_effort_sets_effective_tier_eligibility(tmp_path):
    """Grok family: reported effort changes Preferred eligibility."""
    from plan_select import worker_with_effort

    plans = _tree(tmp_path)
    _plan(plans / "features" / "hard.md", preferred="reasoner")
    _plan(plans / "features" / "mid.md", preferred="mid")
    _plan(plans / "features" / "front.md", preferred="frontier")

    low = worker_with_effort("Grok 4.6", "mid", "low")
    take, skip = plan_fit.triage(inventory_ready(plans, low), low, "low")
    assert {r.slug for r, _ in take} == {"mid"}
    assert {r.slug for r in skip} == {"hard", "front"}

    # medium → effective reasoner: good for reasoner Preferred; overqualified for mid-only
    med = worker_with_effort("Grok 4.6", "mid", "medium")
    take, skip = plan_fit.triage(inventory_ready(plans, med), med, "medium")
    assert {r.slug for r, _ in take} == {"hard"}
    assert "mid" in {r.slug for r in skip}

    # high/xhigh → effective frontier: only frontier Preferred (overqualified for mid/reasoner)
    high = worker_with_effort("Grok 4.6", "mid", "high")
    take, skip = plan_fit.triage(inventory_ready(plans, high), high, "high")
    assert {r.slug for r, _ in take} == {"front"}
    assert {r.slug for r in skip} == {"hard", "mid"}

    xh = worker_with_effort("Grok 4.5", "mid", "xhigh")  # coerced to frontier via map
    assert xh.tier == "frontier"

    unknown = worker_with_effort("Grok 4.6", "mid", None)
    take, skip = plan_fit.triage(inventory_ready(plans, unknown), unknown, None)
    assert {r.slug for r, _ in take} == {"mid"}
    assert "hard" in {r.slug for r in skip}


# --- triage / CLI -----------------------------------------------------------

def test_triage_splits_by_fit_and_deps(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "good.md", preferred="mid")
    _plan(plans / "features" / "named.md", preferred="Claude Sonnet 5")  # unknown → take
    _plan(plans / "features" / "hard.md", preferred="reasoner")
    _plan(plans / "features" / "tiny.md", preferred="small")
    _plan(plans / "features" / "blocked.md", preferred="mid", depends="nope")

    worker = Worker("Qwen3 32B", "mid")
    take, skip = plan_fit.triage(inventory_ready(plans, worker), worker, "high")
    assert {r.slug for r, _ in take} == {"good", "named"}
    assert {r.slug for r in skip} == {"hard", "tiny", "blocked"}
    # Every eligible plan carries actionable effort advice.
    assert all(a.should_change for _, a in take)


def test_skip_reasons_name_the_cause(tmp_path):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "hard.md", preferred="reasoner")
    _plan(plans / "features" / "blocked.md", preferred="mid", depends="nope")
    worker = Worker("m", "mid")
    recs = {r.slug: r for r in inventory_ready(plans, worker)}
    assert "underqualified" in plan_fit._reason(recs["hard"], worker)
    assert "deps UNMET: nope" in plan_fit._reason(recs["blocked"], worker)


def test_human_assigned_plans_are_skipped_regardless_of_fit(tmp_path):
    plans = _tree(tmp_path)
    # Perfect fit AND deps met, but assigned to a person → skip anyway.
    _plan(plans / "features" / "hers.md", preferred="mid", assignee="alice@corp.com")
    _plan(plans / "features" / "mine.md", preferred="mid", assignee="ai")
    worker = Worker("m", "mid")
    take, skip = plan_fit.triage(inventory_ready(plans, worker), worker, None)
    assert {r.slug for r, _ in take} == {"mine"}
    assert {r.slug for r in skip} == {"hers"}
    # The skip reason names the assignee and outranks any fit clause.
    reason = plan_fit._reason(skip[0], worker)
    assert "assigned to alice@corp.com" in reason


def test_human_assigned_skip_appears_in_json(tmp_path, capsys):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "hers.md", preferred="mid", assignee="bob")
    assert plan_fit.main(["--root", str(tmp_path), "--tier", "mid", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["eligible"] == []
    row = payload["skipped"][0]
    assert row["assignee"] == "bob" and row["agent_assignable"] is False


def test_cli_exit_codes_and_json(tmp_path, capsys):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "hard.md", preferred="reasoner")
    root = str(tmp_path)

    # Nothing eligible → exit 1, and the operator is told what would clear it.
    assert plan_fit.main(["--root", root, "--tier", "small"]) == 1
    assert "none for you" in capsys.readouterr().out

    # Eligible → exit 0 with machine-readable detail.
    assert plan_fit.main(["--root", root, "--tier", "reasoner",
                          "--effort", "low", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next"] == "features/hard.md"
    assert payload["eligible"][0]["effort"]["verdict"] == "underpowered"
    assert payload["worker"]["tier"] == "reasoner"


def test_cli_requires_an_identity_and_rejects_bad_effort(tmp_path, capsys):
    _tree(tmp_path)
    root = str(tmp_path)
    assert plan_fit.main(["--root", root]) == 2
    assert "say who you are" in capsys.readouterr().err
    assert plan_fit.main(["--root", root, "--tier", "mid", "--effort", "turbo"]) == 2
    assert "unknown effort" in capsys.readouterr().err


def test_cli_next_prints_only_a_path(tmp_path, capsys):
    plans = _tree(tmp_path)
    _plan(plans / "features" / "good.md", preferred="mid")
    assert plan_fit.main(["--root", str(tmp_path), "--tier", "mid", "--next"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("features/good.md") and "\n" not in out


def test_cli_is_read_only(tmp_path):
    """Triage must never claim, move, or lease — that is plan_select --claim."""
    plans = _tree(tmp_path)
    _plan(plans / "features" / "good.md", preferred="mid")
    before = {p.name for p in (plans / "features").iterdir()}

    plan_fit.main(["--root", str(tmp_path), "--tier", "mid"])

    assert {p.name for p in (plans / "features").iterdir()} == before
    assert list((plans / "in-progress").iterdir()) == []
    assert not (plans / ".leases").exists()
