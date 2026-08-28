"""Unit tests for scripts/fleet_metrics.py — claim parser + JSONL ledger."""
from __future__ import annotations

import json
from pathlib import Path

from fleet_metrics import (
    FIT_TIER_LADDER,
    FOOTER_TRUNCATION_MARKER,
    OutcomeRecord,
    append_outcome,
    extract_footer,
    load_outcomes,
    normalize_fit_tier,
    parse_claimed_status,
    record_task_outcome,
    render_human_report,
    should_stop,
    task_id_for,
)


def test_parse_clean_success_footer():
    text = (
        "Implemented the endpoint.\n"
        "## Result\n"
        "Done — success.\n"
        "## How to verify\n"
        "pytest -q\n"
        "## Deferred / concerns\n"
        "None\n"
    )
    assert parse_claimed_status(text) == "success"


def test_parse_hedged_should_work():
    text = (
        "Changed the handler.\n"
        "## Result\n"
        "This should work once the fixture is in place.\n"
        "## How to verify\n"
        "pytest tests/test_foo.py\n"
    )
    assert parse_claimed_status(text) == "should-work"


def test_parse_missing_footer_unparseable():
    assert parse_claimed_status("I fixed it, trust me.") == "unparseable"
    assert parse_claimed_status("") == "unparseable"


def test_parse_partial_footer_unparseable():
    # Has ## Result but not ## How to verify
    text = "## Result\nok\n"
    assert parse_claimed_status(text) == "unparseable"


def test_parse_blocked_claim():
    text = (
        "## Result\n"
        "Blocked: needs human decision on schema.\n"
        "## How to verify\n"
        "n/a\n"
    )
    assert parse_claimed_status(text) == "blocked"


def test_parse_empty_result_body_unparseable():
    text = "## Result\n\n## How to verify\npytest -q\n"
    assert parse_claimed_status(text) == "unparseable"


def test_parse_unverified_marker_is_should_work():
    text = (
        "## Result\n"
        "Looks good (unverified).\n"
        "## How to verify\n"
        "manual check\n"
    )
    assert parse_claimed_status(text) == "should-work"


def test_append_outcome_jsonl(tmp_path: Path):
    ledger = tmp_path / "var" / "fleet-metrics" / "outcomes.jsonl"
    rec = OutcomeRecord(
        model="Qwen3-32B",
        tier="executor",
        task_id="abc123",
        claimed="success",
        actual_verify_exit=0,
        scope_verdict="pass",
        timestamp=1.0,
        tokens=100,
        endpoint="h100-executor",
        task_slug="demo",
    )
    append_outcome(rec, ledger)
    append_outcome(rec, ledger)
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["model"] == "Qwen3-32B"
    assert row["claimed"] == "success"
    assert row["actual_verify_exit"] == 0
    # No task body / prompt fields
    assert "task" not in row
    assert "prompt" not in row
    assert "output" not in row


def test_record_task_outcome_pairs_claim_and_exit(tmp_path: Path):
    ledger = tmp_path / "outcomes.jsonl"
    out = (
        "## Result\n"
        "should work\n"
        "## How to verify\n"
        "pytest -q\n"
    )
    rec = record_task_outcome(
        output=out,
        verify_exit=1,
        model="fake-model",
        tier="mid",
        task="Add the endpoint",
        ledger_path=ledger,
        scope_verdict=None,
        endpoint="fake-ep",
        task_slug="claimed-vs-actual-scoring",
        timestamp=42.0,
    )
    assert rec.claimed == "should-work"
    assert rec.actual_verify_exit == 1
    assert rec.task_id.startswith("claimed-vs-actual-scoring:")
    loaded = load_outcomes(ledger)
    assert len(loaded) == 1
    assert loaded[0].claimed == "should-work"
    assert loaded[0].timestamp == 42.0


def test_task_id_stable_and_content_free():
    a = task_id_for("Do the thing")
    b = task_id_for("Do the thing")
    c = task_id_for("Do something else")
    assert a == b
    assert a != c
    assert "Do the thing" not in a


# --- should_stop: harness-enforced mirror of mythos-core rule 6 --------------


def _rec(*, model="fake-model", task_id="t1", verify_exit=1, scope_verdict=None,
         timestamp=1.0, tier="mid", claimed="unparseable") -> OutcomeRecord:
    return OutcomeRecord(
        model=model, tier=tier, task_id=task_id, claimed=claimed,
        actual_verify_exit=verify_exit, scope_verdict=scope_verdict, timestamp=timestamp,
    )


def test_should_stop_continues_with_one_failure():
    ledger = [_rec()]
    decision = should_stop("t1", "fake-model", ledger, tier="mid")
    assert decision.action == "continue"


def test_should_stop_escalates_after_two_failures():
    ledger = [_rec(timestamp=1.0), _rec(timestamp=2.0)]
    decision = should_stop("t1", "fake-model", ledger, tier="mid")
    assert decision.action == "escalate-tier"
    assert decision.target_tier == "reasoner"
    assert len(decision.evidence) == 2


def test_should_stop_human_report_at_top_available_tier():
    ledger = [_rec(timestamp=1.0), _rec(timestamp=2.0)]
    # tier_ladder ends at "reasoner" for this fleet — no frontier endpoint configured.
    decision = should_stop("t1", "fake-model", ledger, tier="reasoner",
                           tier_ladder=("small", "mid", "reasoner"))
    assert decision.action == "human-report"
    assert decision.target_tier is None
    assert len(decision.evidence) == 2


def test_should_stop_human_report_at_true_top_of_default_ladder():
    ledger = [_rec(timestamp=1.0), _rec(timestamp=2.0)]
    decision = should_stop("t1", "fake-model", ledger, tier="frontier")
    assert decision.action == "human-report"
    assert decision.target_tier is None


def test_should_stop_counts_a_scope_gate_rejection_as_a_failure():
    ledger = [
        _rec(verify_exit=None, scope_verdict="fail", timestamp=1.0),
        _rec(verify_exit=None, scope_verdict="fail", timestamp=2.0),
    ]
    decision = should_stop("t1", "fake-model", ledger, tier="mid")
    assert decision.action == "escalate-tier"


def test_should_stop_ignores_rows_that_are_not_recorded_failures():
    """A handoff never reaches the ledger (execute_task returns before recording
    one), and a no-verify-cmd success is not a failure either — neither counts."""
    ledger = [
        _rec(verify_exit=None, scope_verdict=None, timestamp=1.0),
        _rec(verify_exit=None, scope_verdict="pass", timestamp=2.0),
        _rec(verify_exit=0, scope_verdict="pass", timestamp=3.0),
    ]
    decision = should_stop("t1", "fake-model", ledger, tier="mid")
    assert decision.action == "continue"


def test_should_stop_is_scoped_to_the_same_task_and_model():
    ledger = [
        _rec(model="fake-model", task_id="t1", timestamp=1.0),
        _rec(model="fake-model", task_id="t1", timestamp=2.0),
    ]
    assert should_stop("t2", "fake-model", ledger, tier="mid").action == "continue"
    assert should_stop("t1", "other-model", ledger, tier="mid").action == "continue"


def test_normalize_fit_tier_maps_registry_tiers():
    assert normalize_fit_tier("executor") == "mid"
    assert normalize_fit_tier("executor-heavy") == "mid"
    assert normalize_fit_tier("swarm") == "small"
    assert normalize_fit_tier("reasoner") == "reasoner"
    assert normalize_fit_tier("frontier") == "frontier"
    assert normalize_fit_tier("detached") == "mid"
    assert normalize_fit_tier("mid") == "mid"  # already normalized
    assert normalize_fit_tier("made-up-tier") == "mid"  # unlabeled default
    assert normalize_fit_tier("") == "mid"


def test_fit_tier_ladder_is_the_canonical_four_tiers():
    assert FIT_TIER_LADDER == ("small", "mid", "reasoner", "frontier")


def test_render_human_report_carries_task_and_evidence():
    evidence = (
        _rec(model="m1", tier="reasoner", verify_exit=1, timestamp=1.0, claimed="should-work"),
        _rec(model="m1", tier="reasoner", scope_verdict="fail", verify_exit=None,
             timestamp=2.0, claimed="blocked"),
    )
    report = render_human_report("Fix the race condition in the queue", evidence)
    assert "Fix the race condition in the queue" in report
    assert "## Tried" in report
    assert "## Observed" in report
    assert "## Hypothesis" in report
    assert "m1" in report
    assert "reasoner" in report
    assert "verify_exit=1" in report
    assert "scope_verdict='fail'" in report


# --- extract_footer: the executor -> orchestrator boundary contract ----------


CLEAN_FOOTER = (
    "Did the thing, here is some reasoning the coordinator should never see.\n"
    "## Result\n"
    "Implemented the widget.\n"
    "## How to verify\n"
    "pytest tests/test_widget.py -q\n"
    "## Deferred / concerns\n"
    "None.\n"
)


def test_extract_footer_clean_input():
    extraction = extract_footer(CLEAN_FOOTER)
    assert extraction.ok
    assert not extraction.truncated
    assert "## Result" in extraction.footer_text
    assert "Implemented the widget." in extraction.footer_text
    assert "## How to verify" in extraction.footer_text
    assert "pytest tests/test_widget.py -q" in extraction.footer_text
    assert "## Deferred / concerns" in extraction.footer_text
    assert "None." in extraction.footer_text
    # The rambling preamble before the first heading never crosses the boundary.
    assert "reasoning the coordinator" not in extraction.footer_text


def test_extract_footer_tolerates_case_and_spacing_drift():
    sloppy = (
        "##  result  \n"
        "ok\n"
        "##HOW TO VERIFY\n"
        "n/a\n"
        "##   Deferred/Concerns\n"
        "none\n"
    )
    extraction = extract_footer(sloppy)
    assert extraction.ok
    assert "## Result" in extraction.footer_text
    assert "## How to verify" in extraction.footer_text
    assert "## Deferred / concerns" in extraction.footer_text


def test_extract_footer_missing_section_is_named():
    missing_deferred = (
        "## Result\nok\n"
        "## How to verify\npytest -q\n"
    )
    extraction = extract_footer(missing_deferred)
    assert not extraction.ok
    assert extraction.missing == ("Deferred / concerns",)

    missing_all = "I fixed it, trust me."
    extraction2 = extract_footer(missing_all)
    assert not extraction2.ok
    assert extraction2.missing == ("Result", "How to verify", "Deferred / concerns")


def test_extract_footer_empty_text_is_missing_all():
    extraction = extract_footer("")
    assert not extraction.ok
    assert extraction.missing == ("Result", "How to verify", "Deferred / concerns")


def test_extract_footer_duplicate_heading_last_occurrence_wins():
    duplicated = (
        "## Result\n"
        "draft attempt, ignore this\n"
        "## How to verify\n"
        "draft, ignore\n"
        "## Result\n"
        "final answer\n"
        "## How to verify\n"
        "pytest -q\n"
        "## Deferred / concerns\n"
        "none\n"
    )
    extraction = extract_footer(duplicated)
    assert extraction.ok
    assert "final answer" in extraction.footer_text
    assert "draft attempt" not in extraction.footer_text
    assert "draft, ignore" not in extraction.footer_text


def test_extract_footer_caps_oversize_output():
    huge_body = "\n".join(f"line {i}" for i in range(200))
    oversized = f"## Result\n{huge_body}\n## How to verify\npytest -q\n## Deferred / concerns\nnone\n"
    extraction = extract_footer(oversized, max_lines=10)
    assert extraction.ok
    assert extraction.truncated
    assert len(extraction.footer_text.splitlines()) <= 11  # cap + marker line
    assert FOOTER_TRUNCATION_MARKER in extraction.footer_text
    assert "line 199" not in extraction.footer_text  # the tail never survives


def test_extract_footer_under_cap_is_not_truncated():
    extraction = extract_footer(CLEAN_FOOTER, max_lines=60)
    assert not extraction.truncated
    assert FOOTER_TRUNCATION_MARKER not in extraction.footer_text
