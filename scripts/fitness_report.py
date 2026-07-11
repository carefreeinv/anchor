#!/usr/bin/env python3
"""Read-only claimed-vs-actual fitness report from the fleet metrics ledger.

Usage:
  python scripts/fitness_report.py
  python scripts/fitness_report.py --ledger var/fleet-metrics/outcomes.jsonl
  python scripts/fitness_report.py --json

Does not rewrite model-fitness.md — humans update prose from this output.
Rates with n < 5 are withheld (prints n only) so low sample noise is visible.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from fleet_metrics import OutcomeRecord, default_ledger_path, load_outcomes

MIN_N_FOR_RATE = 5


@dataclass
class ModelStats:
    model: str
    tier: str
    n: int = 0
    claim_parseable: int = 0
    unparseable: int = 0
    # Among parseable claims that assert success/should-work, how often verify exited 0
    claim_positive: int = 0
    claim_positive_and_verify_pass: int = 0
    # Tasks with a known verify exit
    verify_known: int = 0
    verify_pass: int = 0
    claimed_success: int = 0
    claimed_should_work: int = 0
    claimed_blocked: int = 0

    @property
    def unparseable_rate(self) -> float | None:
        if self.n < MIN_N_FOR_RATE:
            return None
        return self.unparseable / self.n

    @property
    def verify_pass_rate(self) -> float | None:
        if self.verify_known < MIN_N_FOR_RATE:
            return None
        return self.verify_pass / self.verify_known

    @property
    def claim_accuracy(self) -> float | None:
        """Share of positive claims that matched a passing verify (exit 0)."""
        if self.claim_positive < MIN_N_FOR_RATE:
            return None
        return self.claim_positive_and_verify_pass / self.claim_positive

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "tier": self.tier,
            "n": self.n,
            "unparseable": self.unparseable,
            "unparseable_rate": self.unparseable_rate,
            "verify_known": self.verify_known,
            "verify_pass": self.verify_pass,
            "verify_pass_rate": self.verify_pass_rate,
            "claim_positive": self.claim_positive,
            "claim_positive_and_verify_pass": self.claim_positive_and_verify_pass,
            "claim_accuracy": self.claim_accuracy,
            "claimed_success": self.claimed_success,
            "claimed_should_work": self.claimed_should_work,
            "claimed_blocked": self.claimed_blocked,
            "claimed_unparseable": self.unparseable,
        }


def aggregate(records: list[OutcomeRecord]) -> list[ModelStats]:
    buckets: dict[tuple[str, str], ModelStats] = {}
    for r in records:
        key = (r.model, r.tier)
        if key not in buckets:
            buckets[key] = ModelStats(model=r.model, tier=r.tier)
        s = buckets[key]
        s.n += 1
        if r.claimed == "unparseable":
            s.unparseable += 1
        else:
            s.claim_parseable += 1
        if r.claimed == "success":
            s.claimed_success += 1
        elif r.claimed == "should-work":
            s.claimed_should_work += 1
        elif r.claimed == "blocked":
            s.claimed_blocked += 1

        if r.actual_verify_exit is not None:
            s.verify_known += 1
            if r.actual_verify_exit == 0:
                s.verify_pass += 1

        # Positive claim accuracy: success/should-work vs actual exit 0
        if r.claimed in ("success", "should-work") and r.actual_verify_exit is not None:
            s.claim_positive += 1
            if r.actual_verify_exit == 0:
                s.claim_positive_and_verify_pass += 1

    return sorted(buckets.values(), key=lambda x: (-x.n, x.model, x.tier))


def _fmt_rate(rate: float | None, n: int) -> str:
    if rate is None:
        return f"n={n} (rate withheld; need n≥{MIN_N_FOR_RATE})"
    return f"{rate:.1%} (n={n})"


def format_table(stats: list[ModelStats]) -> str:
    if not stats:
        return "No outcome records found."
    lines = [
        "Claimed-vs-actual fitness report",
        f"(rates withheld when n < {MIN_N_FOR_RATE})",
        "",
        f"{'model':<28} {'tier':<12} {'n':>5}  claim-acc          verify-pass        unparseable",
        "-" * 100,
    ]
    for s in stats:
        lines.append(
            f"{s.model:<28} {s.tier:<12} {s.n:>5}  "
            f"{_fmt_rate(s.claim_accuracy, s.claim_positive):<18} "
            f"{_fmt_rate(s.verify_pass_rate, s.verify_known):<18} "
            f"{_fmt_rate(s.unparseable_rate, s.n)}"
        )
    lines.append("")
    lines.append(
        "claim-acc = positive claims (success|should-work) whose verify exit was 0; "
        "does not auto-edit model-fitness.md."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="path to outcomes.jsonl (default: ./var/fleet-metrics/outcomes.jsonl)",
    )
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args(argv)

    ledger = args.ledger if args.ledger is not None else default_ledger_path()
    records = load_outcomes(ledger)
    stats = aggregate(records)

    if args.json:
        payload = {
            "ledger": str(ledger),
            "min_n_for_rate": MIN_N_FOR_RATE,
            "models": [s.to_dict() for s in stats],
            "total_records": len(records),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"ledger: {ledger}  records: {len(records)}")
        print(format_table(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
