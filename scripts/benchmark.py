#!/usr/bin/env python3
"""Benchmark YOUR workload across fleet endpoints — playbook move #5:
know with your own numbers which tasks deserve which tier.

Tasks file: JSONL, one per line:
  {"id": "t1", "prompt": "…", "check": "regex the output must match", "roles": ["executor"]}

Usage:
  python benchmark.py tasks.jsonl                     # all endpoints
  python benchmark.py tasks.jsonl --tier swarm reasoner
  python benchmark.py tasks.jsonl -o results.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

from anchor_client import Fleet, has_required_footer, load_prompt


def run_task(ep, task: dict, system: str) -> dict:
    t0 = time.time()
    try:
        out = ep.chat([{"role": "system", "content": system},
                       {"role": "user", "content": task["prompt"]}],
                      thinking=task.get("thinking", False), max_tokens=4096)
        err = ""
    except Exception as e:
        out, err = "", str(e)
    dt = time.time() - t0
    passed = bool(out) and not err
    if passed and task.get("check"):
        passed = re.search(task["check"], out, re.DOTALL) is not None
    return {"endpoint": ep.name, "model": ep.model, "tier": ep.tier, "task": task["id"],
            "pass": passed, "footer_ok": has_required_footer(out), "seconds": round(dt, 1),
            "chars": len(out), "error": err[:200]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tasks", help="JSONL task file")
    ap.add_argument("--tier", nargs="*", help="limit to these tiers")
    ap.add_argument("-o", "--out", default="benchmark_results.csv")
    ap.add_argument("--registry", default=None)
    args = ap.parse_args()

    fleet = Fleet(args.registry) if args.registry else Fleet()
    eps = [e for e in fleet.endpoints if not args.tier or e.tier in args.tier]
    lines = Path(args.tasks).read_text(encoding="utf-8").splitlines()
    tasks = [json.loads(line) for line in lines if line.strip()]
    system = load_prompt("anchor/system-prompts/mythos-core.md")

    rows = []
    for ep in eps:
        for task in tasks:
            r = run_task(ep, task, system)
            rows.append(r)
            print(f"{r['endpoint']:>18} {r['task']:>8} "
                  f"{'PASS' if r['pass'] else 'FAIL':4} {r['seconds']:6}s", file=sys.stderr)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    # Per-endpoint summary: pass rate + median latency — the routing table, from your data.
    print(f"\n{'endpoint':>18} {'tier':>14} {'pass':>6} {'median_s':>9}")
    for ep in eps:
        mine = [r for r in rows if r["endpoint"] == ep.name]
        rate = sum(r["pass"] for r in mine) / len(mine)
        lat = sorted(r["seconds"] for r in mine)[len(mine) // 2]
        print(f"{ep.name:>18} {ep.tier:>14} {rate:>5.0%} {lat:>8}s")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
