#!/usr/bin/env python3
"""Claimed-vs-actual fleet outcome ledger.

Parses an executor's ``## Result`` footer claim, pairs it with the actual
verification exit code (and optional scope-gate verdict), and appends a
metadata-only JSONL record under ``var/fleet-metrics/outcomes.jsonl``.

Never stores task content or prompts — model reliability signal only.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

ClaimedStatus = Literal["success", "should-work", "blocked", "unparseable"]

DEFAULT_LEDGER_REL = Path("var/fleet-metrics/outcomes.jsonl")

# Section from ## Result until the next ## heading (or EOF).
RESULT_SECTION_RE = re.compile(
    r"^##\s+Result\s*$([\s\S]*?)(?=^##\s|\Z)",
    re.MULTILINE | re.IGNORECASE,
)
# Required footer headings (same contract as anchor_client.has_required_footer).
FOOTER_MARKERS = ("## Result", "## How to verify")

# Hedged / "should work" language (checked before hard success).
SHOULD_WORK_RE = re.compile(
    r"\b("
    r"should\s+work|should\s+pass|should\s+be\s+(?:fine|ok|okay)|"
    r"ought\s+to\s+work|likely|probably|presumably|"
    r"I\s+believe|I\s+think|seems\s+to|appears\s+to|"
    r"unverified|hopefully|fingers\s+crossed"
    r")\b",
    re.IGNORECASE,
)
BLOCKED_RE = re.compile(
    r"\b("
    r"blocked|cannot\s+proceed|can'?t\s+proceed|stuck|"
    r"escalate|escalat(?:e|ion)|hold(?:ing)?\s+(?:for|on)|"
    r"needs?\s+(?:human|planner|bigger\s+model)|"
    r"out\s+of\s+scope|refusing|will\s+not\s+proceed"
    r")\b",
    re.IGNORECASE,
)
SUCCESS_RE = re.compile(
    r"\b("
    r"success|succeeded|done|complete[d]?|ok|okay|passed|pass|"
    r"works|working|fixed|implemented|shipped|green|all\s+good|"
    r"verified|ready"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OutcomeRecord:
    """One ledger row — metadata only (no prompts / task bodies)."""

    model: str
    tier: str
    task_id: str
    claimed: ClaimedStatus
    actual_verify_exit: int | None
    scope_verdict: str | None
    timestamp: float
    # "pass" / "fail" / None when the run had no role enforcement. A task can pass
    # verify while still writing outside its role's allowed paths — without this the
    # ledger would score that run as an accurate claim.
    role_verdict: str | None = None
    tokens: int | None = None
    endpoint: str | None = None
    task_slug: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def task_id_for(task: str, *, slug: str | None = None) -> str:
    """Stable short hash of the task text (never store the text itself)."""
    h = hashlib.sha256(task.strip().encode("utf-8")).hexdigest()[:16]
    return f"{slug}:{h}" if slug else h


def has_footer_markers(text: str) -> bool:
    return all(m in text for m in FOOTER_MARKERS)


def extract_result_body(text: str) -> str | None:
    """Return the ## Result section body, or None if the heading is missing."""
    m = RESULT_SECTION_RE.search(text or "")
    if not m:
        return None
    return m.group(1).strip()


def parse_claimed_status(output: str) -> ClaimedStatus:
    """Classify the executor's claimed outcome from its footer.

    Tolerant but honest: missing/malformed footers → ``unparseable`` (signal).
    """
    if not output or not has_footer_markers(output):
        return "unparseable"

    body = extract_result_body(output)
    if body is None:
        return "unparseable"
    if not body:
        # Heading present but empty — still unparseable as a claim.
        return "unparseable"

    if BLOCKED_RE.search(body):
        return "blocked"
    if SHOULD_WORK_RE.search(body):
        return "should-work"
    if SUCCESS_RE.search(body):
        return "success"
    # Footer exists but claim is gibberish / non-committal.
    return "unparseable"


def default_ledger_path(project_root: Path | None = None) -> Path:
    root = project_root if project_root is not None else Path.cwd()
    return root / DEFAULT_LEDGER_REL


def append_outcome(record: OutcomeRecord, ledger_path: Path) -> None:
    """Append one JSON object as a line. Creates parent dirs as needed."""
    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.to_json_dict(), ensure_ascii=False, separators=(",", ":"))
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def record_task_outcome(
    *,
    output: str | None,
    verify_exit: int | None,
    model: str,
    tier: str,
    task: str,
    ledger_path: Path | None = None,
    project_root: Path | None = None,
    scope_verdict: str | None = None,
    role_verdict: str | None = None,
    tokens: int | None = None,
    endpoint: str | None = None,
    task_slug: str | None = None,
    timestamp: float | None = None,
) -> OutcomeRecord:
    """Build + append an outcome record; return it for callers/tests."""
    rec = OutcomeRecord(
        model=model or "unknown",
        tier=tier or "unknown",
        task_id=task_id_for(task, slug=task_slug),
        claimed=parse_claimed_status(output or ""),
        actual_verify_exit=verify_exit,
        scope_verdict=scope_verdict,
        role_verdict=role_verdict,
        timestamp=float(timestamp if timestamp is not None else time.time()),
        tokens=tokens,
        endpoint=endpoint,
        task_slug=task_slug,
    )
    path = ledger_path if ledger_path is not None else default_ledger_path(project_root)
    append_outcome(rec, path)
    return rec


def load_outcomes(ledger_path: Path) -> list[OutcomeRecord]:
    """Read a JSONL ledger into OutcomeRecord rows (skips blank/corrupt lines)."""
    path = Path(ledger_path)
    if not path.is_file():
        return []
    out: list[OutcomeRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            out.append(
                OutcomeRecord(
                    model=str(raw.get("model", "unknown")),
                    tier=str(raw.get("tier", "unknown")),
                    task_id=str(raw.get("task_id", "")),
                    claimed=raw.get("claimed", "unparseable"),  # type: ignore[arg-type]
                    actual_verify_exit=raw.get("actual_verify_exit"),
                    scope_verdict=raw.get("scope_verdict"),
                    role_verdict=raw.get("role_verdict"),
                    timestamp=float(raw.get("timestamp", 0.0)),
                    tokens=raw.get("tokens"),
                    endpoint=raw.get("endpoint"),
                    task_slug=raw.get("task_slug"),
                )
            )
        except (TypeError, ValueError):
            continue
    return out
