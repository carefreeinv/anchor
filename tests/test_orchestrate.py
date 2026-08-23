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


def test_fit_gate_line_finds_token_after_preflight():
    from orchestrate import fit_gate_line

    line = fit_gate_line(RULE13_THEN_REROUTE)
    assert line is not None and line.startswith("SUGGEST-REROUTE: coding-agent")
    buried = "\n".join(f"note {i}" for i in range(15))
    buried += "\nSUGGEST-REROUTE: coding-agent — too late\n"
    assert fit_gate_line(buried) is None


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
        (None, GOOD_OUTPUT),   # executor (writes nothing it shouldn't)
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

    from fleet_metrics import record_task_outcome
    import orchestrate

    task_text = split_tasks(PLAN_TEXT)[0]
    ledger = git_repo / "var" / "fleet-metrics" / "outcomes.jsonl"
    for i in range(2):
        record_task_outcome(
            output="## Result\nfailed\n## How to verify\nn/a\n",
            verify_exit=1, model="frontier-model", tier="frontier", task=task_text,
            ledger_path=ledger, timestamp=float(i),
        )

    # planner call → PLAN_TEXT; executor call is refused before dispatch; critic call → verdict
    fleet = TopTierFleet([PLAN_TEXT, "review: ok"])
    out = _run_main(monkeypatch, git_repo, fleet)

    orchestrate.main()  # no SystemExit — a human-report is not a role violation

    assert fleet.ep.calls == 2  # planner + critic only; executor never dispatched

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
