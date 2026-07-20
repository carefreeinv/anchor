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
    def __init__(self, replies, quirks=None):
        self.replies = list(replies)
        self.name = "fake-ep"
        self.calls = 0
        self.quirks = quirks or {}

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


class FakeFleet:
    def __init__(self, replies, quirks=None):
        self.ep = FakeEndpoint(replies, quirks=quirks)

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


def test_execute_task_rejects_out_of_scope_before_tests(git_repo):
    """Out-of-scope worktree edit → failed-scope, and --verify never runs."""
    from pathlib import Path

    from orchestrate import execute_task
    from scope_gate import ScopeConfig

    # Executor "touched" a file outside scope (untracked new file).
    (git_repo / "secret.py").write_text("x = 1\n", encoding="utf-8")
    marker = git_repo / "verify-ran.txt"
    scope = ScopeConfig(root=git_repo, in_scope=("README",))

    fleet = FakeFleet([GOOD_OUTPUT])
    result = execute_task(
        "do the thing", "plan", fleet,
        verify_cmd=f"touch {marker}", hold_on_fail=False, scope=scope,
    )

    assert result["status"] == "failed-scope"
    assert "secret.py" in result["offending"]
    assert not Path(marker).exists()  # tests never ran on an out-of-scope diff
    assert fleet.ep.calls == 1  # not retried — routed back to planner


def test_execute_task_in_scope_runs_verify(git_repo):
    """In-scope changes pass the gate and proceed to --verify."""
    from pathlib import Path

    from orchestrate import execute_task
    from scope_gate import ScopeConfig

    (git_repo / "README").write_text("edited in scope\n", encoding="utf-8")
    marker = git_repo / "verify-ran.txt"
    scope = ScopeConfig(root=git_repo, in_scope=("README",))

    fleet = FakeFleet([GOOD_OUTPUT])
    result = execute_task(
        "edit the readme", "plan", fleet,
        verify_cmd=f"touch {marker}", hold_on_fail=False, scope=scope,
    )

    assert result["status"] == "ok"
    assert Path(marker).exists()  # gate passed → verify ran


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


class SideEffectEndpoint:
    """Fake endpoint whose chat() optionally performs a filesystem side effect
    before replying — models the executor agent editing its worktree."""

    name = "fake-ep"

    def __init__(self, replies):
        self.replies = list(replies)
        self.quirks: dict = {}  # real Endpoint always has one; budget gate reads it

    def chat(self, messages, **kwargs):
        side_effect, reply = self.replies.pop(0)
        if side_effect:
            side_effect()
        return reply


class SideEffectFleet:
    def __init__(self, replies):
        self.ep = SideEffectEndpoint(replies)

    def pick(self, role):
        return self.ep


PLAN_TEXT = (
    "## Steps\n"
    "| # | Task | Touches | Verify by | Route to |\n"
    "|---|------|---------|-----------|----------|\n"
    "| 1 | say hello | README | none | mid |\n"
)


def _run_main(monkeypatch, git_repo, fleet, extra_args=()):
    import orchestrate

    out = git_repo / "run.json"
    monkeypatch.setattr(orchestrate, "Fleet", lambda *a, **k: fleet)
    monkeypatch.setattr(orchestrate, "load_prompt", lambda p: "PROMPT")
    monkeypatch.setattr(
        "sys.argv",
        ["orchestrate.py", "--goal", "greet", "--worktree", str(git_repo),
         "--out", str(out), *extra_args],
    )
    return out


def test_main_planner_product_write_hard_error_run_still_outputs(
    git_repo, monkeypatch
):
    """Planner phase writing a product file → hard error (exit 4), but the run
    continues to its plan/review output (the spec text is not lost)."""
    import json

    import orchestrate

    fleet = SideEffectFleet([
        # planner: illegally writes a product file alongside its plan text
        (lambda: (git_repo / "api.py").write_text("x = 1\n"), PLAN_TEXT),
        (None, GOOD_OUTPUT),   # executor
        (None, "review: ok"),  # critic
    ])
    out = _run_main(monkeypatch, git_repo, fleet)

    with pytest.raises(SystemExit) as exc_info:
        orchestrate.main()
    assert exc_info.value.code == orchestrate.ROLE_VIOLATION_EXIT

    run = json.loads(out.read_text())
    assert run["plan"] == PLAN_TEXT          # run continued to spec output
    assert run["review"] == "review: ok"
    assert [v["role"] for v in run["role_violations"]] == ["planner"]
    assert run["role_violations"][0]["offending"] == ["api.py"]
    assert any(e["event"] == "role-violation" for e in run["events"])
    assert any(e["event"] == "role-transition" for e in run["events"])


def test_main_executor_plans_write_fails_role(git_repo, monkeypatch):
    """Executor phase touching .plans/** → task marked failed-role, exit 4."""
    import json

    import orchestrate

    def executor_touches_plans():
        p = git_repo / ".plans" / "features" / "sneaky.md"
        p.parent.mkdir(parents=True)
        p.write_text("# widened my own mandate\n")

    fleet = SideEffectFleet([
        (None, PLAN_TEXT),                     # planner (clean)
        (executor_touches_plans, GOOD_OUTPUT),  # executor (illegal write)
        (None, "review: ok"),                  # critic
    ])
    out = _run_main(monkeypatch, git_repo, fleet)

    with pytest.raises(SystemExit) as exc_info:
        orchestrate.main()
    assert exc_info.value.code == orchestrate.ROLE_VIOLATION_EXIT

    run = json.loads(out.read_text())
    assert run["results"][0]["status"] == "failed-role"
    assert run["results"][0]["role_offending"] == [".plans/features/sneaky.md"]


def test_main_clean_run_has_no_violations_and_exits_zero(git_repo, monkeypatch):
    import json

    import orchestrate

    fleet = SideEffectFleet([
        (None, PLAN_TEXT),
        (None, GOOD_OUTPUT),
        (None, "review: ok"),
    ])
    out = _run_main(monkeypatch, git_repo, fleet)

    orchestrate.main()  # no SystemExit

    run = json.loads(out.read_text())
    assert run["role_violations"] == []
    assert run["results"][0]["status"] == "ok"


def test_enforce_role_phase_ignores_preexisting_changes(git_repo):
    """Only writes made during the phase are attributed to the role."""
    from orchestrate import enforce_role_phase, snapshot_changes
    from roles import CRITIC

    (git_repo / "dirty.py").write_text("pre-existing\n")
    before = snapshot_changes(git_repo)

    events = []
    verdict = enforce_role_phase(CRITIC, git_repo, before, events)
    assert verdict.ok  # critic wrote nothing new; dirty.py not blamed
    assert events == []


def test_check_budget_ok_when_endpoint_has_no_max_context():
    from anchor_client import Endpoint
    from orchestrate import check_budget

    ep = Endpoint(name="unspecified-ep", tier="executor", base_url="http://x", model="m")
    ok, msg = check_budget("x" * 100_000, ep)
    assert ok
    assert msg == ""


def test_check_budget_rejects_text_over_max_context():
    from anchor_client import Endpoint
    from orchestrate import check_budget

    ep = Endpoint(name="tiny-ep", tier="executor", base_url="http://x", model="m",
                  quirks={"max_context": 100})
    ok, msg = check_budget("x" * 10_000, ep)  # ~2500 estimated tokens >> 100
    assert not ok
    assert "tiny-ep" in msg
    assert "decomposed wrong" in msg


def test_check_budget_ok_when_text_fits_max_context():
    from anchor_client import Endpoint
    from orchestrate import check_budget

    ep = Endpoint(name="roomy-ep", tier="executor", base_url="http://x", model="m",
                  quirks={"max_context": 100_000})
    ok, msg = check_budget("x" * 100, ep)
    assert ok
    assert msg == ""


def test_execute_task_rejects_oversized_prompt_without_calling_endpoint():
    from orchestrate import execute_task

    fleet = FakeFleet([GOOD_OUTPUT], quirks={"max_context": 10})
    result = execute_task("do the thing", "plan", fleet, verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "failed-budget"
    assert "decomposed wrong" in result["message"]
    assert fleet.ep.calls == 0  # rejected before dispatch — never sent, never truncated


def test_execute_task_budget_rejection_holds_in_detached_mode_message_unchanged():
    from orchestrate import execute_task

    # Budget rejection is not a retryable/escalatable failure mode like SUGGEST-ESCALATE
    # or a failed verify — it always reports failed-budget regardless of hold_on_fail.
    fleet = FakeFleet([GOOD_OUTPUT], quirks={"max_context": 10})
    result = execute_task("do the thing", "plan", fleet, verify_cmd=None, hold_on_fail=True)

    assert result["status"] == "failed-budget"
