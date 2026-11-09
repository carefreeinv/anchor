import argparse
import subprocess
import sys
from pathlib import Path

import work_once
from plan_select import Worker


def _plan(path: Path, *, preferred: str = "mid", value: str = "medium",
          assignee: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    asg = f"- **Assignee:** {assignee}\n" if assignee is not None else ""
    path.write_text(
        f"# Plan: t\n\n- **Value:** {value}\n- **Preferred models:** {preferred}\n{asg}\n"
        "## Goal\ng\n\n## Steps\n| 1 | x |\n\n## Done when\n- [ ] ok\n",
        encoding="utf-8",
    )


def _root(tmp_path: Path) -> Path:
    for lane in (
        "bugs",
        "features",
        "in-progress",
        "ambiguous",
        "blocked",
        "drafts",
        "completed",
    ):
        (tmp_path / ".plans" / lane).mkdir(parents=True)
    return tmp_path


def test_list_exit_zero_and_shows_fit(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    code = work_once.main(
        ["--root", str(root), "--list", "--tier", "mid", "--agent-id", "list-me"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "features/a.md" in out
    assert "good" in out


def test_once_empty_backlog_exits_1(tmp_path, capsys):
    root = _root(tmp_path)
    code = work_once.main(["--root", str(root), "--once", "--no-run", "--tier", "mid", "--agent-id", "t"])
    assert code == 1


def test_once_no_fit_exits_1(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "hard.md", preferred="frontier")
    code = work_once.main(
        ["--root", str(root), "--once", "--no-run", "--tier", "small", "--agent-id", "tiny"]
    )
    assert code == 1


def test_triage_never_claims_and_reports_take(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    code = work_once.main(
        ["--root", str(root), "--triage", "--tier", "mid", "--agent-id", "t1"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "take: features/a.md" in out
    # Never claimed — still sitting in features/, not moved to in-progress/.
    assert (root / ".plans" / "features" / "a.md").is_file()
    assert not (root / ".plans" / "in-progress" / "a.md").is_file()


def test_triage_reports_reject_for_human_assignee(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "human.md", preferred="mid", assignee="alice")
    work_once.main(
        ["--root", str(root), "--triage", "--tier", "mid", "--agent-id", "t1"]
    )
    out = capsys.readouterr().out
    assert "reject: features/human.md" in out
    assert "alice" in out


def test_triage_reports_reject_for_underqualified(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "hard.md", preferred="frontier")
    code = work_once.main(
        ["--root", str(root), "--triage", "--tier", "small", "--agent-id", "tiny"]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "reject: features/hard.md" in out
    assert "underqualified" in out


def test_triage_reports_skip_for_overqualified(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "easy.md", preferred="small")
    code = work_once.main(
        ["--root", str(root), "--triage", "--tier", "frontier", "--agent-id", "big"]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "skip: features/easy.md" in out
    assert "overqualified" in out


def test_triage_reports_reject_for_missing_goal(tmp_path, capsys):
    root = _root(tmp_path)
    path = root / ".plans" / "features" / "no_goal.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Plan: t\n\n- **Preferred models:** mid\n\n## Context read\nnotes\n\n"
        "## Done when\n- [ ] x\n",
        encoding="utf-8",
    )
    code = work_once.main(
        ["--root", str(root), "--triage", "--tier", "mid", "--agent-id", "t1"]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "reject: features/no_goal.md" in out
    assert "Goal" in out


def test_triage_reports_reject_for_unmet_deps_unless_ignored(tmp_path, capsys):
    root = _root(tmp_path)
    path = root / ".plans" / "features" / "dep.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Plan: t\n\n- **Preferred models:** mid\n- **Depends on:** ghost-plan\n\n"
        "## Goal\ng\n\n## Done when\n- [ ] x\n",
        encoding="utf-8",
    )
    code = work_once.main(
        ["--root", str(root), "--triage", "--tier", "mid", "--agent-id", "t1"]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "reject: features/dep.md" in out
    assert "ghost-plan" in out

    code2 = work_once.main([
        "--root", str(root), "--triage", "--tier", "mid", "--agent-id", "t1",
        "--no-dep-check",
    ])
    assert code2 == 0
    out2 = capsys.readouterr().out
    assert "take: features/dep.md" in out2


def test_triage_empty_backlog_exits_1(tmp_path, capsys):
    root = _root(tmp_path)
    code = work_once.main(
        ["--root", str(root), "--triage", "--tier", "mid", "--agent-id", "t1"]
    )
    assert code == 1
    assert "no ready" in capsys.readouterr().out


def test_triage_never_touches_network(monkeypatch, tmp_path, capsys):
    """--triage must be pure local file I/O — no anchor_client.Endpoint.chat call."""
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")

    def _boom(*a, **k):
        raise AssertionError("triage must never dispatch a chat request")

    monkeypatch.setattr("anchor_client.Endpoint.chat", _boom, raising=False)
    code = work_once.main(
        ["--root", str(root), "--triage", "--tier", "mid", "--agent-id", "t1"]
    )
    assert code == 0


def test_bare_loop_never_picks_human_assigned(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "hers.md", preferred="mid", assignee="alice")
    code = work_once.main(
        ["--root", str(root), "--once", "--no-run", "--tier", "mid", "--agent-id", "w1"]
    )
    assert code == 1
    assert (root / ".plans" / "features" / "hers.md").is_file()


def test_named_human_assigned_refused_then_forced(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "hers.md", preferred="mid", assignee="alice")
    # Named claim of a human plan is refused by default (exit 1, file stays put).
    code = work_once.main(
        ["--root", str(root), "--slug", "hers", "--no-run", "--tier", "mid", "--agent-id", "w1"]
    )
    assert code == 1
    assert "assigned to alice" in capsys.readouterr().err
    assert (root / ".plans" / "features" / "hers.md").is_file()
    # --allow-assigned forces it (operator override).
    code = work_once.main(
        ["--root", str(root), "--slug", "hers", "--no-run", "--tier", "mid",
         "--agent-id", "w1", "--allow-assigned"]
    )
    assert code == 0
    assert (root / ".plans" / "in-progress" / "hers.md").is_file()


def test_once_moves_to_in_progress_and_blocks_others(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    code = work_once.main(
        ["--root", str(root), "--once", "--no-run", "--tier", "mid", "--agent-id", "w1"]
    )
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("in-progress/a.md")
    assert (root / ".plans" / "in-progress" / "a.md").is_file()
    assert not (root / ".plans" / "features" / "a.md").exists()
    # second worker cannot claim the moved plan
    code2 = work_once.main(
        ["--root", str(root), "--once", "--no-run", "--tier", "mid", "--agent-id", "w2"]
    )
    assert code2 == 1


def test_bare_pick_never_resumes_takes_next_ready(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    _plan(root / ".plans" / "features" / "b.md", preferred="mid")
    work_once.main(
        ["--root", str(root), "--once", "--no-run", "--tier", "mid", "--agent-id", "w1"]
    )
    capsys.readouterr()  # clear first claim (a.md → in-progress)
    # A second bare pick for the same agent does NOT resume in-progress/a.md;
    # it claims the next ready plan (b.md). Resume is an explicit --path claim.
    code = work_once.main(
        ["--root", str(root), "--once", "--no-run", "--tier", "mid", "--agent-id", "w1"]
    )
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("in-progress/b.md")
    assert "in-progress/a.md" not in out


def test_heartbeat_extends_lease(tmp_path, capsys):
    import plan_lease

    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    work_once.main(
        ["--root", str(root), "--once", "--no-run", "--tier", "mid", "--agent-id", "w1"]
    )
    capsys.readouterr()
    plans = root / ".plans"
    before = plan_lease.read_lease(plans, "in-progress/a.md").expires_at
    code = work_once.main(
        ["--root", str(root), "--heartbeat", "in-progress/a.md", "--agent-id", "w1"]
    )
    assert code == 0
    after = plan_lease.read_lease(plans, "in-progress/a.md").expires_at
    assert after >= before


def test_recover_only_takes_over_expired_lease(tmp_path):
    import plan_lease

    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    work_once.main(
        ["--root", str(root), "--once", "--no-run", "--tier", "mid", "--agent-id", "w1"]
    )
    plans = root / ".plans"
    # Active foreign lease → recover refused.
    code = work_once.main(
        ["--root", str(root), "--recover", "--path", "in-progress/a.md",
         "--agent-id", "w2"]
    )
    assert code == 2
    assert plan_lease.owner_of(plans, "in-progress/a.md") == "w1"

    # Expire w1's lease → recover by w2 succeeds and transfers ownership.
    import time

    from plan_lease import Lease, _write_lease_force, lease_path

    _write_lease_force(
        lease_path(plans, "in-progress/a.md"),
        Lease(
            plan_rel="in-progress/a.md",
            agent_id="w1",
            claimed_at=time.time() - 100,
            expires_at=time.time() - 10,
        ),
    )
    code = work_once.main(
        ["--root", str(root), "--recover", "--path", "in-progress/a.md",
         "--agent-id", "w2"]
    )
    assert code == 0
    assert plan_lease.owner_of(plans, "in-progress/a.md") == "w2"


def test_refuse_draft_path(tmp_path):
    root = _root(tmp_path)
    draft = root / ".plans" / "drafts" / "nope.md"
    _plan(draft, preferred="mid")
    code = work_once.main(
        [
            "--root",
            str(root),
            "--path",
            str(draft),
            "--tier",
            "mid",
            "--agent-id",
            "w",
        ]
    )
    assert code == 2


def test_run_refuses_underqualified_without_starting_orchestrate(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "midwork.md", preferred="small, mid")

    def _boom(*_a, **_k):
        raise AssertionError("orchestrate must not start")

    monkeypatch.setattr(work_once, "run_orchestrate", _boom)
    code = work_once.main(
        [
            "--root", str(root), "--once", "--slug", "midwork",
            "--tier", "small", "--agent-id", "tiny", "--run",
        ]
    )
    assert code == 2
    assert "underqualified" in capsys.readouterr().err
    assert (root / ".plans" / "in-progress" / "midwork.md").is_file()


def test_no_fit_check_picks_mismatch(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "hard.md", preferred="frontier")
    code = work_once.main(
        [
            "--root",
            str(root),
            "--once", "--no-run",
            "--tier",
            "small",
            "--no-fit-check",
            "--agent-id",
            "s",
        ]
    )
    assert code == 0
    assert "in-progress/hard.md" in capsys.readouterr().out


def test_cli_subprocess_list(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "bugs" / "b.md", preferred="mid")
    script = Path(__file__).resolve().parent.parent / "scripts" / "work_once.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(root),
            "--list",
            "--tier",
            "mid",
            "--agent-id",
            "cli",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "bugs/b.md" in proc.stdout


def test_resolve_worker_ignores_grok_shaped_agent_id():
    """Lease ids like grok-effort-tier-46 must not promote via --effort."""
    import argparse

    args = argparse.Namespace(
        endpoint=None,
        model=None,
        agent_id="grok-effort-tier-46",
        tier="mid",
        effort="high",
        registry=None,
    )
    w = work_once.resolve_worker(args)
    assert w.name == "work-once"
    assert w.tier == "mid"

    args.effort = "xhigh"
    assert work_once.resolve_worker(args).tier == "mid"

    args.model = "Grok 4.6"
    args.effort = "high"
    w = work_once.resolve_worker(args)
    assert w.tier == "reasoner"


def test_registry_tier_mapping():
    w = Worker("Qwen", "executor-heavy")
    assert w.tier == "mid"


def test_park_via_cli(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "thin.md", preferred="mid")
    code = work_once.main(
        [
            "--root",
            str(root),
            "--path",
            str(root / ".plans" / "features" / "thin.md"),
            "--park",
            "ambiguous",
            "--agent-id",
            "w",
        ]
    )
    assert code == 0
    assert (root / ".plans" / "ambiguous" / "thin.md").is_file()
    assert "ambiguous" in capsys.readouterr().out


# -- site inference-load policy --------------------------------------------

def _registry(tmp_path: Path, *, base_url: str = "http://127.0.0.1:11434/v1",
              local: str = "") -> Path:
    reg = tmp_path / "endpoints.yaml"
    reg.write_text(
        "endpoints:\n"
        "  - name: box\n    tier: swarm\n"
        f"    base_url: {base_url}\n    model: qwen3:4b\n{local}",
        encoding="utf-8",
    )
    return reg


def _set_level(root: Path, level: str) -> None:
    import inference_load as il

    il.write_cache(root / il.DEFAULT_CACHE_REL, il.LoadPolicy(level=level, source="test"))


def test_local_worker_does_not_claim_when_level_is_off(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    _set_level(root, "off")
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--endpoint", "box",
        "--registry", str(_registry(tmp_path)), "--agent-id", "w",
    ])
    assert code == 1
    assert "capped" in capsys.readouterr().err
    # The plan is left in the ready lane, unclaimed and unleased.
    assert (root / ".plans" / "features" / "a.md").is_file()
    assert not list((root / ".plans" / ".leases").glob("*.json"))


def test_local_worker_claims_when_level_is_full(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    _set_level(root, "high")
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--endpoint", "box",
        "--registry", str(_registry(tmp_path)), "--agent-id", "w",
    ])
    assert code == 0
    assert (root / ".plans" / "in-progress" / "a.md").is_file()


def test_level_low_bars_a_mid_tier_local_worker(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    _set_level(root, "low")
    reg = _registry(tmp_path)
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--endpoint", "box", "--tier", "mid",
        "--registry", str(reg), "--agent-id", "w",
    ])
    assert code == 1
    assert "not allowed at level=low" in capsys.readouterr().err


def test_cloud_endpoint_is_never_capped_by_site_load(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    _set_level(root, "off")
    reg = _registry(tmp_path, base_url="https://api.example.com/v1")
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--endpoint", "box",
        "--registry", str(reg), "--agent-id", "w",
    ])
    assert code == 0
    assert (root / ".plans" / "in-progress" / "a.md").is_file()


def test_explicit_local_false_opts_a_private_endpoint_out(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    _set_level(root, "off")
    reg = _registry(tmp_path, base_url="http://10.0.1.10:8000/v1", local="    local: false\n")
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--endpoint", "box",
        "--registry", str(reg), "--agent-id", "w",
    ])
    assert code == 0


def test_ignore_load_overrides_the_cap(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    _set_level(root, "off")
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--endpoint", "box", "--ignore-load",
        "--registry", str(_registry(tmp_path)), "--agent-id", "w",
    ])
    assert code == 0


def test_local_worker_flag_gates_without_an_endpoint(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    _set_level(root, "off")
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--tier", "small", "--local-worker",
        "--agent-id", "w",
    ])
    assert code == 1
    assert "capped" in capsys.readouterr().err


def test_tier_worker_without_local_flag_is_not_gated(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    _set_level(root, "off")
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--tier", "small", "--agent-id", "w",
    ])
    assert code == 0


def test_unconfigured_site_leaves_local_workers_alone(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--endpoint", "box",
        "--registry", str(_registry(tmp_path)), "--agent-id", "w",
    ])
    assert code == 0
    assert (root / ".plans" / "in-progress" / "a.md").is_file()


def test_stale_policy_holds_local_work_by_default(tmp_path, capsys):
    import time

    import inference_load as il

    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="small")
    il.write_cache(
        root / il.DEFAULT_CACHE_REL,
        il.LoadPolicy(level="high", ttl_s=30, received_at=time.time() - 600),
    )
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--endpoint", "box",
        "--registry", str(_registry(tmp_path)), "--agent-id", "w",
    ])
    assert code == 1
    assert "failsafe:hold" in capsys.readouterr().err


def test_crude_parser_strips_inline_comments_on_the_shipped_registry():
    # Regression: the repo's own endpoints.yaml annotates `local: true` with a
    # trailing comment. Parsed naively, that string missed the truthy set and
    # read as NOT local — turning the governor off for that endpoint on any
    # install without PyYAML, the exact case this parser exists for.
    registry = Path(work_once.__file__).resolve().parent / "endpoints.yaml"
    parsed = work_once._parse_endpoints_crude(registry.read_text(encoding="utf-8"))
    h100 = next(e for e in parsed if e["name"] == "h100-executor")
    assert h100["local"] == "true"
    assert h100["base_url"] == "http://10.0.1.10:8000/v1"

    import inference_load as il

    assert il.endpoint_is_local(h100) is True


def test_crude_value_handles_comments_quotes_and_urls():
    assert work_once._crude_value("tier: swarm   # tiny") == "swarm"
    assert work_once._crude_value('model: "qwen3:4b"') == "qwen3:4b"
    assert work_once._crude_value("base_url: http://x/v1#frag") == "http://x/v1#frag"
    assert work_once._crude_value("name: box") == "box"


def test_ensure_worktree_failure_returns_plan_to_ready(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _plan(root / ".plans" / "bugs" / "a.md", preferred="mid")
    from worktree_for_agent import WorktreeError

    def boom(*_a, **_k):
        raise WorktreeError("already checked out at /tmp/other")

    monkeypatch.setattr("worktree_for_agent.ensure_worktree", boom)
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--ensure-worktree",
        "--tier", "mid", "--agent-id", "w", "--slug", "a",
    ])
    assert code == 2
    assert (root / ".plans" / "bugs" / "a.md").is_file()
    assert not (root / ".plans" / "in-progress" / "a.md").is_file()


def test_run_with_ensure_worktree_forwards_worktree_to_orchestrate(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    captured: list[list[str]] = []

    class Rec:
        path = tmp_path / "wt"
        branch = "feature/a"
        integration = "dev"

    Rec.path.mkdir()

    def fake_ensure(project, agent_id, slug=None):
        return Rec()

    def fake_run(plan_path, extra):
        captured.append(list(extra))
        return 0

    monkeypatch.setattr("worktree_for_agent.ensure_worktree", fake_ensure)
    monkeypatch.setattr(work_once, "run_orchestrate", fake_run)
    code = work_once.main([
        "--root", str(root), "--once", "--run", "--ensure-worktree",
        "--tier", "mid", "--agent-id", "w", "--slug", "a",
    ])
    assert code == 0
    assert captured and captured[0][:2] == ["--worktree", str(Rec.path)]


def test_orchestrate_worktree_args_uses_ensure(tmp_path, monkeypatch):
    class Rec:
        path = tmp_path / "wt"
        branch = "feature/a"

    Rec.path.mkdir()

    def fake_ensure(project, agent_id, slug=None):
        assert slug == "a"
        return Rec()

    monkeypatch.setattr("worktree_for_agent.ensure_worktree", fake_ensure)
    monkeypatch.setattr(work_once, "_git_branch", lambda _p: "feature/a")
    extra = work_once.orchestrate_worktree_args(tmp_path, "w", "a")
    assert extra == ["--worktree", str(Rec.path)]


def test_orchestrate_worktree_args_skips_mainline(tmp_path, monkeypatch):
    class Rec:
        path = tmp_path / "wt"

    Rec.path.mkdir()

    monkeypatch.setattr(
        "worktree_for_agent.ensure_worktree",
        lambda *a, **k: Rec(),
    )
    monkeypatch.setattr(work_once, "_git_branch", lambda _p: "main")
    extra = work_once.orchestrate_worktree_args(tmp_path, "w", "a")
    assert extra == []


def test_run_forwards_endpoint_and_registry_before_worktree(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    captured: list[list[str]] = []
    reg = tmp_path / "ep.yaml"
    reg.write_text(
        "endpoints:\n  - name: pin\n    tier: executor\n    model: x\n",
        encoding="utf-8",
    )

    class Rec:
        path = tmp_path / "wt"
        branch = "feature/a"
        integration = "dev"

    Rec.path.mkdir()

    def fake_ensure(project, agent_id, slug=None):
        return Rec()

    def fake_run(plan_path, extra):
        captured.append(list(extra))
        return 0

    monkeypatch.setattr("worktree_for_agent.ensure_worktree", fake_ensure)
    monkeypatch.setattr(work_once, "run_orchestrate", fake_run)
    monkeypatch.setattr(
        work_once,
        "resolve_worker",
        lambda args: work_once.Worker(name="pin", tier="mid"),
    )
    code = work_once.main([
        "--root", str(root), "--once", "--run", "--ensure-worktree",
        "--endpoint", "pin", "--registry", str(reg),
        "--no-fit-check", "--agent-id", "w", "--slug", "a",
    ])
    assert code == 0
    assert captured
    extra = captured[0]
    assert extra[:4] == ["--registry", str(reg), "--endpoint", "pin"]
    assert extra[4:6] == ["--worktree", str(Rec.path)]


def test_run_exit_0_finishes_to_review_needed(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (root / ".plans" / "review-needed").mkdir()
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a, **k: 0)

    from plan_finish_gate import FinishGate

    monkeypatch.setattr(work_once, "check_finish", lambda *a, **k: FinishGate(True, "test"))
    code = work_once.main([
        "--root", str(root), "--once", "--slug", "a", "--run",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 0
    assert (root / ".plans" / "review-needed" / "a.md").is_file()
    assert not (root / ".plans" / "in-progress" / "a.md").is_file()


def test_run_exit_0_empty_work_stays_in_progress(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (root / ".plans" / "review-needed").mkdir()
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a, **k: 0)
    from plan_finish_gate import FinishGate
    monkeypatch.setattr(
        work_once, "check_finish", lambda *a, **k: FinishGate(False, "plan-only"),
    )
    code = work_once.main([
        "--root", str(root), "--once", "--slug", "a", "--run",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 0
    assert (root / ".plans" / "in-progress" / "a.md").is_file()
    assert not (root / ".plans" / "review-needed" / "a.md").is_file()


def test_run_exit_2_does_not_finish(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (root / ".plans" / "review-needed").mkdir()
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a, **k: 2)
    code = work_once.main([
        "--root", str(root), "--once", "--slug", "a", "--run",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 2
    assert (root / ".plans" / "in-progress" / "a.md").is_file()
    assert not (root / ".plans" / "review-needed" / "a.md").is_file()


def test_run_exit_0_no_finish_flag(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (root / ".plans" / "review-needed").mkdir()
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a, **k: 0)
    code = work_once.main([
        "--root", str(root), "--once", "--slug", "a", "--run", "--no-finish",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 0
    assert (root / ".plans" / "in-progress" / "a.md").is_file()


def test_once_without_run_flag_still_orchestrates(tmp_path, monkeypatch):
    root = _root(tmp_path)
    (root / ".plans" / "review-needed").mkdir()
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    called: list[int] = []

    def fake_run(plan_path, extra):
        called.append(1)
        return 0

    monkeypatch.setattr(work_once, "run_orchestrate", fake_run)
    from plan_finish_gate import FinishGate
    monkeypatch.setattr(work_once, "check_finish", lambda *a, **k: FinishGate(True, "test"))
    code = work_once.main([
        "--root", str(root), "--once", "--slug", "a",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 0
    assert called == [1]
    assert (root / ".plans" / "review-needed" / "a.md").is_file()


def test_no_run_skips_orchestrate(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")

    def boom(*a, **k):
        raise AssertionError("orchestrate must not run with --no-run")

    monkeypatch.setattr(work_once, "run_orchestrate", boom)
    code = work_once.main([
        "--root", str(root), "--once", "--no-run", "--slug", "a",
        "--tier", "mid", "--agent-id", "t", "--no-fit-check",
    ])
    assert code == 0
    assert (root / ".plans" / "in-progress" / "a.md").is_file()


def test_nick_effort_applies_unless_cli_effort_wins(tmp_path):
    root = _root(tmp_path)
    reg = tmp_path / "ep.yaml"
    overlay = root / "var" / "endpoints.local.yaml"
    overlay.parent.mkdir()
    reg.write_text(
        "endpoints:\n"
        "  - name: pin\n    tier: executor\n    model: grok-4.6\n"
        "    base_url: http://x/v1\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "endpoints:\n  - name: pin\n    aliases: [lightning]\n    effort: low\n",
        encoding="utf-8",
    )
    ns = argparse.Namespace(
        endpoint="lightning", registry=str(reg), root=str(root),
        model=None, tier=None, effort=None,
    )
    w = work_once.resolve_worker(ns)
    assert w.tier == "mid"  # grok + low
    ns.effort = "high"
    w2 = work_once.resolve_worker(ns)
    assert w2.tier == "reasoner"  # CLI --effort wins
