"""Golden --json / exit-code snapshots for every `anchor` verb/action.

Written against the *unrefactored* CLI (Step 1 of cli-operations-core). After
the move into `anchor_ops`, these files must stay byte-identical modulo the
normalizer (timestamps, SHAs, absolute paths).

Regenerate with: ANCHOR_UPDATE_GOLDENS=1 python3 -m pytest tests/test_anchor_cli_golden.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import anchor_cli
import pytest
from test_anchor_cli import cli, write

GOLDEN = Path(__file__).resolve().parent / "golden" / "anchor_cli"
SHA = re.compile(r"\b[0-9a-f]{40}\b")
UPDATE = os.environ.get("ANCHOR_UPDATE_GOLDENS") == "1"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for lane in ("bugs", "features", "in-progress", "review-needed", "drafts",
                 "completed", "ambiguous", "blocked"):
        (root / ".plans" / lane).mkdir(parents=True)
    return root


@pytest.fixture
def repo_project(git_repo: Path) -> Path:
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


def normalize(doc: dict, root: Path) -> dict:
    """Drop run-local noise so goldens compare across tmp dirs and clocks."""
    blob = json.dumps(doc, indent=2, sort_keys=True, default=str)
    blob = blob.replace(str(root), "<ROOT>")
    blob = SHA.sub("<SHA>", blob)
    data = json.loads(blob)

    def walk(node):
        if isinstance(node, dict):
            if "expires_at" in node and isinstance(node["expires_at"], (int, float)):
                node["expires_at"] = "<TS>"
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return data


def assert_golden(name: str, code: int, doc: dict, root: Path) -> None:
    payload = {"exit_code": code, "doc": normalize(doc, root)}
    GOLDEN.mkdir(parents=True, exist_ok=True)
    path = GOLDEN / f"{name}.json"
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if UPDATE or not path.is_file():
        path.write_text(text, encoding="utf-8")
        if not UPDATE:
            pytest.fail(f"wrote missing golden {path.name}; re-run to confirm")
        return
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert payload == expected, f"golden drift in {path.name}"


# --- plans ------------------------------------------------------------------------


def test_golden_plans_list(project):
    write(project, "bugs", "b1")
    write(project, "drafts", "d1")
    code, doc = cli(["plans", "--root", str(project)])
    assert_golden("plans_list", code, doc, project)


def test_golden_plans_missing_tree(tmp_path):
    code, doc = cli(["plans", "--root", str(tmp_path)])
    assert_golden("plans_missing_tree", code, doc, tmp_path)


def test_golden_plans_lane_filter(project):
    write(project, "bugs", "b1")
    write(project, "drafts", "d1")
    code, doc = cli(["plans", "--lane", "bugs", "--root", str(project)])
    assert_golden("plans_lane_filter", code, doc, project)


def test_golden_plans_board_passthrough(project):
    """`--board --json` is the schema-v1 envelope with plan_board under result.board."""
    write(project, "bugs", "b1")
    code, doc = cli(["plans", "--board", "--root", str(project), "--json"])
    board = (doc.get("result") or {}).get("board") or {}
    payload = {
        "exit_code": code,
        "verb": doc.get("verb"),
        "action": doc.get("action"),
        "keys": sorted(doc.keys()),
        "schema_version": doc.get("schema_version"),
        "include_parked": board.get("include_parked"),
        "column_names": [c["name"] for c in board.get("columns", [])],
        "ready_slugs": [
            p["slug"] for col in board.get("columns", []) if col["name"] == "Ready"
            for p in col["plans"]
        ],
    }
    GOLDEN.mkdir(parents=True, exist_ok=True)
    path = GOLDEN / "plans_board_passthrough.json"
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if UPDATE or not path.is_file():
        path.write_text(text, encoding="utf-8")
        if not UPDATE:
            pytest.fail(f"wrote missing golden {path.name}; re-run to confirm")
        return
    assert payload == json.loads(path.read_text(encoding="utf-8"))


# --- work -------------------------------------------------------------------------


def test_golden_work_list(project):
    write(project, "features", "f1")
    code, doc = cli(["work", "--list", "--root", str(project), "--tier", "mid"])
    assert_golden("work_list", code, doc, project)


def test_golden_work_list_empty(project):
    code, doc = cli(["work", "--list", "--root", str(project)])
    assert_golden("work_list_empty", code, doc, project)


def test_golden_work_claim(project):
    write(project, "features", "f1", priority="P3")
    write(project, "bugs", "b1")
    code, doc = cli(["work", "--no-run", "--root", str(project), "--agent-id", "a1"])
    assert_golden("work_claim", code, doc, project)


def test_golden_work_claim_named(project):
    write(project, "features", "f1")
    code, doc = cli(["work", "f1", "--no-run", "--root", str(project), "--agent-id", "a1", "--no-fit-check"])
    assert_golden("work_claim_named", code, doc, project)


def test_golden_work_claim_empty(project):
    code, doc = cli(["work", "--root", str(project), "--agent-id", "a1"])
    assert_golden("work_claim_empty", code, doc, project)


def test_golden_work_run_headless(project, monkeypatch):
    import work_once

    monkeypatch.setattr(work_once, "run_orchestrate", lambda *a, **k: 0)
    monkeypatch.setattr(work_once, "orchestrate_worktree_args", lambda *a, **k: [])
    write(project, "features", "f1")
    code, doc = cli(["work", "--root", str(project), "--agent-id", "a1", "--run"])
    assert_golden("work_run_headless", code, doc, project)


def test_golden_work_heartbeat_finish_return(project):
    write(project, "features", "f1")
    write(project, "features", "f2")
    cli(["work", "f1", "--no-run", "--root", str(project), "--agent-id", "a1"])
    cli(["work", "f2", "--no-run", "--root", str(project), "--agent-id", "a1"])

    code, doc = cli(["work", "--heartbeat", "f1", "--root", str(project), "--agent-id", "a1"])
    assert_golden("work_heartbeat", code, doc, project)

    code, doc = cli(["work", "--heartbeat", "f1", "--root", str(project), "--agent-id", "other"])
    assert_golden("work_heartbeat_not_holder", code, doc, project)

    code, doc = cli(["work", "--finish", "f1", "--root", str(project), "--agent-id", "someone-else"])
    assert_golden("work_finish_not_holder", code, doc, project)

    code, doc = cli(["work", "--finish", "f1", "--root", str(project), "--agent-id", "a1"])
    assert_golden("work_finish", code, doc, project)

    code, doc = cli(["work", "--return", "f2", "--root", str(project), "--agent-id", "a1"])
    assert_golden("work_return", code, doc, project)


# --- review -----------------------------------------------------------------------


def test_golden_review_list(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "--list", "--root", str(project)])
    assert_golden("review_list", code, doc, project)


def test_golden_review_list_empty(project):
    code, doc = cli(["review", "--root", str(project)])
    assert_golden("review_list_empty", code, doc, project)


def test_golden_review_headless_needs_operator(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--no-delegate", "--root", str(project)])
    assert_golden("review_headless_needs_operator", code, doc, project)


def test_golden_review_skip(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json", "--no-delegate"],
                    interactive=True, answers=["skip"])
    assert_golden("review_skip", code, doc, project)


def test_golden_review_needs_work_empty_notes(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json", "--no-delegate"],
                    interactive=True, answers=["needs-work", "bugs", ""])
    assert_golden("review_needs_work_empty_notes", code, doc, project)


def test_golden_review_needs_work(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json", "--no-delegate"],
                    interactive=True, answers=["needs-work", "bugs", "Done when #1 fails"])
    assert_golden("review_needs_work", code, doc, project)


def test_golden_review_defer(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json", "--no-delegate"],
                    interactive=True, answers=["defer", "waiting on staging"])
    assert_golden("review_defer", code, doc, project)


def test_golden_review_approve_without_branch(project):
    write(project, "review-needed", "r1")
    code, doc = cli(["review", "r1", "--root", str(project), "--json", "--no-delegate"],
                    interactive=True, answers=["approve"])
    assert_golden("review_approve_without_branch", code, doc, project)


def test_golden_review_approve_fast_forward(repo_project):
    code, doc = cli(["review", "r1", "--root", str(repo_project), "--json", "--no-delegate"],
                    interactive=True, answers=["approve"])
    assert_golden("review_approve_fast_forward", code, doc, repo_project)


def test_golden_review_approve_not_fast_forward(repo_project):
    (repo_project / "other.txt").write_text("y\n", encoding="utf-8")
    _git(repo_project, "add", "other.txt")
    _git(repo_project, "commit", "-m", "dev moved on")
    code, doc = cli(["review", "r1", "--root", str(repo_project), "--json", "--no-delegate"],
                    interactive=True, answers=["approve"])
    assert_golden("review_approve_not_fast_forward", code, doc, repo_project)


def test_golden_review_headless_never_merges(repo_project):
    code, doc = cli(["review", "r1", "--no-delegate", "--root", str(repo_project)])
    assert_golden("review_headless_never_merges", code, doc, repo_project)


# --- draft ------------------------------------------------------------------------


def test_golden_draft_list_empty(project):
    code, doc = cli(["draft", "--root", str(project)])
    assert_golden("draft_list_empty", code, doc, project)


def test_golden_draft_list(project):
    write(project, "drafts", "d1")
    code, doc = cli(["draft", "--list", "--root", str(project)])
    assert_golden("draft_list", code, doc, project)


def test_golden_draft_create(project):
    code, doc = cli(["draft", "new-thing", "--no-delegate", "--shared", "--root", str(project), "--goal", "Ship it."])
    assert_golden("draft_create", code, doc, project)


def test_golden_draft_local(project):
    code, doc = cli(["draft", "mine", "--no-delegate", "--root", str(project)])
    assert_golden("draft_local", code, doc, project)


def test_golden_draft_duplicate(project):
    write(project, "features", "taken")
    code, doc = cli(["draft", "taken", "--no-delegate", "--root", str(project)])
    assert_golden("draft_duplicate", code, doc, project)


def test_golden_draft_promote_needs_lane(project):
    write(project, "drafts", "d1")
    code, doc = cli(["draft", "--promote", "d1", "--root", str(project)])
    assert_golden("draft_promote_needs_lane", code, doc, project)


def test_golden_draft_promote(project):
    write(project, "drafts", "d1")
    code, doc = cli(["draft", "--promote", "d1", "--to", "features", "--root", str(project)])
    assert_golden("draft_promote", code, doc, project)


@pytest.mark.skipif(UPDATE, reason="goldens being regenerated")
def test_golden_covers_every_cli_action():
    """Every Result.action the unrefactored CLI emits has at least one golden."""
    names = {p.stem for p in GOLDEN.glob("*.json")}
    required = {
        "plans_list", "plans_missing_tree", "plans_lane_filter", "plans_board_passthrough",
        "work_list", "work_list_empty", "work_claim", "work_claim_named", "work_claim_empty",
        "work_run_headless", "work_heartbeat", "work_finish", "work_finish_not_holder",
        "work_return",
        "review_list", "review_list_empty", "review_headless_needs_operator", "review_skip",
        "review_needs_work_empty_notes", "review_needs_work", "review_defer",
        "review_approve_without_branch", "review_approve_fast_forward",
        "review_approve_not_fast_forward", "review_headless_never_merges",
        "draft_list_empty", "draft_list", "draft_create", "draft_local", "draft_duplicate",
        "draft_promote_needs_lane", "draft_promote",
    }
    assert required <= names, f"missing goldens: {sorted(required - names)}"
    actions = set()
    for path in GOLDEN.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        doc = payload.get("doc") or {}
        if isinstance(doc, dict) and "action" in doc:
            actions.add(doc["action"])
    assert actions >= {
        "list", "claim", "heartbeat", "finish", "return", "review", "create", "promote",
    }
    assert "plans_missing_tree" in names  # exit 2
    # NeedsOperator cases
    for name in ("review_headless_needs_operator", "review_needs_work_empty_notes",
                 "draft_promote_needs_lane", "review_approve_not_fast_forward"):
        payload = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
        assert payload["exit_code"] == anchor_cli.EXIT_NEEDS_OPERATOR, name
