from pathlib import Path
from types import SimpleNamespace

from plan_parse import (
    TriageAction,
    has_goal_section,
    safe_read_text,
    strip_code_fences,
    triage_plan,
)

FIXTURES = Path(__file__).parent / "fixtures" / "plans"


def _worker(tier="mid", name="test-worker"):
    return SimpleNamespace(tier=tier, name=name)


def _record(**overrides):
    base = dict(
        parse_error=None,
        has_goal=True,
        agent_assignable=True,
        assignee=None,
        deps_met=True,
        deps_unmet=(),
        fit="good",
        preferred="mid",
        owner=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --- strip_code_fences ------------------------------------------------------

def test_strip_code_fences_blanks_fenced_content():
    text = "before\n```\nfenced line 1\nfenced line 2\n```\nafter\n"
    out = strip_code_fences(text)
    assert "fenced line" not in out
    assert "before" in out
    assert "after" in out


def test_strip_code_fences_preserves_line_count():
    text = "a\n```\nb\nc\nd\n```\ne\n"
    out = strip_code_fences(text)
    assert text.count("\n") == out.count("\n")


def test_strip_code_fences_handles_tilde_fences():
    text = "a\n~~~\nsecret\n~~~\nb\n"
    assert "secret" not in strip_code_fences(text)


def test_strip_code_fences_leaves_unfenced_text_untouched():
    text = "# Plan: X\n\n- **Value:** high\n\n## Goal\nDo the thing.\n"
    assert strip_code_fences(text) == text


def test_strip_code_fences_on_fixture_hides_the_quoted_example():
    text = (FIXTURES / "fenced_example_header.md").read_text(encoding="utf-8")
    stripped = strip_code_fences(text)
    assert "**Preferred models:** frontier" not in stripped
    assert "**Assignee:** human" not in stripped
    # the plan's own real header (outside the fence) survives
    assert "**Preferred models:** small" in stripped


# --- has_goal_section --------------------------------------------------------

def test_has_goal_section_true_for_normal_plan():
    text = (FIXTURES / "good_swarm.md").read_text(encoding="utf-8")
    assert has_goal_section(text)


def test_has_goal_section_false_when_missing():
    text = (FIXTURES / "missing_goal.md").read_text(encoding="utf-8")
    assert not has_goal_section(text)


def test_has_goal_section_false_for_empty_goal_body():
    text = "# Plan: X\n\n## Goal\n\n## Done when\n- [ ] x\n"
    assert not has_goal_section(text)


def test_has_goal_section_ignores_a_fenced_example_goal():
    text = (
        "# Plan: X\n\n## Context read\n\n```markdown\n## Goal\nfenced, not real\n```\n"
    )
    assert not has_goal_section(text)


# --- safe_read_text -----------------------------------------------------------

def test_safe_read_text_returns_content_for_real_file():
    text, err = safe_read_text(FIXTURES / "good_swarm.md")
    assert err is None
    assert "Rename a helper function" in text


def test_safe_read_text_returns_error_for_missing_file():
    text, err = safe_read_text(FIXTURES / "does_not_exist.md")
    assert text is None
    assert err is not None


def test_safe_read_text_returns_error_for_bad_encoding(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00\x81 not valid utf-8")
    text, err = safe_read_text(bad)
    assert text is None
    assert "utf-8" in err.lower() or "decode" in err.lower()


# --- triage_plan --------------------------------------------------------------

def test_triage_rejects_unreadable():
    rec = _record(parse_error="OSError: boom")
    verdict = triage_plan(rec, _worker())
    assert verdict.action is TriageAction.REJECT
    assert "unreadable" in verdict.reason


def test_triage_rejects_missing_goal():
    rec = _record(has_goal=False)
    verdict = triage_plan(rec, _worker())
    assert verdict.action is TriageAction.REJECT
    assert "Goal" in verdict.reason


def test_triage_rejects_human_assignee():
    rec = _record(agent_assignable=False, assignee="alice@example.com")
    verdict = triage_plan(rec, _worker())
    assert verdict.action is TriageAction.REJECT
    assert "alice@example.com" in verdict.reason


def test_triage_rejects_unmet_deps_by_default():
    rec = _record(deps_met=False, deps_unmet=("some-other-plan",))
    verdict = triage_plan(rec, _worker())
    assert verdict.action is TriageAction.REJECT
    assert "some-other-plan" in verdict.reason


def test_triage_takes_unmet_deps_when_ignored():
    rec = _record(deps_met=False, deps_unmet=("some-other-plan",))
    verdict = triage_plan(rec, _worker(), ignore_deps=True)
    assert verdict.action is TriageAction.TAKE


def test_triage_rejects_underqualified():
    rec = _record(fit="underqualified", preferred="reasoner, frontier")
    verdict = triage_plan(rec, _worker(tier="mid"))
    assert verdict.action is TriageAction.REJECT
    assert "underqualified" in verdict.reason


def test_triage_skips_overqualified():
    rec = _record(fit="overqualified", preferred="small")
    verdict = triage_plan(rec, _worker(tier="frontier"))
    assert verdict.action is TriageAction.SKIP
    assert "overqualified" in verdict.reason


def test_triage_skips_lease_held_by_other_agent():
    rec = _record(owner="other-agent")
    verdict = triage_plan(rec, _worker(), agent_id="me")
    assert verdict.action is TriageAction.SKIP
    assert "other-agent" in verdict.reason


def test_triage_takes_good_fit():
    rec = _record(fit="good", preferred="mid")
    verdict = triage_plan(rec, _worker(tier="mid"))
    assert verdict.action is TriageAction.TAKE


def test_triage_takes_unknown_preferred():
    rec = _record(fit="unknown", preferred=None)
    verdict = triage_plan(rec, _worker(tier="mid"))
    assert verdict.action is TriageAction.TAKE


def test_triage_missing_goal_beats_deps_and_assignee_ordering():
    # parse_error is checked first, has_goal second — both independent of the
    # other checks so ordering never masks a hard reject with a softer reason.
    rec = _record(has_goal=False, deps_met=False, deps_unmet=("x",))
    verdict = triage_plan(rec, _worker())
    assert "Goal" in verdict.reason
