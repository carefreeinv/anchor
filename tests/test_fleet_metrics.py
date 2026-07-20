"""Unit tests for scripts/fleet_metrics.py — claim parser + JSONL ledger."""
from __future__ import annotations

import json
from pathlib import Path

from fleet_metrics import (
    OutcomeRecord,
    append_outcome,
    load_outcomes,
    parse_claimed_status,
    record_task_outcome,
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
