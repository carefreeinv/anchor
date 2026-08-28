"""Integration: orchestrator writes one ledger row per finished task."""
from __future__ import annotations

from pathlib import Path

from fleet_metrics import load_outcomes, record_task_outcome
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


# --- harness-enforced stop condition: refuse a third dispatch, escalate a tier --
# The MAX_ATTEMPTS loop above only ever runs two attempts *within one call*, so it
# can't reach a "third dispatch" on its own — these tests simulate a resumed
# invocation by seeding the ledger with two failures from an earlier run before
# execute_task's first attempt of *this* call.


class RecordingTieredEndpoint:
    def __init__(self, name, model, tier, replies):
        self.name = name
        self.model = model
        self.tier = tier
        self.quirks: dict = {}
        self.replies = list(replies)
        self.calls = 0
        self.prompts: list[str] = []

    def chat(self, messages, **kwargs):
        self.calls += 1
        self.prompts.append(messages[-1]["content"])
        return self.replies.pop(0)


class TieredFleet:
    """fleet.pick() always returns the tier this run would normally dispatch to;
    escalation reads .endpoints directly, same as the real Fleet."""

    def __init__(self, endpoints, default_ep):
        self.endpoints = endpoints
        self._default = default_ep

    def pick(self, role):
        return self._default


def _seed_two_failures(ledger, *, task, model, tier):
    for i in range(2):
        record_task_outcome(
            output="## Result\nfailed\n## How to verify\nn/a\n",
            verify_exit=1, model=model, tier=tier, task=task,
            ledger_path=ledger, timestamp=float(i),
        )


def test_third_dispatch_to_same_model_is_refused_and_escalates_with_evidence(tmp_path: Path):
    ledger = tmp_path / "outcomes.jsonl"
    mid_ep = RecordingTieredEndpoint("mid-ep", "fake-model-mid", "mid", [])
    reasoner_ep = RecordingTieredEndpoint("reasoner-ep", "fake-model-reasoner", "reasoner",
                                          [GOOD_OK])
    fleet = TieredFleet([mid_ep, reasoner_ep], mid_ep)

    task = "do it"
    _seed_two_failures(ledger, task=task, model="fake-model-mid", tier="mid")

    result = execute_task(task, "plan", fleet, verify_cmd=None, hold_on_fail=False,
                          metrics_ledger=ledger)

    assert mid_ep.calls == 0  # third dispatch to the same model refused
    assert reasoner_ep.calls == 1
    assert result["status"] == "ok"
    assert "ESCALATION" in reasoner_ep.prompts[0]
    assert "fake-model-mid" in reasoner_ep.prompts[0]


def test_escalate_tier_with_uninspectable_fleet_falls_back_to_escalate_status(tmp_path: Path):
    """A fleet stub with no ``.endpoints`` (like this file's own FakeFleet) can't be
    searched for an escalation target — available_fit_tiers conservatively assumes
    the full ladder is still open, should_stop says escalate, but there is no
    endpoint to actually escalate to. Report up rather than silently continuing."""
    ledger = tmp_path / "outcomes.jsonl"
    fleet = FakeFleet([])  # no .endpoints attribute at all

    task = "do it"
    _seed_two_failures(ledger, task=task, model="fake-model", tier="mid")

    result = execute_task(task, "plan", fleet, verify_cmd=None, hold_on_fail=False,
                          metrics_ledger=ledger)

    assert fleet.ep.calls == 0
    assert result["status"] == "escalate"
    assert result["target_tier"] == "reasoner"


def test_two_failures_at_top_available_tier_produces_a_human_report(tmp_path: Path):
    ledger = tmp_path / "outcomes.jsonl"
    ep = RecordingTieredEndpoint("frontier-ep", "fake-model-frontier", "frontier", [])
    fleet = TieredFleet([ep], ep)

    task = "hard task"
    _seed_two_failures(ledger, task=task, model="fake-model-frontier", tier="frontier")

    result = execute_task(task, "plan", fleet, verify_cmd=None, hold_on_fail=False,
                          metrics_ledger=ledger)

    assert ep.calls == 0  # the orchestrator generates the report itself
    assert result["status"] == "human-report"
    assert "## Tried" in result["report"]
    assert "## Observed" in result["report"]
    assert "hard task" in result["report"]


def test_an_already_exhausted_escalated_tier_reaches_human_report_not_a_third_hop(
    tmp_path: Path,
):
    """Regression: fleet.pick("executor") always returns the *base* (mid) endpoint,
    so should_stop must be re-checked against each hop, not just the base tier —
    otherwise a reasoner tier that is itself exhausted would be re-escalated to
    forever from a base tier permanently stuck at 2 failures, never reaching
    human-report and never refusing a further dispatch to reasoner."""
    ledger = tmp_path / "outcomes.jsonl"
    mid_ep = RecordingTieredEndpoint("mid-ep", "fake-model-mid", "mid", [])
    reasoner_ep = RecordingTieredEndpoint("reasoner-ep", "fake-model-reasoner", "reasoner", [])
    fleet = TieredFleet([mid_ep, reasoner_ep], mid_ep)  # pick("executor") always → mid_ep

    task = "chronically hard task"
    _seed_two_failures(ledger, task=task, model="fake-model-mid", tier="mid")
    _seed_two_failures(ledger, task=task, model="fake-model-reasoner", tier="reasoner")

    result = execute_task(task, "plan", fleet, verify_cmd=None, hold_on_fail=False,
                          metrics_ledger=ledger)

    assert mid_ep.calls == 0
    assert reasoner_ep.calls == 0  # already exhausted too — never re-dispatched
    assert result["status"] == "human-report"
