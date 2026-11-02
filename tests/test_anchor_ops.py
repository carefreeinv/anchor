"""Registry shape for the transport-neutral operations core."""
from __future__ import annotations

import anchor_ops as ops

EXPECTED = {
    "plans.list", "plans.board",
    "work.list", "work.claim", "work.heartbeat", "work.finish", "work.return",
    "review.list", "review.review",
    "draft.list", "draft.create", "draft.promote",
    "fleet-watch.status", "fleet-watch.list", "fleet-watch.once",
    "fleet-watch.emit", "fleet-watch.install",
}


def test_every_verb_action_registered_exactly_once():
    names = [op.name for op in ops.operations()]
    assert sorted(names) == sorted(EXPECTED)
    assert len(names) == len(set(names))
    for op in ops.operations():
        assert op.verb in ops.VERBS
        assert op.name == f"{op.verb}.{op.action}"
        assert op.requires in (None, ops.NEEDS_OPERATOR, ops.NEEDS_MODEL, ops.NEEDS_HARNESS)


def test_safety_flags_on_mutating_ops():
    by_name = {op.name: op for op in ops.operations()}
    assert by_name["review.review"].mutates and by_name["review.review"].requires == ops.NEEDS_OPERATOR
    assert by_name["draft.promote"].mutates and by_name["draft.promote"].requires == ops.NEEDS_OPERATOR
    assert by_name["work.claim"].mutates and by_name["work.claim"].requires == ops.NEEDS_MODEL
    assert not by_name["plans.list"].mutates
    assert not by_name["review.list"].mutates
    assert by_name["fleet-watch.install"].mutates
    assert by_name["fleet-watch.install"].requires == ops.NEEDS_OPERATOR
    assert not by_name["fleet-watch.emit"].mutates
    assert by_name["fleet-watch.emit"].requires == ops.NEEDS_HARNESS


def test_result_needs_operator_and_mode_live_in_the_core():
    assert ops.NeedsOperator("x", "y").step == "x"
    assert ops.Result("plans", "list").to_json(ops.Mode(False, "test"))["schema_version"] == 1
    never = ops.NeverAnswers()
    try:
        never.choose("review-decision", "Decision", ops.REVIEW_CHOICES)
    except ops.NeedsOperator as exc:
        assert exc.step == "review-decision"
    else:
        raise AssertionError("NeverAnswers.choose must raise")
