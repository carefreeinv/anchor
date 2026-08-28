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
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

ClaimedStatus = Literal["success", "should-work", "blocked", "unparseable"]
StopAction = Literal["continue", "escalate-tier", "human-report"]

DEFAULT_LEDGER_REL = Path("var/fleet-metrics/outcomes.jsonl")

# Escalation ladder for the harness-enforced stop condition (mythos-core rule 6,
# mirrored harness-side). Mirrors scripts/plan_select.py's FIT_TIERS /
# REGISTRY_TIER_TO_FIT — duplicated (not imported) so this module stays a leaf with
# no dependency on the plan-picker script.
FIT_TIER_LADDER: tuple[str, ...] = ("small", "mid", "reasoner", "frontier")
_REGISTRY_TIER_TO_FIT: dict[str, str] = {
    "swarm": "small",
    "executor": "mid",
    "executor-heavy": "mid",
    "reasoner": "reasoner",
    "frontier": "frontier",
    "detached": "mid",
}

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


def normalize_fit_tier(tier: str) -> str:
    """Map a registry tier (``executor``, ``reasoner``, ...) onto the fit ladder.

    Already-normalized fit tiers pass through unchanged. An unrecognized tier
    defaults to ``mid`` — the same "unlabeled is not reserved for a higher tier"
    default the plan-fit picker uses.
    """
    t = (tier or "mid").strip().lower()
    if t in FIT_TIER_LADDER:
        return t
    return _REGISTRY_TIER_TO_FIT.get(t, "mid")


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


@dataclass(frozen=True)
class StopDecision:
    """Verdict from :func:`should_stop` — the caller acts on ``action``, never
    re-derives it by re-reading the ledger itself."""

    action: StopAction
    reason: str
    evidence: tuple[OutcomeRecord, ...] = ()
    target_tier: str | None = None  # set only when action == "escalate-tier"


def _is_recorded_failure(rec: OutcomeRecord) -> bool:
    """A failed verification, or a scope-gate rejection (it is one — mythos-core
    rule 7). A handoff never reaches the ledger at all (``execute_task`` returns
    before recording one), so it never counts here — the "handoff doesn't count"
    constraint falls out of the existing recording behavior for free.
    """
    return rec.actual_verify_exit == 1 or rec.scope_verdict == "fail"


def should_stop(
    task_id: str,
    model: str,
    ledger: Sequence[OutcomeRecord],
    *,
    tier: str,
    tier_ladder: Sequence[str] = FIT_TIER_LADDER,
) -> StopDecision:
    """Harness-side mirror of mythos-core rule 6 ("two failed attempts → stop").

    Pure function over ledger records — no I/O, no dispatch, so a model flailing
    on its own attempt count no longer matters; this is the persistent backstop.
    Counting is per (task, model): fewer than two recorded failures → continue.
    Two failures at ``tier`` → escalate to the next rung of ``tier_ladder`` (the
    caller's *currently available* tiers, ascending — not always the full
    small→frontier ladder; a fleet with no frontier endpoint has "reasoner" as its
    top available tier). Two failures already at the top available tier →
    human-report: there is nowhere left to escalate to.
    """
    failures = tuple(
        rec for rec in ledger
        if rec.task_id == task_id and rec.model == model and _is_recorded_failure(rec)
    )
    if len(failures) < 2:
        return StopDecision("continue", "fewer than two recorded failures for this task+model")

    evidence = failures[-2:]
    norm = normalize_fit_tier(tier)
    ladder = list(tier_ladder)
    idx = ladder.index(norm) if norm in ladder else len(ladder) - 1
    if idx >= len(ladder) - 1:
        return StopDecision(
            "human-report",
            f"two failures at '{norm}', the top available tier — exhausted, not escalated",
            evidence,
        )
    return StopDecision(
        "escalate-tier",
        f"two failures at '{norm}' for model '{model}' — refusing a third dispatch, escalating",
        evidence,
        target_tier=ladder[idx + 1],
    )


def render_human_report(task: str, evidence: Sequence[OutcomeRecord]) -> str:
    """Structured report for top-tier exhaustion, in rule 6's shape: what was
    tried, what was observed, a hypothesis, and what a human/stronger model
    should look at — generated by the orchestrator even if the model never did.

    The ledger is metadata-only (no prompts/output stored), so "hypothesis" is
    honest about that limit rather than inventing a diagnosis it cannot support.
    """
    tried = "\n".join(
        f"- attempt {i}: model `{rec.model}` (tier `{rec.tier}`) at "
        f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(rec.timestamp))}"
        for i, rec in enumerate(evidence, start=1)
    )
    observed = "\n".join(
        f"- attempt {i}: verify_exit={rec.actual_verify_exit!r}, "
        f"scope_verdict={rec.scope_verdict!r}, claimed={rec.claimed!r}"
        for i, rec in enumerate(evidence, start=1)
    )
    return (
        f"# Human report: {task.strip()[:200]}\n\n"
        "## Tried\n"
        f"{tried}\n\n"
        "## Observed\n"
        f"{observed}\n\n"
        "## Hypothesis\n"
        "None — the outcome ledger is metadata-only (no prompts or output stored), "
        "so the harness has no basis for a diagnosis. A human or stronger model "
        "needs the actual task output to form one.\n\n"
        "## What a stronger model or human should look at\n"
        "- The task text above, and the two failing dispatches' actual output "
        "(not retained here by design).\n"
        "- Every tier this fleet has configured has now failed this task twice; "
        "no further automatic escalation is possible.\n"
    )


# --- executor -> orchestrator footer contract (mythos-core rule 8) -----------
# Only the structured footer crosses the boundary back to the coordinator; the
# full transcript is archived separately (scripts/orchestrate.py) for audit.
# Shares this module with the claimed-vs-actual ledger's own (looser, 2-section)
# footer check above rather than a second, drifting implementation — this one
# is the strict 3-section contract mythos-core rule 8 actually specifies.

FOOTER_SECTIONS: tuple[str, ...] = ("Result", "How to verify", "Deferred / concerns")
DEFAULT_FOOTER_MAX_LINES = 60
FOOTER_TRUNCATION_MARKER = "[truncated by harness]"

# Any top-level '##' heading — used both to find the three required ones and to
# bound each one's content at the next heading of any kind. Whitespace after
# '##' is optional (tolerates '##Result' as well as '##  Result') but a third
# '#' is not — '### h3' never matches, so real subheadings inside a section's
# body don't get mistaken for a new top-level boundary.
_ANY_HEADING_RE = re.compile(r"^[ \t]*##(?!#)[ \t]*(.+?)[ \t]*$", re.MULTILINE)


def _normalize_heading(text: str) -> str:
    """Case/whitespace-insensitive key: collapses runs of whitespace, then the
    spacing around a slash, so 'Deferred / concerns', 'Deferred/concerns', and
    'DEFERRED  /  Concerns' all match the same canonical section."""
    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    return re.sub(r"\s*/\s*", "/", collapsed)


_FOOTER_CANONICAL_BY_KEY: dict[str, str] = {
    _normalize_heading(section): section for section in FOOTER_SECTIONS
}


@dataclass(frozen=True)
class FooterExtraction:
    """Result of :func:`extract_footer`. ``missing`` names the required
    sections absent when ``ok`` is False; empty otherwise."""

    ok: bool
    footer_text: str = ""
    missing: tuple[str, ...] = ()
    truncated: bool = False


def extract_footer(text: str, *, max_lines: int = DEFAULT_FOOTER_MAX_LINES) -> FooterExtraction:
    """Extract the mandatory three-section footer from raw executor output.

    Tolerant of case/spacing drift in the heading text. When a heading appears
    more than once (an executor may quote the template while reasoning before
    producing its real answer), the LAST occurrence wins — each section's
    content runs from its heading to the next '##' heading of any kind, or EOF.
    All three sections are required; missing any is a rejection naming which,
    never a partial acceptance. The reconstructed footer is capped at
    ``max_lines`` total lines, truncated with an explicit marker — long enough
    for a legitimate footer, short enough that smuggling a full transcript
    inside '## Result' doesn't work.
    """
    if not text:
        return FooterExtraction(ok=False, missing=FOOTER_SECTIONS)

    matches = list(_ANY_HEADING_RE.finditer(text))
    last_by_section: dict[str, re.Match] = {}
    for m in matches:
        canon = _FOOTER_CANONICAL_BY_KEY.get(_normalize_heading(m.group(1)))
        if canon:
            last_by_section[canon] = m  # later matches overwrite earlier ones

    missing = tuple(section for section in FOOTER_SECTIONS if section not in last_by_section)
    if missing:
        return FooterExtraction(ok=False, missing=missing)

    starts = [m.start() for m in matches]

    def content_after(m: re.Match) -> str:
        nxt = next((s for s in starts if s > m.start()), len(text))
        return text[m.end():nxt].strip("\n")

    parts = [
        f"## {section}\n{content_after(last_by_section[section])}".rstrip()
        for section in FOOTER_SECTIONS
    ]
    footer_text = "\n\n".join(parts).strip("\n") + "\n"

    lines = footer_text.splitlines()
    truncated = len(lines) > max_lines
    if truncated:
        footer_text = "\n".join(lines[:max_lines]) + f"\n{FOOTER_TRUNCATION_MARKER}\n"

    return FooterExtraction(ok=True, footer_text=footer_text, truncated=truncated)
