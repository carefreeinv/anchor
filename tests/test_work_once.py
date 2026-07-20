import subprocess
import sys
from pathlib import Path

import work_once
from plan_select import Worker


def _plan(path: Path, *, preferred: str = "mid", value: str = "medium") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Plan: t\n\n- **Value:** {value}\n- **Preferred models:** {preferred}\n\n"
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
    code = work_once.main(["--root", str(root), "--once", "--tier", "mid", "--agent-id", "t"])
    assert code == 1


def test_once_no_fit_exits_1(tmp_path):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "hard.md", preferred="frontier")
    code = work_once.main(
        ["--root", str(root), "--once", "--tier", "small", "--agent-id", "tiny"]
    )
    assert code == 1


def test_once_moves_to_in_progress_and_blocks_others(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    code = work_once.main(
        ["--root", str(root), "--once", "--tier", "mid", "--agent-id", "w1"]
    )
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("in-progress/a.md")
    assert (root / ".plans" / "in-progress" / "a.md").is_file()
    assert not (root / ".plans" / "features" / "a.md").exists()
    # second worker cannot claim the moved plan
    code2 = work_once.main(
        ["--root", str(root), "--once", "--tier", "mid", "--agent-id", "w2"]
    )
    assert code2 == 1


def test_bare_pick_never_resumes_takes_next_ready(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "a.md", preferred="mid")
    _plan(root / ".plans" / "features" / "b.md", preferred="mid")
    work_once.main(
        ["--root", str(root), "--once", "--tier", "mid", "--agent-id", "w1"]
    )
    capsys.readouterr()  # clear first claim (a.md → in-progress)
    # A second bare pick for the same agent does NOT resume in-progress/a.md;
    # it claims the next ready plan (b.md). Resume is an explicit --path claim.
    code = work_once.main(
        ["--root", str(root), "--once", "--tier", "mid", "--agent-id", "w1"]
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
        ["--root", str(root), "--once", "--tier", "mid", "--agent-id", "w1"]
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
        ["--root", str(root), "--once", "--tier", "mid", "--agent-id", "w1"]
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


def test_no_fit_check_picks_mismatch(tmp_path, capsys):
    root = _root(tmp_path)
    _plan(root / ".plans" / "features" / "hard.md", preferred="frontier")
    code = work_once.main(
        [
            "--root",
            str(root),
            "--once",
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
