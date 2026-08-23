"""Integration tests for the executor -> orchestrator footer-only relay
(mythos-core rule 8): the coordinator sees at most the extracted footer, the
full raw transcript is archived separately, and a malformed reply gets
exactly one corrective retry before escalating."""
from __future__ import annotations

from pathlib import Path

from orchestrate import execute_task


class RecordingEndpoint:
    def __init__(self, replies, quirks=None):
        self.replies = list(replies)
        self.name = "fake-ep"
        self.model = "fake-model"
        self.tier = "mid"
        self.calls = 0
        self.quirks = quirks or {}

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


class RecordingFleet:
    def __init__(self, replies, quirks=None):
        self.ep = RecordingEndpoint(replies, quirks=quirks)

    def pick(self, role):
        return self.ep


VERBOSE_OUTPUT = (
    "Let me think this through step by step. First I looked at the existing "
    "code, then I considered three different approaches before settling on "
    "one, and here is a long trace of my reasoning that the coordinator "
    "should never have to read back into its own context window, because "
    "none of it is the actual answer, just the scratch work that got there.\n"
    "## Result\n"
    "Implemented the widget.\n"
    "## How to verify\n"
    "pytest tests/test_widget.py -q\n"
    "## Deferred / concerns\n"
    "None.\n"
)

MALFORMED_OUTPUT = "I fixed it, trust me, no need for a footer here."


def test_coordinator_sees_only_the_footer_not_the_rambling(tmp_path: Path):
    fleet = RecordingFleet([VERBOSE_OUTPUT])
    result = execute_task(
        "do the thing", "plan", fleet, verify_cmd=None, hold_on_fail=False,
        transcript_root=tmp_path,
    )

    assert result["status"] == "ok"
    assert "Implemented the widget." in result["output"]
    assert "pytest tests/test_widget.py -q" in result["output"]
    # The reasoning preamble crossed to disk (transcript) but never back to
    # the coordinator's own context.
    assert "step by step" not in result["output"]
    assert "scratch work" not in result["output"]
    assert len(result["output"]) < len(VERBOSE_OUTPUT)


def test_transcript_file_is_archived_with_the_full_raw_output(tmp_path: Path):
    fleet = RecordingFleet([VERBOSE_OUTPUT])
    execute_task(
        "do the thing", "plan", fleet, verify_cmd=None, hold_on_fail=False,
        transcript_root=tmp_path, task_slug="fixture-run",
    )

    transcript_dir = tmp_path / "var" / "task-transcripts"
    files = list(transcript_dir.glob("*.log"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    # The full raw transcript, rambling included, lives on disk for post-mortem.
    assert "step by step" in text
    assert "scratch work" in text
    assert "Implemented the widget." in text
    assert "attempt 1" in text
    assert "fake-ep" in text


def test_no_transcript_written_when_transcript_root_is_none():
    fleet = RecordingFleet([VERBOSE_OUTPUT])
    execute_task("do the thing", "plan", fleet, verify_cmd=None, hold_on_fail=False)
    # No transcript_root given — nothing to assert on disk; this just proves
    # the call doesn't require one (default stays opt-in, matching metrics_ledger).


def test_malformed_output_gets_exactly_one_retry_then_escalates():
    fleet = RecordingFleet([MALFORMED_OUTPUT, MALFORMED_OUTPUT])
    result = execute_task(
        "do the thing", "plan", fleet, verify_cmd=None, hold_on_fail=False,
    )

    assert result["status"] == "escalate"
    assert fleet.ep.calls == 2  # one corrective retry, then stop — never a third


def test_malformed_then_corrected_output_succeeds_on_the_retry():
    fleet = RecordingFleet([MALFORMED_OUTPUT, VERBOSE_OUTPUT])
    result = execute_task(
        "do the thing", "plan", fleet, verify_cmd=None, hold_on_fail=False,
    )

    assert result["status"] == "ok"
    assert fleet.ep.calls == 2
    assert "Implemented the widget." in result["output"]


def test_transcript_accumulates_across_retries(tmp_path: Path):
    fleet = RecordingFleet([MALFORMED_OUTPUT, VERBOSE_OUTPUT])
    execute_task(
        "do the thing", "plan", fleet, verify_cmd=None, hold_on_fail=False,
        transcript_root=tmp_path,
    )

    files = list((tmp_path / "var" / "task-transcripts").glob("*.log"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "attempt 1" in text
    assert "attempt 2" in text
    assert "trust me" in text  # the failed first attempt is preserved too
