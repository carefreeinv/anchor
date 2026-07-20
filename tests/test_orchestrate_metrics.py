"""Integration: orchestrator writes one ledger row per finished task."""
from __future__ import annotations

from pathlib import Path

from fleet_metrics import load_outcomes
from orchestrate import execute_task


class FakeEndpoint:
    def __init__(self, replies):
        self.replies = list(replies)
        self.name = "fake-ep"
        self.model = "fake-model"
        self.tier = "mid"
        self.quirks: dict = {}  # real Endpoint always has one; budget gate reads it
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


class FakeFleet:
    def __init__(self, replies):
        self.ep = FakeEndpoint(replies)

    def pick(self, role):
        return self.ep


GOOD_OK = "did it\n## Result\nDone — success.\n## How to verify\npytest -q\n"
GOOD_HEDGE = "tweaked\n## Result\nThis should work.\n## How to verify\npytest -q\n"


def test_two_tasks_two_ledger_records(tmp_path: Path):
    ledger = tmp_path / "outcomes.jsonl"
    fleet = FakeFleet([GOOD_OK, GOOD_HEDGE])

    r1 = execute_task(
        "task one", "plan", fleet,
        verify_cmd="true", hold_on_fail=False,
        metrics_ledger=ledger, task_slug="fixture-run",
    )
    r2 = execute_task(
        "task two", "plan", fleet,
        verify_cmd="true", hold_on_fail=False,
        metrics_ledger=ledger, task_slug="fixture-run",
    )

    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    rows = load_outcomes(ledger)
    assert len(rows) == 2
    assert rows[0].claimed == "success"
    assert rows[0].actual_verify_exit == 0
    assert rows[0].model == "fake-model"
    assert rows[0].task_id.startswith("fixture-run:")
    assert rows[1].claimed == "should-work"
    assert rows[1].actual_verify_exit == 0
    # metadata only
    raw = ledger.read_text(encoding="utf-8")
    assert "task one" not in raw
    assert "YOUR SINGLE TASK" not in raw


def test_failed_verify_records_nonzero_exit(tmp_path: Path):
    ledger = tmp_path / "outcomes.jsonl"
    # Two attempts both fail verify → one final ledger row with exit 1
    fleet = FakeFleet([GOOD_OK, GOOD_OK])
    r = execute_task(
        "broken", "plan", fleet,
        verify_cmd="false", hold_on_fail=False,
        metrics_ledger=ledger,
    )
    assert r["status"] == "escalate"
    rows = load_outcomes(ledger)
    assert len(rows) == 1
    assert rows[0].claimed == "success"
    assert rows[0].actual_verify_exit == 1
