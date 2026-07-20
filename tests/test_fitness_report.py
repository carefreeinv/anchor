"""Unit tests for scripts/fitness_report.py aggregation."""
from __future__ import annotations

import json
from pathlib import Path

from fitness_report import MIN_N_FOR_RATE, aggregate, format_table, main
from fleet_metrics import OutcomeRecord, append_outcome


def _rec(model: str, claimed: str, exit_code: int | None, i: int = 0) -> OutcomeRecord:
    return OutcomeRecord(
        model=model,
        tier="mid",
        task_id=f"t{i}",
        claimed=claimed,  # type: ignore[arg-type]
        actual_verify_exit=exit_code,
        scope_verdict=None,
        timestamp=float(i),
    )


def test_aggregate_withholds_rates_under_min_n():
    rows = [_rec("m1", "success", 0, i) for i in range(3)]
    stats = aggregate(rows)
    assert len(stats) == 1
    assert stats[0].n == 3
    assert stats[0].claim_accuracy is None
    assert stats[0].verify_pass_rate is None
    assert "withheld" in format_table(stats)


def test_aggregate_rates_at_min_n():
    rows = []
    for i in range(MIN_N_FOR_RATE):
        # 4 success+pass, 1 should-work+fail
        if i < 4:
            rows.append(_rec("m1", "success", 0, i))
        else:
            rows.append(_rec("m1", "should-work", 1, i))
    stats = aggregate(rows)
    s = stats[0]
    assert s.n == 5
    assert s.claim_accuracy == 0.8
    assert s.verify_pass_rate == 0.8
    assert s.unparseable_rate == 0.0


def test_cli_json_and_table(tmp_path: Path, capsys):
    ledger = tmp_path / "outcomes.jsonl"
    for i in range(2):
        append_outcome(_rec("Qwen", "success", 0, i), ledger)
    append_outcome(_rec("Qwen", "unparseable", 1, 9), ledger)

    assert main(["--ledger", str(ledger), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_records"] == 3
    assert payload["models"][0]["model"] == "Qwen"
    assert payload["models"][0]["unparseable"] == 1

    assert main(["--ledger", str(ledger)]) == 0
    out = capsys.readouterr().out
    assert "Qwen" in out
    assert "records: 3" in out
