import pytest
from orchestrate import split_tasks


def test_split_tasks_from_steps_table():
    plan = (
        "## Steps\n"
        "| # | Task | Touches | Verify by | Route to |\n"
        "|---|------|---------|-----------|----------|\n"
        "| 1 | Add the endpoint | api.py | pytest -q | executor |\n"
        "| 2 | Update the docs | README.md | manual read | tuner |\n"
    )
    tasks = split_tasks(plan)
    assert len(tasks) == 2
    assert "Add the endpoint" in tasks[0]


def test_split_tasks_from_numbered_list():
    plan = "1. Do the first thing\n2. Do the second thing\n"
    assert split_tasks(plan) == ["Do the first thing", "Do the second thing"]


def test_split_tasks_empty_plan_raises_with_clear_message():
    with pytest.raises(ValueError, match="empty"):
        split_tasks("   \n\n")


def test_split_tasks_unrecognized_format_raises_with_preview():
    plan = "Sure! Here's what I'd do: first, refactor things; then ship it."
    with pytest.raises(ValueError, match="No tasks found") as exc_info:
        split_tasks(plan)
    assert "refactor things" in str(exc_info.value)


class FakeEndpoint:
    def __init__(self, replies):
        self.replies = list(replies)
        self.name = "fake-ep"
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


class FakeFleet:
    def __init__(self, replies):
        self.ep = FakeEndpoint(replies)

    def pick(self, role):
        return self.ep


GOOD_OUTPUT = "did the thing\n## Result\nok\n## How to verify\npytest -q\n"


def test_execute_task_honors_suggest_escalate_without_burning_attempts():
    from orchestrate import execute_task

    fleet = FakeFleet(["SUGGEST-ESCALATE: claude:opus — architecture decision beyond this tier"])
    result = execute_task("pick a schema migration strategy", "plan", fleet,
                          verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "escalate"
    assert result["attempts"] == 1
    assert "claude:opus" in result["suggestion"]
    assert fleet.ep.calls == 1  # no retry burned on a declared poor fit


def test_execute_task_suggest_escalate_holds_in_detached_mode():
    from orchestrate import execute_task

    fleet = FakeFleet(["SUGGEST-ESCALATE: reasoner tier — hard concurrency bug"])
    result = execute_task("fix the race condition", "plan", fleet,
                          verify_cmd=None, hold_on_fail=True)

    assert result["status"] == "hold"


def test_execute_task_insist_overrides_fit_check():
    from orchestrate import execute_task

    fleet = FakeFleet([
        "SUGGEST-ESCALATE: bigger model — poor fit",
        GOOD_OUTPUT,
    ])
    result = execute_task("do it anyway", "plan", fleet,
                          verify_cmd=None, hold_on_fail=False, insist=True)

    assert result["status"] == "ok"
    assert result["attempts"] == 2
    assert fleet.ep.calls == 2


def test_assert_plan_file_allows_features_bugs_and_in_progress(tmp_path):
    from orchestrate import assert_plan_file_allowed

    for lane in ("features", "bugs", "in-progress"):
        p = tmp_path / ".plans" / lane / "foo.md"
        p.parent.mkdir(parents=True)
        p.write_text("# plan")
        assert_plan_file_allowed(p)  # no raise


def test_assert_plan_file_rejects_non_executable_lanes(tmp_path):
    from orchestrate import assert_plan_file_allowed

    for lane in ("drafts", "completed", "ambiguous", "blocked"):
        p = tmp_path / ".plans" / lane / "foo.md"
        p.parent.mkdir(parents=True)
        p.write_text("# plan")
        with pytest.raises(SystemExit, match=lane):
            assert_plan_file_allowed(p)


def test_assert_plan_file_allows_paths_outside_plans(tmp_path):
    from orchestrate import assert_plan_file_allowed

    p = tmp_path / "adhoc-plan.md"
    p.write_text("# plan")
    assert_plan_file_allowed(p)
