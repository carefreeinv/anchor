"""`anchor plans|work|review|draft` — the dual-mode contract, proven rather than asserted.

Headless runs (the default whenever stdio is not a terminal) must never block on
input, never merge, never start a model, and always emit parseable JSON. Only an
interactive run with an operator's answer may merge, and only through
merge_feature's gate onto the integration branch.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import anchor_cli
import plan_lease
import plan_store
import pytest

SCRIPTS = Path(anchor_cli.__file__).resolve().parent

PLAN = """# Plan: {slug}

- **Value:** medium
- **Priority:** {priority}
- **Preferred models:** mid
- **Depends on:** none

## Goal
Do {slug}.

## Steps
1. thing

## Done when
- done
"""


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def cli(argv, *, interactive=False, answers=()):
    """Run the CLI in-process. Returns (exit_code, parsed JSON or text)."""
    out = TTY() if interactive else io.StringIO()
    stdin = TTY() if interactive else io.StringIO()
    feed = iter(answers)

    def read(_prompt: str) -> str:
        try:
            return next(feed)
        except StopIteration:
            raise EOFError from None

    code = anchor_cli.main(argv, stdin=stdin, stdout=out, env={}, read=read)
    text = out.getvalue()
    if not interactive or "--json" in argv:
        return code, json.loads(text)
    return code, text


def write(project: Path, lane: str, slug: str, priority: str = "P2") -> Path:
    path = project / ".plans" / lane / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PLAN.format(slug=slug, priority=priority), encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for lane in ("bugs", "features", "in-progress", "review-needed", "drafts",
                 "completed", "ambiguous", "blocked"):
        (root / ".plans" / lane).mkdir(parents=True)
    return root


# --- mode detection -------------------------------------------------------------


def test_mode_is_interactive_only_with_two_ttys_and_no_override():
    assert anchor_cli.detect_mode(False, stdin=TTY(), stdout=TTY(), env={}).interactive


@pytest.mark.parametrize(
    "flag,stdin,stdout,env,reason",
    [
        (True, TTY(), TTY(), {}, "--non-interactive"),
        (False, TTY(), TTY(), {"ANCHOR_NONINTERACTIVE": "1"}, "ANCHOR_NONINTERACTIVE"),
        (False, io.StringIO(), TTY(), {}, "stdin is not a terminal"),
        (False, TTY(), io.StringIO(), {}, "stdout is not a terminal"),
        (False, object(), TTY(), {}, "stdio not inspectable"),
    ],
)
def test_every_doubt_resolves_to_headless(flag, stdin, stdout, env, reason):
    mode = anchor_cli.detect_mode(flag, stdin=stdin, stdout=stdout, env=env)
    assert not mode.interactive and mode.reason == reason


def test_closed_stdin_is_headless():
    closed = io.StringIO()
    closed.close()
    assert not anchor_cli.detect_mode(False, stdin=closed, stdout=TTY(), env={}).interactive


def test_headless_prompter_cannot_ask():
    ask = anchor_cli.Prompter(anchor_cli.Mode(False, "test"), read=lambda _p: pytest.fail("asked"))
    with pytest.raises(anchor_cli.NeedsOperator):
        ask.choose("x", "Pick", ("a", "b"))
    with pytest.raises(anchor_cli.NeedsOperator):
        ask.text("x", "Say")


# --- plans ------------------------------------------------------------------------


def test_plans_lists_every_lane(project):
    write(project, "bugs", "b1")
    write(project, "drafts", "d1")
    code, doc = cli(["plans", "--root", str(project)])
    assert code == 0 and doc["schema_version"] == 1 and doc["mode"] == "non-interactive"
    assert [(p["lane"], p["slug"]) for p in doc["result"]["plans"]] == [
        ("bugs", "b1"), ("drafts", "d1"),
    ]
    assert doc["result"]["counts"]["bugs"] == 1


def test_missing_plans_tree_is_a_hard_error(tmp_path):
    code, doc = cli(["plans", "--root", str(tmp_path)])
    assert code == 2 and "no .plans/" in doc["error"]


# --- work -------------------------------------------------------------------------


def _mini_registry(root: Path) -> Path:
    reg = root / "endpoints.yaml"
    reg.write_text(
        "endpoints:\n"
        "  - name: nemotron-build\n    tier: executor\n"
        "    base_url: https://integrate.api.nvidia.com/v1\n"
        "    model: pin-model\n"
        "roles:\n  executor: [executor]\n",
        encoding="utf-8",
    )
    return reg


def test_models_list_json_includes_aliases(project):
    reg = _mini_registry(project)
    overlay = project / "var" / "endpoints.local.yaml"
    overlay.parent.mkdir()
    overlay.write_text(
        "endpoints:\n"
        "  - name: nemotron-build\n    aliases: [lightning]\n"
        "    machine: flippy\n    effort: low\n",
        encoding="utf-8",
    )
    code, doc = cli(
        ["models", "list", "--root", str(project), "--registry", str(reg), "--json"]
    )
    assert code == 0
    row = next(r for r in doc["result"]["endpoints"] if r["name"] == "nemotron-build")
    assert row["aliases"] == ["lightning"]
    assert row["machine"] == "flippy"
    assert row["effort"] == "low"
    assert row["model"]


def test_models_nick_writes_overlay_not_shared(project, tmp_path):
    reg = _mini_registry(project)
    overlay = tmp_path / "nick.yaml"
    code, doc = cli([
        "models", "nick", "lightning",
        "--root", str(project),
        "--endpoint", "nemotron-build",
        "--machine", "flippy",
        "--effort", "low",
        "--overlay", str(overlay),
        "--registry", str(reg),
        "--json",
    ])
    assert code == 0
    assert overlay.is_file()
    assert "lightning" in overlay.read_text(encoding="utf-8")
    assert "aliases:" not in reg.read_text(encoding="utf-8")
    assert doc["result"]["name"] == "nemotron-build"
    assert "lightning" in doc["result"]["aliases"]


def test_models_nick_finds_overlay_only_endpoint(project, monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    overlay = cfg / "endpoints.local.yaml"
    overlay.write_text(
        "endpoints:\n"
        "  - name: nemotron-build\n    tier: executor\n"
        "    base_url: https://integrate.api.nvidia.com/v1\n"
        "    model: pin-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCHOR_CONFIG_DIR", str(cfg))
    empty = tmp_path / "empty.yaml"
    empty.write_text("endpoints: []\n", encoding="utf-8")
    code, doc = cli([
        "models", "nick", "lightning",
        "--root", str(project),
        "--endpoint", "nemotron-build",
        "--registry", str(empty),
        "--json",
    ])
    assert code == 0, doc
    assert "lightning" in overlay.read_text(encoding="utf-8")
    assert "lightning" in doc["result"]["aliases"]


def test_work_list_resolves_endpoint_nickname(project):
    write(project, "features", "f1")
    reg = _mini_registry(project)
    overlay = project / "var" / "endpoints.local.yaml"
    overlay.parent.mkdir()
    overlay.write_text(
        "endpoints:\n  - name: nemotron-build\n    aliases: [lightning]\n",
        encoding="utf-8",
    )
    code, doc = cli([
        "work", "--list", "--root", str(project),
        "--endpoint", "lightning", "--registry", str(reg), "--tier", "mid",
    ])
    assert code == 0
    (row,) = doc["result"]["plans"]
    assert row["rel"] == "features/f1.md"
    assert row["fit"] == "good"


def test_work_list_uses_plan_select_fit(project):
    write(project, "features", "f1")
    code, doc = cli(["work", "--list", "--root", str(project), "--tier", "mid"])
    assert code == 0
    (row,) = doc["result"]["plans"]
    assert row["rel"] == "features/f1.md" and row["fit"] == "good" and row["deps"] == "met"


def test_work_list_empty_is_nothing_to_do(project):
    code, doc = cli(["work", "--list", "--root", str(project)])
    assert code == 1 and doc["result"]["plans"] == []


def test_work_claims_and_hands_execution_back(project):
    write(project, "features", "f1", priority="P3")
    write(project, "bugs", "b1")
    code, doc = cli(["work", "--root", str(project), "--agent-id", "a1"])
    assert code == 0
    assert doc["result"]["plan"] == "in-progress/b1.md"
    assert plan_store.owner(project / ".plans", "in-progress/b1.md") == "a1"
    assert [p["step"] for p in doc["pending"]] == ["execute"]
    assert doc["pending"][0]["needs"] == "model"


def test_work_run_is_refused_headless(project, monkeypatch):
    import work_once

    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a: pytest.fail("model started"))
    write(project, "features", "f1")
    code, doc = cli(["work", "--root", str(project), "--agent-id", "a1", "--run"])
    assert code == 0
    assert any("--run ignored" in n for n in doc["notes"])
    assert doc["pending"][0]["step"] == "execute"


def test_work_run_forwards_endpoint_interactive(project, monkeypatch, tmp_path):
    import work_once

    seen: list[list[str]] = []

    def fake_orch(_dest, extra):
        seen.append(list(extra))
        return 0

    monkeypatch.setattr(work_once, "run_orchestrate", fake_orch)
    monkeypatch.setattr(
        work_once,
        "orchestrate_worktree_args",
        lambda *a, **k: ["--worktree", str(tmp_path / "wt")],
    )
    write(project, "features", "f1")
    reg = tmp_path / "ep.yaml"
    reg.write_text(
        "endpoints:\n  - name: nemoclaw\n    tier: executor\n    model: qwen3:8b\n",
        encoding="utf-8",
    )
    code, _doc = cli(
        [
            "work", "--root", str(project), "--agent-id", "a1", "--run",
            "--endpoint", "nemoclaw", "--registry", str(reg), "--no-fit-check",
        ],
        interactive=True,
    )
    assert code == 0
    assert seen
    extra = seen[0]
    assert extra[:4] == ["--registry", str(reg), "--endpoint", "nemoclaw"]
    assert extra[4:6][0] == "--worktree"
    assert len(extra) >= 6


def test_work_run_interactive_extras_include_worktree(project, monkeypatch, tmp_path):
    import work_once

    seen: list[list[str]] = []
    wt = tmp_path / "agent-wt"
    wt.mkdir()

    class Rec:
        path = wt

    def fake_orch(_dest, extra):
        seen.append(list(extra))
        return 0

    monkeypatch.setattr(work_once, "run_orchestrate", fake_orch)
    monkeypatch.setattr(
        work_once,
        "orchestrate_worktree_args",
        lambda *a, **k: ["--worktree", str(wt)],
    )
    write(project, "features", "f1")
    code, _doc = cli(
        ["work", "--root", str(project), "--agent-id", "a1", "--run"],
        interactive=True,
    )
    assert code == 0
    assert seen and seen[0][:2] == ["--worktree", str(wt)]


def test_work_run_interactive_exit_0_parks_review_needed(project, monkeypatch):
    import work_once

    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a, **k: 0)
    monkeypatch.setattr(work_once, "orchestrate_worktree_args", lambda *a, **k: [])
    write(project, "features", "f1")
    code, doc = cli(
        ["work", "--root", str(project), "--agent-id", "a1", "--run", "--json"],
        interactive=True,
    )
    assert code == 0
    assert doc["result"]["plan"] == "review-needed/f1.md"
    assert (project / ".plans" / "review-needed" / "f1.md").is_file()
    assert not (project / ".plans" / "in-progress" / "f1.md").is_file()


def test_work_run_interactive_exit_2_stays_in_progress(project, monkeypatch):
    import work_once

    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a, **k: 2)
    monkeypatch.setattr(work_once, "orchestrate_worktree_args", lambda *a, **k: [])
    write(project, "features", "f1")
    code, doc = cli(
        ["work", "--root", str(project), "--agent-id", "a1", "--run"],
        interactive=True,
    )
    assert code == 2
    assert (project / ".plans" / "in-progress" / "f1.md").is_file()
    assert not (project / ".plans" / "review-needed" / "f1.md").is_file()


def test_work_run_interactive_no_finish_keeps_lease(project, monkeypatch):
    import work_once

    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a, **k: 0)
    monkeypatch.setattr(work_once, "orchestrate_worktree_args", lambda *a, **k: [])
    write(project, "features", "f1")
    code, doc = cli(
        ["work", "--root", str(project), "--agent-id", "a1", "--run", "--no-finish", "--json"],
        interactive=True,
    )
    assert code == 0
    assert (project / ".plans" / "in-progress" / "f1.md").is_file()
    assert any("no-finish" in n for n in doc["notes"])


def test_work_run_headless_notes_dropped_endpoint(project, monkeypatch):
    import work_once

    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a: pytest.fail("model started"))
    write(project, "features", "f1")
    code, doc = cli(
        ["work", "--root", str(project), "--agent-id", "a1", "--run",
         "--endpoint", "h100-executor"],
    )
    assert code == 0
    assert any("h100-executor" in n and "--endpoint" in n for n in doc["notes"])


def test_work_heartbeat_finish_return(project):
    plans = project / ".plans"
    write(project, "features", "f1")
    write(project, "features", "f2")
    cli(["work", "f1", "--root", str(project), "--agent-id", "a1"])
    cli(["work", "f2", "--root", str(project), "--agent-id", "a1"])

    code, doc = cli(["work", "--heartbeat", "f1", "--root", str(project), "--agent-id", "a1"])
    assert code == 0 and doc["result"]["plan"] == "in-progress/f1.md"

    code, doc = cli(["work", "--heartbeat", "f1", "--root", str(project), "--agent-id", "other"])
    assert code == 2 and doc["action"] == "heartbeat"
    assert "a1" in doc["error"]

    code, doc = cli(["work", "--finish", "f1", "--root", str(project), "--agent-id", "someone-else"])
    assert code == 2 and "lease holder" in doc["error"]
    assert doc["action"] == "finish"

    code, doc = cli(["work", "--finish", "f1", "--root", str(project), "--agent-id", "a1"])
    assert code == 0 and doc["result"]["plan"] == "review-needed/f1.md"
    assert plan_lease.read_lease(plans, "in-progress/f1.md") is None

    code, doc = cli(["work", "--return", "f2", "--root", str(project), "--agent-id", "a1"])
    assert code == 0 and doc["result"]["plan"] == "features/f2.md"


# --- review -----------------------------------------------------------------------


def test_review_list(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "--root", str(project)])
    assert code == 0 and [p["slug"] for p in doc["result"]["plans"]] == ["r1"]


def test_review_headless_stops_for_the_decision_with_the_package(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project)])
    assert code == anchor_cli.EXIT_NEEDS_OPERATOR
    assert doc["result"]["plan"] == "review-needed/r1.md"
    steps = {(p["step"], p["needs"]) for p in doc["pending"]}
    assert steps == {("critic", "model"), ("review-decision", "operator")}
    assert (project / ".plans" / "review-needed" / "r1.md").is_file()


def test_review_interactive_skip_changes_nothing(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json"],
                    interactive=True, answers=["skip"])
    assert code == 0 and doc["result"]["decision"] == "skip"
    assert (project / ".plans" / "review-needed" / "r1.md").is_file()


def test_review_needs_work_requires_notes_and_moves(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json"],
                    interactive=True, answers=["needs-work", "bugs", ""])
    assert code == 3 and doc["pending"][-1]["step"] == "needs-work-notes"
    assert (project / ".plans" / "review-needed" / "r1.md").is_file()

    code, doc = cli(["review", "r1", "--root", str(project), "--json"],
                    interactive=True, answers=["needs-work", "bugs", "Done when #1 fails"])
    assert code == 0 and doc["result"]["moved_to"] == "bugs/r1.md"
    body = (project / ".plans" / "bugs" / "r1.md").read_text(encoding="utf-8")
    assert "## Review notes\nDone when #1 fails" in body


def test_review_defer_moves_to_blocked(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json"],
                    interactive=True, answers=["defer", "waiting on staging"])
    assert code == 0 and doc["result"]["moved_to"] == "blocked/r1.md"


def test_review_approve_without_branch_archives(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json"],
                    interactive=True, answers=["approve"])
    assert code == 0 and doc["result"]["moved_to"] == "completed/r1.md"
    assert "merge" not in doc["result"]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo_project(git_repo: Path) -> Path:
    """git repo on main with dev, a feature/r1 branch one commit ahead, .plans ignored."""
    (git_repo / ".gitignore").write_text(".plans/\n", encoding="utf-8")
    _git(git_repo, "add", ".gitignore")
    _git(git_repo, "commit", "-m", "ignore plans")
    _git(git_repo, "branch", "dev")
    _git(git_repo, "checkout", "-b", "feature/r1", "dev")
    (git_repo / "thing.txt").write_text("x\n", encoding="utf-8")
    _git(git_repo, "add", "thing.txt")
    _git(git_repo, "commit", "-m", "r1 work")
    _git(git_repo, "checkout", "dev")
    write(git_repo, "review-needed", "r1")
    return git_repo


def test_review_approve_fast_forwards_through_the_gate(repo_project):
    head = _git(repo_project, "rev-parse", "feature/r1")
    code, doc = cli(["review", "r1", "--root", str(repo_project), "--json"],
                    interactive=True, answers=["approve"])
    assert code == 0, doc
    assert doc["result"]["target"] == "dev" and doc["result"]["fast_forward"] is True
    assert doc["result"]["merge"]["ok"] and doc["result"]["merge"]["outcome"] == head
    assert _git(repo_project, "rev-parse", "dev") == head
    assert _git(repo_project, "rev-parse", "main") != head
    assert doc["result"]["moved_to"] == "completed/r1.md"


def test_review_approve_never_makes_a_merge_commit(repo_project):
    (repo_project / "other.txt").write_text("y\n", encoding="utf-8")
    _git(repo_project, "add", "other.txt")
    _git(repo_project, "commit", "-m", "dev moved on")
    dev_before = _git(repo_project, "rev-parse", "dev")
    code, doc = cli(["review", "r1", "--root", str(repo_project), "--json"],
                    interactive=True, answers=["approve"])
    assert code == 3
    assert doc["pending"][-1]["step"] == "merge-commit"
    assert doc["pending"][-1]["needs"] == "harness"
    assert _git(repo_project, "rev-parse", "dev") == dev_before
    assert (repo_project / ".plans" / "review-needed" / "r1.md").is_file()


def test_review_headless_never_merges(repo_project):
    dev_before = _git(repo_project, "rev-parse", "dev")
    code, _doc = cli(["review", "r1", "--root", str(repo_project)])
    assert code == 3
    assert _git(repo_project, "rev-parse", "dev") == dev_before


# --- draft ------------------------------------------------------------------------


def test_draft_scaffolds_and_hands_prose_back(project):
    code, doc = cli(["draft", "new-thing", "--root", str(project), "--goal", "Ship it."])
    assert code == 0 and doc["result"]["plan"] == "drafts/new-thing.md"
    text = (project / ".plans" / "drafts" / "new-thing.md").read_text(encoding="utf-8")
    assert "## Goal\nShip it." in text
    assert doc["pending"][0]["step"] == "plan-prose"


def test_draft_local_and_duplicate(project):
    code, doc = cli(["draft", "mine", "--local", "--root", str(project)])
    assert doc["result"]["plan"] == "drafts/mine.local.md"
    write(project, "features", "taken")
    code, doc = cli(["draft", "taken", "--root", str(project)])
    assert code == 2 and "already used" in doc["error"]


def test_draft_promote(project):
    write(project, "drafts", "d1")
    code, doc = cli(["draft", "--promote", "d1", "--root", str(project)])
    assert code == 3 and doc["pending"][0]["step"] == "promote-lane"
    code, doc = cli(["draft", "--promote", "d1", "--to", "features", "--root", str(project)])
    assert code == 0 and doc["result"]["plan"] == "features/d1.md"


# --- delegation -------------------------------------------------------------------


class _StubEndpoint:
    name = "stub"
    last_kw: dict | None = None
    last_system: str | None = None

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def chat(self, messages, **kw) -> str:
        self.calls += 1
        self.last_kw = kw
        _StubEndpoint.last_kw = kw
        sys_txt = next((m["content"] for m in messages if m["role"] == "system"), "")
        _StubEndpoint.last_system = sys_txt
        return self.reply


@pytest.fixture
def stub_fleet(monkeypatch, tmp_path):
    anchor_client = pytest.importorskip("anchor_client")
    reply = PLAN.format(slug="delegated", priority="P2")
    ep = _StubEndpoint(reply)

    class StubFleet:
        def __init__(self, _path, **_kw):
            self.endpoints = [ep]

        def pick(self, _role):
            return ep

        def lookup(self, _name):
            return ep

    reg = tmp_path / "endpoints.yaml"
    reg.write_text("endpoints: []\n", encoding="utf-8")
    monkeypatch.setattr(anchor_client, "Fleet", StubFleet)
    return ep, reg


def test_delegation_round_trips_one_step_interactively(project, stub_fleet):
    ep, reg = stub_fleet
    code, doc = cli(["draft", "d2", "--root", str(project), "--delegate", "--registry", str(reg),
                     "--json"], interactive=True)
    assert code == 0 and ep.calls == 1
    assert doc["result"]["delegated_to"] == "stub" and doc["pending"] == []
    text = (project / ".plans" / "drafts" / "d2.md").read_text(encoding="utf-8")
    assert text.startswith("# Plan: delegated")


def test_headless_never_delegates(project, stub_fleet):
    ep, reg = stub_fleet
    code, doc = cli(["draft", "d3", "--root", str(project), "--delegate", "--registry", str(reg)])
    assert code == 0 and ep.calls == 0
    assert any("non-interactive" in n for n in doc["notes"])
    assert doc["pending"][0]["step"] == "plan-prose"


def test_delegation_without_an_endpoint_names_the_step(project, tmp_path):
    pytest.importorskip("anchor_client")
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json", "--delegate",
                     "--registry", str(tmp_path / "missing.yaml")],
                    interactive=True, answers=["skip"])
    assert code == 0
    assert any("no endpoint registry" in n for n in doc["notes"])


# --- no verb blocks with stdin closed (subprocess, real stdio) --------------------

HEADLESS_ARGVS = [
    ["plans"],
    ["plans", "--board"],
    ["work", "--list"],
    ["work"],
    ["work", "--run"],
    ["review"],
    ["review", "r1"],
    ["review", "r1", "--delegate"],
    ["draft"],
    ["draft", "fresh"],
    ["draft", "--promote", "d1"],
    ["work", "--heartbeat", "f1"],
    ["work", "--finish", "f1"],
    ["work", "--return", "f1"],
]
OWNED_VERBS = ("--heartbeat", "--finish", "--return")


@pytest.mark.parametrize("close", [False, True], ids=["devnull", "closed"])
@pytest.mark.parametrize("argv", HEADLESS_ARGVS, ids=lambda a: " ".join(a))
def test_no_verb_blocks_with_stdin_closed(project, argv, close):
    write(project, "features", "f1")
    write(project, "review-needed", "r1")
    write(project, "drafts", "d1")
    if any(flag in argv for flag in OWNED_VERBS):
        plan_lease.claim_and_move(project / ".plans", "features/f1.md", "sub")
    cmd = [sys.executable, str(SCRIPTS / "anchor.py"), *argv, "--root", str(project),
           "--agent-id", "sub"] if argv[0] == "work" else [
        sys.executable, str(SCRIPTS / "anchor.py"), *argv, "--root", str(project)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if close:
        proc.stdin.close()
        proc.stdin = None  # the child sees EOF on a closed pipe; communicate must not flush it
        out, _err = proc.communicate(timeout=30)
    else:
        out, _err = proc.communicate(input="", timeout=30)
    assert proc.returncode in (0, 1, 3), _err
    doc = json.loads(out)
    if "--board" not in argv:
        assert doc["mode"] == "non-interactive" and doc["exit_code"] == proc.returncode


# --- a pip-installed `anchor` can import everything it uses -------------------------


def _script_imports(name: str) -> set[str]:
    import ast

    tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return {m for m in found if (SCRIPTS / f"{m}.py").is_file()}


def test_pyproject_ships_the_whole_import_closure():
    import re

    text = (SCRIPTS.parent / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"py-modules\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert block, "py-modules list not found"
    shipped = set(re.findall(r'"([^"]+)"', block.group(1)))

    closure: set[str] = set()
    todo = ["anchor", "anchor_cli"]
    while todo:
        mod = todo.pop()
        if mod not in closure:
            closure.add(mod)
            todo.extend(_script_imports(mod) - closure)
    assert closure <= shipped, f"imported but not packaged: {sorted(closure - shipped)}"


# --- documented commands match --help exactly ------------------------------------


@pytest.mark.parametrize("verb", anchor_cli.VERBS)
def test_docs_quote_help_verbatim(verb):
    page = (SCRIPTS.parent / "docs" / "docs" / "tooling" / "plan-verbs.md").read_text(encoding="utf-8")
    help_text = subprocess.run(
        [sys.executable, str(SCRIPTS / "anchor.py"), verb, "--help"],
        capture_output=True, text=True, check=True,
        env={"COLUMNS": "80", "PATH": "/usr/bin:/bin"},
    ).stdout.rstrip("\n")
    assert f"```text\n{help_text}\n```" in page, (
        f"docs/docs/tooling/plan-verbs.md is stale for `anchor {verb} --help`; "
        "regenerate its Command reference section"
    )


# --- review fixes: race, remote-only branch, critic confirmation ----------------


def test_review_approve_race_never_leaves_a_staged_merge(repo_project):
    """dev advances while the operator is at the prompt (the critic's H1 repro)."""

    def answer_after_dev_moves(_prompt: str) -> str:
        _git(repo_project, "checkout", "-q", "dev")
        (repo_project / "race.txt").write_text("r\n", encoding="utf-8")
        _git(repo_project, "add", "race.txt")
        _git(repo_project, "commit", "-q", "-m", "dev moved during the prompt")
        return "approve"

    out, stdin = TTY(), TTY()
    code = anchor_cli.main(["review", "r1", "--root", str(repo_project), "--json"],
                           stdin=stdin, stdout=out, env={}, read=answer_after_dev_moves)
    doc = json.loads(out.getvalue())
    assert code == anchor_cli.EXIT_NEEDS_OPERATOR, doc
    assert doc["pending"][-1]["step"] == "merge-commit"
    assert _git(repo_project, "status", "--porcelain") == ""
    probe = subprocess.run(["git", "-C", str(repo_project), "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                           capture_output=True, text=True)
    assert probe.returncode != 0, "a merge was left staged"
    assert (repo_project / ".plans" / "review-needed" / "r1.md").is_file()


def test_review_approve_with_remote_only_branch_does_not_archive(repo_project, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo_project, "remote", "add", "origin", str(remote))
    _git(repo_project, "push", "-q", "origin", "feature/r1")
    _git(repo_project, "fetch", "-q", "origin")
    _git(repo_project, "branch", "-D", "feature/r1")
    code, doc = cli(["review", "r1", "--root", str(repo_project), "--json"],
                    interactive=True, answers=["approve"])
    assert code == 3
    assert doc["result"]["remote_only"] == ["origin/feature/r1"]
    assert doc["pending"][-1]["step"] == "local-branch"
    assert (repo_project / ".plans" / "review-needed" / "r1.md").is_file()


@pytest.mark.parametrize(
    "text,verdict",
    [
        ("## Verdict\n**Verdict: ACCEPT**", "ACCEPT"),
        ("Checklist ok.\n\nVerdict: REVISE — fix H1", "REVISE"),
        ("**Verdict:** escalate", "ESCALATE"),
        ("looks fine but I would REVISE the docs; ACCEPT otherwise", "REVISE"),
        ("no verdict here", "UNKNOWN"),
        # M-A: template options / strikethrough / prior ACCEPT must not fail open
        ("## Verdict\nACCEPT | REVISE (with …) | ESCALATE\n\nREVISE: fix H1", "REVISE"),
        ("## Verdict\n~~ACCEPT~~ **REVISE**", "REVISE"),
        ("Prior round verdict: ACCEPT was premature.\n**Verdict: REVISE**", "REVISE"),
        ("## Verdict\nACCEPT | REVISE | ESCALATE\n\nESCALATE — needs a bigger model", "ESCALATE"),
        # M-A: a prior-round ACCEPT must not fill an empty ## Verdict section
        ("Prior round verdict: ACCEPT was premature.\n## Verdict\n", "UNKNOWN"),
        ("Prior round verdict: ACCEPT was premature.\n## Verdict\nLooks fine.\n\n"
         "## Notes for next task\nACCEPT this later", "UNKNOWN"),
    ],
)
def test_critic_verdict(text, verdict):
    assert anchor_cli.critic_verdict(text) == verdict


@pytest.fixture
def critic_fleet(monkeypatch, tmp_path):
    anchor_client = pytest.importorskip("anchor_client")
    ep = _StubEndpoint("Findings: H1 is real.\n\n**Verdict: REVISE**")

    class StubFleet:
        def __init__(self, _path, **_kw):
            self.endpoints = [ep]

        def pick(self, _role):
            return ep

        def lookup(self, _name):
            return ep

    reg = tmp_path / "endpoints.yaml"
    reg.write_text("endpoints: []\n", encoding="utf-8")
    monkeypatch.setattr(anchor_client, "Fleet", StubFleet)
    return reg


def test_approve_after_revise_critic_needs_explicit_yes(project, critic_fleet):
    write(project, "review-needed", "r1")
    argv = ["review", "r1", "--root", str(project), "--json", "--delegate",
            "--registry", str(critic_fleet)]
    code, doc = cli(argv, interactive=True, answers=["approve", "no"])
    assert code == 0 and doc["result"]["critic"]["verdict"] == "REVISE"
    assert doc["result"]["decision"] == "skip"
    assert (project / ".plans" / "review-needed" / "r1.md").is_file()

    code, doc = cli(argv, interactive=True, answers=["approve", "yes"])
    assert code == 0 and doc["result"]["moved_to"] == "completed/r1.md"


def test_delegation_reports_a_bad_registry_instead_of_crashing(project, tmp_path):
    pytest.importorskip("anchor_client")
    write(project, "drafts", "d0")
    bad = tmp_path / "endpoints.yaml"
    bad.write_text("endpoints: [ {name: x, tier: mid}\n", encoding="utf-8")  # invalid YAML
    code, doc = cli(["draft", "d9", "--root", str(project), "--json", "--delegate",
                     "--registry", str(bad)], interactive=True)
    assert code == 0
    assert any("cannot load" in n for n in doc["notes"])


def test_delegation_reports_missing_doctrine(project, stub_fleet, monkeypatch):
    import anchor_client

    ep, reg = stub_fleet

    def missing(_rel):
        raise FileNotFoundError("anchor/system-prompts/mythos-core.md")

    monkeypatch.setattr(anchor_client, "load_prompt", missing)
    code, doc = cli(["draft", "d8", "--root", str(project), "--json", "--delegate",
                     "--registry", str(reg)], interactive=True)
    assert code == 0 and ep.calls == 0
    assert any("doctrine" in n for n in doc["notes"])


def test_review_interactive_critic_without_delegate_flag(project, critic_fleet):
    write(project, "review-needed", "r1")
    code, doc = cli(
        ["review", "r1", "--root", str(project), "--json",
         "--registry", str(critic_fleet)],
        interactive=True, answers=["skip"],
    )
    assert code == 0
    assert doc["result"]["critic"]["verdict"] == "REVISE"


def test_review_no_delegate_skips_critic_chat(project, critic_fleet):
    write(project, "review-needed", "r1")
    code, doc = cli(
        ["review", "r1", "--root", str(project), "--json", "--no-delegate",
         "--registry", str(critic_fleet)],
        interactive=True, answers=["skip"],
    )
    assert code == 0
    assert "critic" not in (doc.get("result") or {})


def test_review_delegate_critic_thinks_off(project, critic_fleet):
    write(project, "review-needed", "r1")
    _StubEndpoint.last_kw = None
    code, doc = cli(
        ["review", "r1", "--root", str(project), "--json", "--delegate",
         "--registry", str(critic_fleet)],
        interactive=True, answers=["skip"],
    )
    assert code == 0
    assert _StubEndpoint.last_kw is not None
    assert _StubEndpoint.last_kw.get("thinking") is False
    assert _StubEndpoint.last_kw.get("max_tokens") == 8192
    assert "code critic" in (_StubEndpoint.last_system or "").lower()
    assert "mythos" not in (_StubEndpoint.last_system or "").lower()
    assert doc["result"]["critic"]["verdict"] == "REVISE"


def test_diff_chunks_split_on_file_boundaries():
    from anchor_ops import diff_chunks

    a = "diff --git a/a.py b/a.py\n" + ("A" * 100) + "\n"
    b = "diff --git a/b.py b/b.py\n" + ("B" * 100) + "\n"
    chunks = diff_chunks(a + b, limit=150)
    assert len(chunks) == 2
    assert chunks[0].startswith("diff --git a/a.py")
    assert chunks[1].startswith("diff --git a/b.py")
    assert diff_chunks("short") == ["short"]


def test_delegate_critic_banner_on_stderr_before_first_prompt(project, critic_fleet, capsys):
    """H1: interactive non-JSON --delegate shows the critic before Approve."""
    write(project, "review-needed", "r1")
    seen: list[str] = []

    def read(_prompt: str) -> str:
        seen.append(capsys.readouterr().err)
        return "skip"

    code = anchor_cli.main(
        ["review", "r1", "--root", str(project), "--delegate",
         "--registry", str(critic_fleet)],
        stdin=TTY(), stdout=TTY(), env={}, read=read,
    )
    assert code == 0
    assert seen, "decision prompt never ran"
    assert "--- critic" in seen[0]
    assert "REVISE" in seen[0]


def test_scaffold_collision_hint_on_platform_flag():
    assert "anchor ./work" in (anchor_cli.scaffold_collision_hint(
        ["work", "--platform", "claude"]) or "")
    with pytest.raises(SystemExit) as ei:
        anchor_cli.main(["work", "--platform", "claude"])
    assert ei.value.code == 2


def test_scaffold_collision_hint_when_verb_named_dir_exists(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    named = tmp_path / "named"
    named.mkdir()
    (named / "review").mkdir()
    assert "anchor ./review" in (anchor_cli.scaffold_collision_hint(
        ["review", "--bogus"], cwd=named) or "")
    assert anchor_cli.scaffold_collision_hint(["review", "--bogus"], cwd=empty) is None
