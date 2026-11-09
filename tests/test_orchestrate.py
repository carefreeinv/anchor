import pytest
from orchestrate import (
    parse_task_touches,
    split_tasks,
    task_touches_denied_plans,
)


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


def test_parse_task_touches_table_row():
    assert parse_task_touches(
        "Parse backtick/bare paths | `anchor/cli.md` | unit | mid"
    ) == ["anchor/cli.md"]
    assert parse_task_touches(
        "Update notes | tests, CHANGELOG.md | pytest | mid"
    ) == ["tests", "CHANGELOG.md"]
    assert parse_task_touches(
        "Keep dotted path | scripts/foo.py | stamp | mid"
    ) == ["scripts/foo.py"]


def test_parse_task_touches_header_line():
    assert parse_task_touches("Touches: `api.py`, scripts/foo.py") == [
        "api.py",
        "scripts/foo.py",
    ]


def test_task_touches_denied_plans_hygiene_path():
    assert task_touches_denied_plans(
        "Drop the Status: line from "
        ".plans/completed/plan-release-tracking.local.md"
    )
    assert task_touches_denied_plans(
        "edit `scripts/foo.py` and `.plans/features/bar.md`"
    )
    assert not task_touches_denied_plans("rewrite scripts/plan_store.py")
    assert not task_touches_denied_plans("see the plans workflow")
    assert not task_touches_denied_plans("see .plans/README for process")


def test_execute_task_plans_touch_escalates_without_chat():
    from orchestrate import execute_task

    fleet = FakeFleet([GOOD_OUTPUT])
    result = execute_task(
        "Drop Status from .plans/completed/plan-release-tracking.local.md",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
    )
    assert result["status"] == "escalate"
    assert result["attempts"] == 1
    assert "EXECUTOR" in result["suggestion"]
    assert fleet.ep.calls == 0


def test_execute_task_mixed_product_and_plans_escalates():
    from orchestrate import execute_task

    fleet = FakeFleet([GOOD_OUTPUT])
    result = execute_task(
        "Update scripts/plan_store.py and `.plans/features/hygiene.md`",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
    )
    assert result["status"] == "escalate"
    assert fleet.ep.calls == 0


def test_execute_task_plans_touch_insist_still_chats():
    from orchestrate import execute_task

    fleet = FakeFleet([GOOD_OUTPUT])
    result = execute_task(
        "Drop Status from .plans/completed/x.local.md",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
        insist=True,
    )
    assert result["status"] == "ok"
    assert fleet.ep.calls == 1


class FakeEndpoint:
    def __init__(self, replies, quirks=None):
        self.replies = list(replies)
        self.name = "fake-ep"
        self.calls = 0
        self.quirks = quirks or {}
        self.last_messages = None

    def chat(self, messages, **kwargs):
        self.calls += 1
        self.last_messages = messages
        return self.replies.pop(0)


class FakeFleet:
    def __init__(self, replies, quirks=None):
        self.ep = FakeEndpoint(replies, quirks=quirks)

    def pick(self, role):
        return self.ep


GOOD_OUTPUT = (
    "did the thing\n## Result\nok\n## How to verify\npytest -q\n"
    "## Deferred / concerns\nNone.\n"
)


def test_execute_task_refuses_swarm_on_mid_preferred_plan():
    from orchestrate import execute_task

    fleet = FakeFleet([GOOD_OUTPUT])
    fleet.ep.tier = "swarm"
    plan = "- **Preferred models:** small, mid\n## Goal\nwrap the board JSON\n"
    result = execute_task("wrap board JSON", plan, fleet, verify_cmd=None, hold_on_fail=False)
    assert result["status"] == "refused-fit"
    assert fleet.ep.calls == 0
    assert "underqualified" in result["message"]


def test_execute_task_insist_overrides_preferred_floor():
    from orchestrate import execute_task

    fleet = FakeFleet([GOOD_OUTPUT])
    fleet.ep.tier = "swarm"
    plan = "- **Preferred models:** mid\n"
    result = execute_task("do it", plan, fleet, verify_cmd=None, hold_on_fail=False, insist=True)
    assert result["status"] == "ok"
    assert fleet.ep.calls == 1


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


def test_execute_task_honors_suggest_downgrade_without_burning_attempts():
    from orchestrate import execute_task

    fleet = FakeFleet([
        "SUGGEST-DOWNGRADE: small — rename-only; local swarm is enough",
    ])
    result = execute_task("rename the helper file", "plan", fleet,
                          verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "escalate"
    assert result["attempts"] == 1
    assert "DOWNGRADE" in result["suggestion"].upper() or "small" in result["suggestion"]
    assert fleet.ep.calls == 1


def test_execute_task_insist_overrides_suggest_downgrade():
    from orchestrate import execute_task

    fleet = FakeFleet([
        "SUGGEST-DOWNGRADE: small — too easy",
        GOOD_OUTPUT,
    ])
    result = execute_task("do it here anyway", "plan", fleet,
                          verify_cmd=None, hold_on_fail=False, insist=True)

    assert result["status"] == "ok"
    assert result["attempts"] == 2
    assert fleet.ep.calls == 2


def test_execute_task_honors_suggest_reroute_without_burning_attempts():
    """Specialty-axis fit gate (mythos-core rule 11) — same no-retry contract as escalate."""
    from orchestrate import execute_task

    fleet = FakeFleet([
        "SUGGEST-REROUTE: coding-agent — leave multi-file software for a software-dev optimized model",
    ])
    result = execute_task("implement the auth middleware across three packages", "plan", fleet,
                          verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "escalate"
    assert result["attempts"] == 1
    assert "coding-agent" in result["suggestion"]
    assert fleet.ep.calls == 1


def test_execute_task_insist_overrides_suggest_reroute():
    from orchestrate import execute_task

    fleet = FakeFleet([
        "SUGGEST-REROUTE: coding-agent — wrong specialty",
        GOOD_OUTPUT,
    ])
    result = execute_task("do it anyway", "plan", fleet,
                          verify_cmd=None, hold_on_fail=False, insist=True)

    assert result["status"] == "ok"
    assert result["attempts"] == 2
    assert fleet.ep.calls == 2


RULE13_THEN_REROUTE = (
    "Goal restated? PASS\n"
    "Acceptance criteria present? PASS\n"
    "Files-in-scope listed? PASS\n"
    "Budget declared and fits (spec's ## Budget)? PASS\n"
    "Tier + specialty fit OK (rule 11: power escalate and/or specialty re-route)? FAIL\n"
    "Task small enough for this tier (rule 10)? PASS\n"
    "SUGGEST-REROUTE: coding-agent — leave multi-file software for a software-dev optimized model\n"
)

RULE13_THEN_DOWNGRADE = (
    "Goal restated? PASS\n"
    "Acceptance criteria present? PASS\n"
    "Files-in-scope listed? PASS\n"
    "Budget declared and fits (spec's ## Budget)? PASS\n"
    "Tier + specialty fit OK (rule 11: power escalate and/or specialty re-route)? PASS\n"
    "Task small enough for this tier (rule 10)? FAIL\n"
    "SUGGEST-DOWNGRADE: small — rename-only; local swarm is enough\n"
)


def test_fit_gate_line_finds_token_after_preflight():
    from orchestrate import fit_gate_line

    line = fit_gate_line(RULE13_THEN_REROUTE)
    assert line is not None and line.startswith("SUGGEST-REROUTE: coding-agent")
    buried = "\n".join(f"note {i}" for i in range(15))
    buried += "\nSUGGEST-REROUTE: coding-agent — too late\n"
    assert fit_gate_line(buried) is None


def test_fit_gate_line_finds_downgrade_token_after_preflight():
    from orchestrate import fit_gate_line

    line = fit_gate_line(RULE13_THEN_DOWNGRADE)
    assert line is not None and line.startswith("SUGGEST-DOWNGRADE: small")


def test_execute_task_honors_reroute_after_rule13_preflight():
    """Rule 13 prints six preflight lines then the token — must not FORMAT-retry."""
    from orchestrate import execute_task

    fleet = FakeFleet([RULE13_THEN_REROUTE])
    result = execute_task(
        "implement the auth middleware across three packages",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
    )

    assert result["status"] == "escalate"
    assert result["attempts"] == 1
    assert "coding-agent" in result["suggestion"]
    assert fleet.ep.calls == 1


def test_execute_task_honors_downgrade_after_rule13_preflight():
    """Same contract as reroute-after-preflight, but for the power/downgrade token."""
    from orchestrate import execute_task

    fleet = FakeFleet([RULE13_THEN_DOWNGRADE])
    result = execute_task(
        "rename the helper file",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
    )

    assert result["status"] == "escalate"
    assert result["attempts"] == 1
    assert "small" in result["suggestion"]
    assert fleet.ep.calls == 1


def test_execute_task_rejects_out_of_scope_before_tests(git_repo):
    """Out-of-scope worktree edit → failed-scope, and --verify never runs."""
    from pathlib import Path

    from orchestrate import execute_task
    from scope_gate import ScopeConfig

    marker = git_repo / "verify-ran.txt"
    scope = ScopeConfig(root=git_repo, in_scope=("README",))

    def write_secret():
        (git_repo / "secret.py").write_text("x = 1\n", encoding="utf-8")

    fleet = SideEffectFleet([(write_secret, GOOD_OUTPUT)])
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

    marker = git_repo / "verify-ran.txt"
    scope = ScopeConfig(root=git_repo, in_scope=("README",))

    def write_readme():
        (git_repo / "README").write_text("edited in scope\n", encoding="utf-8")

    fleet = SideEffectFleet([(write_readme, GOOD_OUTPUT)])
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
        self.calls = getattr(self, "calls", 0) + 1
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
        (lambda: (git_repo / "README").write_text("hello from executor\n"), GOOD_OUTPUT),
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
        (lambda: (git_repo / "README").write_text("hello\n"), GOOD_OUTPUT),
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


# --- ledger rows carry the role verdict -------------------------------------
# A task can pass its verify step and still have written outside its role's
# allowed paths. The claimed-vs-actual ledger exists to measure claim accuracy,
# so a role-violating run must not be recorded as a clean, accurate claim.


def _ledger_rows(path):
    from fleet_metrics import load_outcomes

    return load_outcomes(path)


def test_role_violating_task_is_not_recorded_as_a_clean_claim(git_repo, monkeypatch):
    """Executor claims success, verify is absent, but it wrote into .plans/** —
    the ledger row must carry role_verdict='fail', not a bare accurate claim."""
    import orchestrate

    def executor_touches_plans():
        p = git_repo / ".plans" / "features" / "sneaky.md"
        p.parent.mkdir(parents=True)
        p.write_text("# widened my own mandate\n")

    ledger = git_repo / "outcomes.jsonl"
    fleet = SideEffectFleet([
        (None, PLAN_TEXT),                      # planner (clean)
        (executor_touches_plans, GOOD_OUTPUT),  # executor claims success
        (None, "review: ok"),                   # critic
    ])
    _run_main(monkeypatch, git_repo, fleet,
              extra_args=("--metrics-ledger", str(ledger)))

    with pytest.raises(SystemExit):
        orchestrate.main()

    rows = _ledger_rows(ledger)
    assert len(rows) == 1
    assert rows[0].claimed == "success"      # the model still claimed success
    assert rows[0].role_verdict == "fail"    # ...but the harness caught the write


# --- handoff → continuation --------------------------------------------------
# A task that outgrows its window becomes a planned continuation, not a truncated
# answer. The orchestrator (not the model) decides how many windows are allowed.


HANDOFF_TEXT = """# Handoff: big task

## Done
- [x] Wrote the parser — verified by `pytest -q` → pass

## Remaining

### 1. Serialize the rows

- Goal: stream report rows as CSV
- Files in scope: app/export.py
- Verify by: `pytest tests/test_export.py -q`

## Decisions made
- Streamed rather than buffered — reports can exceed memory

## Files touched
- `app/parse.py` — added the row parser

## Open concerns
- none
"""


class RecordingEndpoint(FakeEndpoint):
    """FakeEndpoint that keeps every user prompt it was dispatched."""

    def __init__(self, replies, quirks=None):
        super().__init__(replies, quirks=quirks)
        self.prompts: list[str] = []

    def chat(self, messages, **kwargs):
        self.prompts.append(messages[-1]["content"])
        return super().chat(messages, **kwargs)


class RecordingFleet:
    def __init__(self, replies, quirks=None):
        self.ep = RecordingEndpoint(replies, quirks=quirks)

    def pick(self, role):
        return self.ep


def test_handoff_output_is_not_treated_as_a_format_failure():
    """A handoff has no '## Result' footer on purpose — it must not be retried."""
    from orchestrate import execute_task

    fleet = RecordingFleet([HANDOFF_TEXT])
    result = execute_task("big task", "plan", fleet, verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "handoff"
    assert result["attempts"] == 1
    assert fleet.ep.calls == 1  # no retry burned on a deliberate handoff
    assert result["handoff"].remaining[0].verify_by == "pytest tests/test_export.py -q"


def test_make_plan_injects_fleet_summary_never_raw_registry():
    """Planner needs routing awareness for 'Route to' hints, but only the generated
    summary — full endpoint detail (base_url, model) stays out of its context."""
    from anchor_client import Endpoint
    from orchestrate import make_plan

    class SummaryFleet(RecordingFleet):
        def __init__(self, replies):
            super().__init__(replies)
            self.endpoints = [Endpoint(
                name="h100-nemotron", tier="reasoner",
                base_url="http://10.0.1.11:8000/v1", model="nvidia/nemotron",
                quirks={"think_toggle": "nemotron", "max_context": 65536},
            )]
            self.roles = {}

    fleet = SummaryFleet(["## Steps\n| 1 | do it | x.py | pytest | executor |\n"])

    make_plan("do the thing", "some context", fleet)

    prompt = fleet.ep.prompts[0]
    assert "FLEET SUMMARY" in prompt
    assert "h100-nemotron" in prompt
    assert "reasoner" in prompt
    assert "http://10.0.1.11:8000/v1" not in prompt  # raw registry detail never pasted
    assert "nvidia/nemotron" not in prompt


def test_make_plan_omits_summary_block_for_fleet_without_endpoints():
    """A test double / minimal fleet with no .endpoints must not break make_plan."""
    from orchestrate import make_plan

    fleet = RecordingFleet(["## Steps\n| 1 | do it | x.py | pytest | executor |\n"])

    make_plan("do the thing", "some context", fleet)

    prompt = fleet.ep.prompts[0]
    assert "FLEET SUMMARY" not in prompt
    assert prompt.endswith("CONTEXT:\nsome context")


def test_undispatchable_handoff_gets_one_corrective_retry_then_escalates():
    """Remaining work with no Verify by is rejected — one retry, never a third."""
    from orchestrate import execute_task

    vague = HANDOFF_TEXT.replace("- Verify by: `pytest tests/test_export.py -q`\n", "")
    fleet = RecordingFleet([vague, vague])
    result = execute_task("big task", "plan", fleet, verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "escalate"
    assert fleet.ep.calls == 2  # MAX_ATTEMPTS: one corrective retry, then stop
    assert "Verify by" in fleet.ep.prompts[1]  # the retry carried the correction


def test_handoff_respawns_a_fresh_continuation_that_completes():
    """The oversized-task path: one handoff, one continuation, task completes."""
    from orchestrate import execute_with_continuations

    fleet = RecordingFleet([HANDOFF_TEXT, GOOD_OUTPUT])
    result = execute_with_continuations("big task", "plan", fleet,
                                        verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "ok"
    assert result["windows"] == 2
    assert [h["window"] for h in result["handoffs"]] == [1]

    continuation = fleet.ep.prompts[1]
    assert "CONTINUATION (window 2)" in continuation
    assert "big task" in continuation                    # original task restated
    assert "do NOT redo" in continuation
    assert "Wrote the parser" in continuation            # done work carried forward
    assert "Streamed rather than buffered" in continuation  # decisions carried forward
    assert "Serialize the rows" in continuation          # only remaining work dispatched


def test_third_respawn_is_refused_with_an_escalation_report():
    """Two respawns is the cap: a task still handing off is a decomposition error."""
    from orchestrate import execute_with_continuations

    fleet = RecordingFleet([HANDOFF_TEXT, HANDOFF_TEXT, HANDOFF_TEXT])
    result = execute_with_continuations("big task", "plan", fleet,
                                        verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "escalate"
    assert result["windows"] == 3
    assert "decomposed wrong" in result["message"]
    assert "back to the planner" in result["message"]
    assert fleet.ep.calls == 3  # no fourth window dispatched


def test_handoff_cap_holds_in_detached_mode():
    from orchestrate import execute_with_continuations

    fleet = RecordingFleet([HANDOFF_TEXT, HANDOFF_TEXT, HANDOFF_TEXT])
    result = execute_with_continuations("big task", "plan", fleet,
                                        verify_cmd=None, hold_on_fail=True)

    assert result["status"] == "hold"


def test_max_respawns_zero_escalates_on_the_first_handoff():
    from orchestrate import execute_with_continuations

    fleet = RecordingFleet([HANDOFF_TEXT, GOOD_OUTPUT])
    result = execute_with_continuations("big task", "plan", fleet, verify_cmd=None,
                                        hold_on_fail=False, max_respawns=0)

    assert result["status"] == "escalate"
    assert fleet.ep.calls == 1


def test_continuation_refusing_to_widen_scope_escalates_instead_of_dispatching(git_repo):
    """Scope smuggled into remaining work goes back to the planner, not to a worker."""
    from orchestrate import execute_with_continuations
    from scope_gate import ScopeConfig

    fleet = RecordingFleet([HANDOFF_TEXT, GOOD_OUTPUT])
    scope = ScopeConfig(root=git_repo, in_scope=("docs/",))  # app/export.py is outside it

    result = execute_with_continuations("big task", "plan", fleet, verify_cmd=None,
                                        hold_on_fail=False, scope=scope)

    assert result["status"] == "escalate"
    assert "app/export.py" in result["message"]
    assert "only shrink" in result["message"]
    assert fleet.ep.calls == 1  # continuation never dispatched


def test_handoff_events_are_logged_for_the_run_record():
    from orchestrate import execute_with_continuations

    events: list[dict] = []
    fleet = RecordingFleet([HANDOFF_TEXT, GOOD_OUTPUT])
    execute_with_continuations("big task", "plan", fleet, verify_cmd=None,
                               hold_on_fail=False, events=events)

    assert [e["event"] for e in events] == ["handoff"]
    assert events[0]["window"] == 1


# --- budget accounting drives the handoff, the model does not ----------------


def test_budget_pressure_is_none_without_a_declared_ceiling():
    from anchor_client import Endpoint
    from orchestrate import budget_pressure

    ep = Endpoint(name="unspecified-ep", tier="executor", base_url="http://x", model="m")
    assert budget_pressure("x" * 1000, ep) is None


def test_budget_pressure_is_the_fraction_of_the_declared_ceiling():
    from anchor_client import Endpoint
    from orchestrate import budget_pressure

    ep = Endpoint(name="ep", tier="executor", base_url="http://x", model="m",
                  quirks={"max_context": 100})
    assert budget_pressure("x" * 320, ep) == pytest.approx(0.81, abs=0.02)


def test_dispatch_near_the_ceiling_attaches_the_handoff_directive(monkeypatch):
    import orchestrate

    monkeypatch.setattr(orchestrate, "HANDOFF_THRESHOLD", 0.0)
    fleet = RecordingFleet([GOOD_OUTPUT], quirks={"max_context": 1_000_000})
    orchestrate.execute_task("small task", "plan", fleet, verify_cmd=None, hold_on_fail=False)

    assert "BUDGET NOTICE" in fleet.ep.prompts[0]
    assert "anchor/templates/handoff.md" in fleet.ep.prompts[0]


def test_dispatch_below_the_threshold_attaches_nothing():
    from orchestrate import execute_task

    fleet = RecordingFleet([GOOD_OUTPUT], quirks={"max_context": 1_000_000})
    execute_task("small task", "plan", fleet, verify_cmd=None, hold_on_fail=False)

    assert "BUDGET NOTICE" not in fleet.ep.prompts[0]


def test_clean_task_records_role_verdict_pass(git_repo, monkeypatch):
    import orchestrate

    ledger = git_repo / "outcomes.jsonl"
    fleet = SideEffectFleet([
        (None, PLAN_TEXT),     # planner
        (lambda: (git_repo / "README").write_text("hello\n"), GOOD_OUTPUT),
        (None, "review: ok"),  # critic
    ])
    _run_main(monkeypatch, git_repo, fleet,
              extra_args=("--metrics-ledger", str(ledger)))

    orchestrate.main()  # clean run: no SystemExit

    rows = _ledger_rows(ledger)
    assert len(rows) == 1
    assert rows[0].role_verdict == "pass"


def test_a_conforming_result_quoting_the_template_is_not_a_handoff():
    """A task whose job is to edit the handoff template must still finish."""
    from orchestrate import execute_with_continuations

    fleet = RecordingFleet([GOOD_OUTPUT + "\n" + HANDOFF_TEXT])
    result = execute_with_continuations("edit the handoff template", "plan", fleet,
                                        verify_cmd=None, hold_on_fail=False)

    assert result["status"] == "ok"          # not spun into a continuation
    assert fleet.ep.calls == 1


def test_budget_check_accounts_for_the_directive_it_will_append(monkeypatch):
    """The directive used to be added after the check that said the prompt fits."""
    import orchestrate

    monkeypatch.setattr(orchestrate, "HANDOFF_THRESHOLD", 0.0)
    monkeypatch.setattr(orchestrate, "load_prompt", lambda p: "SYS")
    # Ceiling sits between the bare prompt and the prompt+directive.
    bare = orchestrate.estimate_tokens("SYS" + "PLAN (context only):\nplan\n\n"
                                       "YOUR SINGLE TASK:\ntask")
    ceiling = bare + 10
    fleet = RecordingFleet([GOOD_OUTPUT], quirks={"max_context": ceiling})

    result = orchestrate.execute_task("task", "plan", fleet, verify_cmd=None,
                                      hold_on_fail=False)

    assert result["status"] == "failed-budget"
    assert fleet.ep.calls == 0  # refused rather than dispatched over the ceiling


def test_budget_pressure_is_total_on_odd_ceilings():
    from anchor_client import Endpoint
    from orchestrate import budget_pressure

    for ceiling in ("0", "abc", -5, 0):
        ep = Endpoint(name="odd", tier="executor", base_url="http://x", model="m",
                      quirks={"max_context": ceiling})
        assert budget_pressure("x" * 100, ep) is None


def test_zero_max_respawns_escalates_without_hitting_the_unreachable_assert():
    import orchestrate

    fleet = RecordingFleet([HANDOFF_TEXT, GOOD_OUTPUT])
    result = orchestrate.execute_with_continuations(
        "big task", "plan", fleet, verify_cmd=None, hold_on_fail=False, max_respawns=0)

    assert result["status"] == "escalate"   # no AssertionError("unreachable")


class TopTierEndpoint:
    """Fake single-tier ('frontier') endpoint whose replies serve every role in
    dispatch order, like SideEffectFleet — but exposes model/tier/.endpoints so
    the harness stop condition can introspect it for escalation/human-report."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.name = "frontier-ep"
        self.model = "frontier-model"
        self.tier = "frontier"
        self.quirks: dict = {}
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


class TopTierFleet:
    def __init__(self, replies):
        self.ep = TopTierEndpoint(replies)
        self.endpoints = [self.ep]

    def pick(self, role):
        return self.ep


def test_human_report_is_written_to_disk_for_top_tier_exhaustion(git_repo, monkeypatch):
    """Two prior failures at the fleet's only (and therefore top available) tier
    means the third dispatch never happens — main() generates and persists a
    structured report file itself, since the model never got a chance to."""
    import json
    from pathlib import Path

    import orchestrate
    from fleet_metrics import record_task_outcome

    task_text = split_tasks(PLAN_TEXT)[0]
    ledger = git_repo / "var" / "fleet-metrics" / "outcomes.jsonl"
    for i in range(2):
        record_task_outcome(
            output="## Result\nfailed\n## How to verify\nn/a\n",
            verify_exit=1, model="frontier-model", tier="frontier", task=task_text,
            ledger_path=ledger, timestamp=float(i),
        )

    # planner call → PLAN_TEXT; executor call is refused before dispatch; critic call → verdict
    fleet = TopTierFleet([PLAN_TEXT])
    out = _run_main(monkeypatch, git_repo, fleet)

    with pytest.raises(SystemExit) as exc:
        orchestrate.main()  # human-report is not a role violation (exit 4)
    assert exc.value.code == orchestrate.FAILED_NOOP_EXIT  # no task ok

    assert fleet.ep.calls == 1  # planner only; critic skipped (0 ok / human-report)

    run = json.loads(out.read_text())
    assert run["results"][0]["status"] == "human-report"
    report_path = Path(run["results"][0]["report_path"])
    assert report_path.is_file()
    text = report_path.read_text(encoding="utf-8")
    assert "## Tried" in text
    assert "## Observed" in text
    assert "## Hypothesis" in text
    assert any(e["event"] == "human-report" for e in run["events"])


def test_continuation_completes_with_a_passing_verify_command(git_repo):
    """The plan's Done when: handoff → continuation → verification actually green."""
    from pathlib import Path

    from orchestrate import execute_with_continuations

    marker = git_repo / "verified.txt"
    fleet = RecordingFleet([HANDOFF_TEXT, GOOD_OUTPUT])

    result = execute_with_continuations("big task", "plan", fleet,
                                        verify_cmd=f"touch {marker}", hold_on_fail=False)

    assert result["status"] == "ok"
    assert result["windows"] == 2
    assert Path(marker).exists()   # the continuation's verify ran, and passed


STALL_FOOTER = (
    "## Result\n"
    "Will produce after executing step 1\n"
    "## How to verify\n"
    "pytest -q\n"
    "## Deferred / concerns\n"
    "None at this time\n"
)

EXAMINE_FOOTER = (
    "## Result\n"
    "Let me examine the relevant files first.\n"
    "## How to verify\n"
    "Check current state of the files\n"
    "## Deferred / concerns\n"
    "None initially\n"
)


def test_execute_task_noop_worktree_is_not_ok_even_if_verify_passes(git_repo):
    from orchestrate import execute_task

    fleet = FakeFleet([GOOD_OUTPUT, GOOD_OUTPUT])
    result = execute_task(
        "do the thing",
        "plan",
        fleet,
        verify_cmd="true",
        hold_on_fail=False,
        worktree=git_repo,
    )
    assert result["status"] == "failed-noop"
    assert result["attempts"] == 2
    assert fleet.ep.calls == 2


def test_execute_task_placeholder_result_is_not_ok(git_repo):
    from orchestrate import execute_task

    fleet = FakeFleet([STALL_FOOTER, EXAMINE_FOOTER])
    result = execute_task(
        "do the thing",
        "plan",
        fleet,
        verify_cmd="true",
        hold_on_fail=False,
        worktree=git_repo,
    )
    assert result["status"] != "ok"
    assert fleet.ep.calls == 2


def test_execute_task_write_then_verify_still_ok(git_repo):
    from orchestrate import execute_task

    def write_readme():
        (git_repo / "README").write_text("edited\n", encoding="utf-8")

    fleet = SideEffectFleet([(write_readme, GOOD_OUTPUT)])
    result = execute_task(
        "edit readme",
        "plan",
        fleet,
        verify_cmd="true",
        hold_on_fail=False,
        worktree=git_repo,
    )
    assert result["status"] == "ok"


def test_main_all_noop_exits_nonzero_and_zero_ok_count(git_repo, monkeypatch):
    import json

    import orchestrate

    fleet = SideEffectFleet([
        (None, PLAN_TEXT),
        (None, GOOD_OUTPUT),
        (None, GOOD_OUTPUT),
    ])
    out = _run_main(monkeypatch, git_repo, fleet)
    with pytest.raises(SystemExit) as exc:
        orchestrate.main()
    assert exc.value.code == orchestrate.FAILED_NOOP_EXIT
    run = json.loads(out.read_text())
    assert run["results"][0]["status"] == "failed-noop"
    assert sum(r["status"] == "ok" for r in run["results"]) == 0
    assert run["review"].startswith("critic skipped: 0/")
    assert "failed-noop" in run["review"]
    assert fleet.ep.calls == 3  # planner + two executor retries; no critic


PLAN_ESCALATE = (
    "## Steps\n"
    "| # | Task | Touches | Verify by | Route to |\n"
    "|---|------|---------|-----------|----------|\n"
    "| 1 | Drop Status from .plans/completed/x.local.md | "
    ".plans/completed/x.local.md | none | mid |\n"
)

PLAN_MIXED = (
    "## Steps\n"
    "| # | Task | Touches | Verify by | Route to |\n"
    "|---|------|---------|-----------|----------|\n"
    "| 1 | say hello | README | none | mid |\n"
    "| 2 | Drop Status from .plans/completed/x.local.md | "
    ".plans/completed/x.local.md | none | mid |\n"
)


def test_main_all_escalate_exits_nonzero(git_repo, monkeypatch):
    import json

    import orchestrate

    fleet = SideEffectFleet([
        (None, PLAN_ESCALATE),
    ])
    out = _run_main(monkeypatch, git_repo, fleet)
    with pytest.raises(SystemExit) as exc:
        orchestrate.main()
    assert exc.value.code == orchestrate.FAILED_NOOP_EXIT
    run = json.loads(out.read_text())
    assert run["results"][0]["status"] == "escalate"
    assert sum(r["status"] == "ok" for r in run["results"]) == 0
    assert run["review"].startswith("critic skipped: 0/")
    assert "escalate" in run["review"]
    assert fleet.ep.calls == 1  # planner only; critic not chatted


def test_main_mixed_ok_and_escalate_exits_zero(git_repo, monkeypatch):
    import json

    import orchestrate

    fleet = SideEffectFleet([
        (None, PLAN_MIXED),
        (lambda: (git_repo / "README").write_text("hello\n"), GOOD_OUTPUT),
        (None, "review: ok"),
    ])
    out = _run_main(monkeypatch, git_repo, fleet)
    orchestrate.main()
    run = json.loads(out.read_text())
    statuses = [r["status"] for r in run["results"]]
    assert "ok" in statuses
    assert "escalate" in statuses
    assert run["review"] == "review: ok"
    assert fleet.ep.calls == 3  # planner + ok executor + critic (mixed still reviews)


def test_main_all_escalate_insist_still_skips_critic(git_repo, monkeypatch):
    import json

    import orchestrate

    fleet = SideEffectFleet([
        (None, PLAN_ESCALATE),
        (None, GOOD_OUTPUT),
        (None, GOOD_OUTPUT),
    ])
    out = _run_main(monkeypatch, git_repo, fleet, extra_args=("--insist",))
    with pytest.raises(SystemExit) as exc:
        orchestrate.main()
    assert exc.value.code == orchestrate.FAILED_NOOP_EXIT
    run = json.loads(out.read_text())
    assert run["review"].startswith("critic skipped: 0/")
    assert "review: ok" not in run["review"]
    assert fleet.ep.calls == 3  # planner + executor retries; critic still skipped


APPLY_OUTPUT = (
    "--- a/README\n"
    "+++ b/README\n"
    "@@ -1 +1 @@\n"
    "-hi\n"
    "+applied from chat\n"
    "## Result\n"
    "changed README\n"
    "## How to verify\n"
    "cat README\n"
    "## Deferred / concerns\n"
    "None.\n"
)


def test_execute_task_applies_unified_diff_then_verify(git_repo):
    from pathlib import Path

    from orchestrate import execute_task

    marker = git_repo / "verify-ran.txt"
    fleet = FakeFleet([APPLY_OUTPUT])
    result = execute_task(
        "edit readme",
        "plan",
        fleet,
        verify_cmd=f"touch {marker}",
        hold_on_fail=False,
        worktree=git_repo,
    )
    assert result["status"] == "ok"
    assert (git_repo / "README").read_text(encoding="utf-8") == "applied from chat\n"
    assert Path(marker).exists()


def test_execute_task_footer_only_with_worktree_is_failed_noop(git_repo):
    from orchestrate import execute_task

    fleet = FakeFleet([GOOD_OUTPUT, GOOD_OUTPUT])
    result = execute_task(
        "edit readme",
        "plan",
        fleet,
        verify_cmd="true",
        hold_on_fail=False,
        worktree=git_repo,
    )
    assert result["status"] == "failed-noop"
    assert (git_repo / "README").read_text(encoding="utf-8") == "hi\n"


FENCE_OUTPUT = (
    "```README\n"
    "applied from fence\n"
    "```\n"
    "## Result\n"
    "changed README\n"
    "## How to verify\n"
    "cat README\n"
    "## Deferred / concerns\n"
    "None.\n"
)


FENCE_NO_FOOTER = (
    "```README\n"
    "applied from fence without footer\n"
    "```\n"
)


def test_execute_task_applies_fence_without_footer(git_repo):
    from pathlib import Path

    from orchestrate import execute_task

    marker = git_repo / "verify-ran.txt"
    fleet = FakeFleet([FENCE_NO_FOOTER])
    result = execute_task(
        "edit readme",
        "plan",
        fleet,
        verify_cmd=f"touch {marker}",
        hold_on_fail=False,
        worktree=git_repo,
    )
    assert result["status"] == "ok"
    assert (git_repo / "README").read_text(encoding="utf-8") == "applied from fence without footer\n"
    assert Path(marker).exists()
    assert fleet.ep.calls == 1


def test_execute_task_prose_without_footer_still_format_retries(git_repo):
    from orchestrate import execute_task

    fleet = FakeFleet(["I will edit README now.", "still no patch and no footer"])
    result = execute_task(
        "edit readme",
        "plan",
        fleet,
        verify_cmd="true",
        hold_on_fail=False,
        worktree=git_repo,
    )
    assert result["status"] == "escalate"
    assert all(h.startswith("FORMAT:") for h in result["history"])
    assert (git_repo / "README").read_text(encoding="utf-8") == "hi\n"
    assert fleet.ep.calls == 2


def test_execute_task_applies_fenced_file_then_verify(git_repo):
    from pathlib import Path

    from orchestrate import execute_task

    marker = git_repo / "verify-ran.txt"
    fleet = FakeFleet([FENCE_OUTPUT])
    result = execute_task(
        "edit readme",
        "plan",
        fleet,
        verify_cmd=f"touch {marker}",
        hold_on_fail=False,
        worktree=git_repo,
    )
    assert result["status"] == "ok"
    assert (git_repo / "README").read_text(encoding="utf-8") == "applied from fence\n"
    assert Path(marker).exists()


def test_execute_task_injects_touches_file_body(tmp_path):
    from orchestrate import FILES_INJECT_HEADER, execute_task

    (tmp_path / "README").write_text("hi\n", encoding="utf-8")
    fleet = FakeFleet([GOOD_OUTPUT, GOOD_OUTPUT])
    execute_task(
        "say hello | README | none | mid",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
        worktree=tmp_path,
    )
    user = fleet.ep.last_messages[1]["content"]
    assert FILES_INJECT_HEADER in user
    assert "--- README ---" in user
    assert "hi\n" in user


def test_execute_task_omits_secret_and_plans_touches(tmp_path):
    from orchestrate import execute_task

    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / ".plans").mkdir()
    (tmp_path / ".plans" / "foo.md").write_text("nope\n", encoding="utf-8")
    (tmp_path / "README").write_text("ok\n", encoding="utf-8")
    fleet = FakeFleet([GOOD_OUTPUT, GOOD_OUTPUT])
    execute_task(
        "edit | README, .env, .plans/foo.md | none | mid",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
        worktree=tmp_path,
    )
    user = fleet.ep.last_messages[1]["content"]
    assert "--- README ---" in user
    assert "ok\n" in user
    assert "SECRET=1" not in user
    assert "nope" not in user
    assert "[omitted: .env (secret)]" in user
    assert "[omitted: .plans/foo.md (plans-deny)]" in user


def test_execute_task_drops_over_budget_touches_files(tmp_path, monkeypatch):
    from orchestrate import FILES_INJECT_HEADER, execute_task

    monkeypatch.setattr("orchestrate.load_prompt", lambda *a, **k: "sys")
    (tmp_path / "README").write_text("hi\n", encoding="utf-8")
    (tmp_path / "BIG.txt").write_text("B" * 20_000, encoding="utf-8")
    fleet = FakeFleet(
        [GOOD_OUTPUT, GOOD_OUTPUT],
        quirks={"max_context": 2500},
    )
    result = execute_task(
        "edit | README, BIG.txt | none | mid",
        "plan",
        fleet,
        verify_cmd=None,
        hold_on_fail=False,
        worktree=tmp_path,
    )
    assert result["status"] != "failed-budget"
    user = fleet.ep.last_messages[1]["content"]
    assert FILES_INJECT_HEADER in user
    assert "--- README ---" in user
    assert "hi\n" in user
    assert "B" * 1000 not in user
    assert "[omitted: BIG.txt (over budget)]" in user


class NamedEndpoint:
    def __init__(self, name, replies, *, model="m"):
        self.name = name
        self.replies = list(replies)
        self.calls = 0
        self.quirks = {}
        self.base_url = f"http://{name}/v1"
        self.model = model
        self.tier = "executor"
        self.aliases: list[str] = []

    def chat(self, messages, **kwargs):
        self.calls += 1
        item = self.replies.pop(0)
        if isinstance(item, tuple):
            fn, text = item
            if fn:
                fn()
            return text
        return item


class RosterFleet:
    def __init__(self, *, planner, executors, critic):
        self.planner = planner
        self.executors = list(executors)
        self.critic = critic

    def pick(self, role):
        if role == "planner":
            return self.planner
        if role == "critic":
            return self.critic
        return self.executors[0]

    def lookup(self, name):
        for ep in (self.planner, self.critic, *self.executors):
            if ep.name == name:
                return ep
        raise LookupError(name)

    def executor_candidates(self):
        return list(self.executors)


BAD_EXEC = "not a patch and no footer\n"


def test_main_failover_second_executor_ok(git_repo, monkeypatch):
    import json

    import orchestrate

    planner = NamedEndpoint("planner", [PLAN_TEXT], model="p")
    first = NamedEndpoint("ep-a", [BAD_EXEC, BAD_EXEC], model="a")

    def write_readme():
        (git_repo / "README").write_text("from-b\n")

    second = NamedEndpoint("ep-b", [(write_readme, GOOD_OUTPUT)], model="b")
    critic = NamedEndpoint("critic", ["review: ok"], model="c")
    fleet = RosterFleet(
        planner=planner, executors=[first, second], critic=critic,
    )
    out = _run_main(monkeypatch, git_repo, fleet)
    orchestrate.main()
    run = json.loads(out.read_text())
    assert sum(r["status"] == "ok" for r in run["results"]) >= 1
    assert run["review"] == "review: ok"
    assert first.calls == 2
    assert second.calls == 1
    assert critic.calls == 1
    assert planner.calls == 1


def test_main_no_failover_does_not_try_second(git_repo, monkeypatch):
    import json

    import orchestrate

    planner = NamedEndpoint("planner", [PLAN_TEXT], model="p")
    first = NamedEndpoint("ep-a", [BAD_EXEC, BAD_EXEC], model="a")
    second = NamedEndpoint("ep-b", [GOOD_OUTPUT], model="b")
    critic = NamedEndpoint("critic", ["review: ok"], model="c")
    fleet = RosterFleet(
        planner=planner, executors=[first, second], critic=critic,
    )
    out = _run_main(monkeypatch, git_repo, fleet, extra_args=("--no-failover",))
    with pytest.raises(SystemExit) as exc:
        orchestrate.main()
    assert exc.value.code == orchestrate.FAILED_NOOP_EXIT
    run = json.loads(out.read_text())
    assert run["review"].startswith("critic skipped: 0/")
    assert second.calls == 0
    assert critic.calls == 0


def test_main_failed_scope_does_not_failover(git_repo, monkeypatch):
    import json

    import orchestrate

    spec = git_repo / "spec.md"
    spec.write_text("## Files in scope\n- README\n", encoding="utf-8")

    planner = NamedEndpoint("planner", [PLAN_TEXT], model="p")

    def write_secret():
        (git_repo / "secret.py").write_text("x = 1\n", encoding="utf-8")

    first = NamedEndpoint("ep-a", [(write_secret, GOOD_OUTPUT)], model="a")
    second = NamedEndpoint("ep-b", [GOOD_OUTPUT], model="b")
    critic = NamedEndpoint("critic", ["review: ok"], model="c")
    fleet = RosterFleet(
        planner=planner, executors=[first, second], critic=critic,
    )
    out = _run_main(
        monkeypatch, git_repo, fleet,
        extra_args=("--scope-spec", str(spec)),
    )
    with pytest.raises(SystemExit) as exc:
        orchestrate.main()
    run = json.loads(out.read_text())
    assert run["results"][0]["status"] == "failed-scope"
    assert second.calls == 0
    assert critic.calls == 0
    assert exc.value.code in (
        orchestrate.FAILED_NOOP_EXIT, orchestrate.ROLE_VIOLATION_EXIT,
    )


def test_main_failover_all_noop_exits_2(git_repo, monkeypatch):
    import json

    import orchestrate

    planner = NamedEndpoint("planner", [PLAN_TEXT], model="p")
    first = NamedEndpoint("ep-a", [BAD_EXEC, BAD_EXEC], model="a")
    second = NamedEndpoint("ep-b", [BAD_EXEC, BAD_EXEC], model="b")
    critic = NamedEndpoint("critic", ["review: ok"], model="c")
    fleet = RosterFleet(
        planner=planner, executors=[first, second], critic=critic,
    )
    out = _run_main(monkeypatch, git_repo, fleet)
    with pytest.raises(SystemExit) as exc:
        orchestrate.main()
    assert exc.value.code == orchestrate.FAILED_NOOP_EXIT
    run = json.loads(out.read_text())
    assert run["review"].startswith("critic skipped: 0/")
    assert first.calls == 2
    assert second.calls == 2
    assert critic.calls == 0


def test_noop_retry_mentions_fence_and_unified_diff():
    import inspect

    import orchestrate

    src = inspect.getsource(orchestrate.execute_task)
    assert "unified diff" in src
    assert "whole-file fence" in src
