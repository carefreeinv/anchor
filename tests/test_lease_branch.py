import json
import subprocess
import threading
import time
from pathlib import Path

import lease_branch as lb
import pytest


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _clone(tmp_path: Path, bare: Path, name: str) -> Path:
    dest = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(bare), str(dest)], check=True, capture_output=True)
    _run(dest, "config", "user.email", "t@example.com")
    _run(dest, "config", "user.name", "t")
    return dest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "ANCHOR_LEASE_REMOTE", "ANCHOR_LEASE_STRICT", "ANCHOR_LEASE_PUBLISH_LOCAL",
        "ANCHOR_LEASE_SKEW_SECONDS", "ANCHOR_LEASE_HEARTBEAT_SECONDS",
        "ANCHOR_LEASE_HOST", "ANCHOR_LEASE_BRANCH", "ANCHOR_LEASE_NET_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def clones(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    seed = _clone(tmp_path, bare, "seed")
    (seed / ".gitignore").write_text(".plans/.leases/\n")
    (seed / "README.md").write_text("x\n")
    _run(seed, "add", "-A")
    _run(seed, "commit", "-qm", "seed")
    _run(seed, "push", "-q", "origin", "HEAD")
    return _clone(tmp_path, bare, "a"), _clone(tmp_path, bare, "b"), bare


def test_bootstrap_idempotent_and_orphan(clones):
    a, b, bare = clones
    tip = lb.bootstrap(a)
    assert lb.bootstrap(a) == tip
    assert lb.bootstrap(b) == tip
    assert _run(bare, "rev-parse", "refs/heads/leases") == tip
    # orphan: shares no history with the code branch
    head = _run(a, "rev-parse", "HEAD")
    assert subprocess.run(
        ["git", "-C", str(bare), "merge-base", tip, head], capture_output=True
    ).returncode != 0


def test_claim_visible_from_second_clone_and_refused(clones):
    a, b, _ = clones
    lb.claim(a, "alpha", "agent-a")
    seen = lb.list_leases(b)
    assert [lz.slug for lz in seen] == ["alpha"]
    assert seen[0].agent_id == "agent-a"
    assert lb.holder_of(b, "alpha").agent_id == "agent-a"
    with pytest.raises(lb.LeaseConflict):
        lb.claim(b, "alpha", "agent-b")


def test_same_agent_reclaim_keeps_claimed_at(clones):
    a, _, _ = clones
    first = lb.claim(a, "alpha", "agent-a")
    again = lb.claim(a, "alpha", "agent-a")
    assert again.claimed_at == first.claimed_at


def test_simultaneous_claim_exactly_one_winner(clones):
    a, b, _ = clones
    lb.bootstrap(a)
    results: dict[str, object] = {}
    barrier = threading.Barrier(2)

    def go(clone, agent):
        barrier.wait()
        try:
            results[agent] = lb.claim(clone, "race", agent)
        except lb.LeaseConflict as exc:
            results[agent] = exc

    ts = [threading.Thread(target=go, args=(a, "agent-a")),
          threading.Thread(target=go, args=(b, "agent-b"))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert set(results) == {"agent-a", "agent-b"}  # neither thread crashed
    winners = [k for k, v in results.items() if isinstance(v, lb.BranchLease)]
    losers = [v for v in results.values() if not isinstance(v, lb.BranchLease)]
    assert len(winners) == 1
    assert len(losers) == 1 and isinstance(losers[0], lb.LeaseConflict)
    assert lb.holder_of(a, "race").agent_id == winners[0]


def test_expired_lease_needs_explicit_recover(clones, monkeypatch):
    a, b, _ = clones
    monkeypatch.setenv("ANCHOR_LEASE_SKEW_SECONDS", "0")
    lb.claim(a, "old", "agent-a", ttl_seconds=1)
    time.sleep(1.2)
    assert lb.holder_of(b, "old") is None
    with pytest.raises(lb.LeaseConflict, match="recover"):
        lb.claim(b, "old", "agent-b")
    got = lb.claim(b, "old", "agent-b", recover=True)
    assert got.agent_id == "agent-b"


def test_skew_slack_keeps_just_expired_lease_live(clones):
    a, b, _ = clones
    lb.claim(a, "slack", "agent-a", ttl_seconds=1)
    time.sleep(1.2)  # past expires_at but inside the 5 min default slack
    assert lb.holder_of(b, "slack") is not None


def test_release_deletes_file_and_foreign_release_refused(clones):
    a, b, _ = clones
    lb.claim(a, "alpha", "agent-a")
    with pytest.raises(lb.LeaseConflict):
        lb.release(b, "alpha", "agent-b")
    assert lb.release(a, "alpha", "agent-a") is True
    assert lb.list_leases(b) == []
    assert lb.release(a, "alpha", "agent-a") is False


def test_renew_throttled_then_forced(clones, monkeypatch):
    a, _, bare = clones
    lb.claim(a, "alpha", "agent-a")
    before = _run(bare, "rev-parse", "refs/heads/leases")
    lb.renew(a, "alpha", "agent-a")  # inside the 2h interval: no push
    assert _run(bare, "rev-parse", "refs/heads/leases") == before
    lb.renew(a, "alpha", "agent-a", force=True)
    assert _run(bare, "rev-parse", "refs/heads/leases") != before
    monkeypatch.setenv("ANCHOR_LEASE_HEARTBEAT_SECONDS", "0")
    mid = _run(bare, "rev-parse", "refs/heads/leases")
    lb.renew(a, "alpha", "agent-a")
    assert _run(bare, "rev-parse", "refs/heads/leases") != mid


def test_renew_foreign_refused(clones):
    a, b, _ = clones
    lb.claim(a, "alpha", "agent-a")
    with pytest.raises(lb.LeaseConflict):
        lb.renew(b, "alpha", "agent-b", force=True)


def test_isolation_branch_only_lease_json_and_no_tracking(clones):
    a, b, bare = clones
    lb.claim(a, "alpha", "agent-a")
    lb.claim(b, "beta", "agent-b")
    names = _run(bare, "log", "--format=", "--name-only", "refs/heads/leases").split()
    assert names and all(n.startswith("leases/") and n.endswith(".json") for n in names)
    code_files = _run(a, "ls-files").split()
    assert not any("lease" in f for f in code_files)
    lb.check_isolation(a)
    # HEAD/index/worktree of the clone were never touched
    assert _run(a, "status", "--porcelain") == ""
    assert _run(a, "rev-parse", "--abbrev-ref", "HEAD") != "leases"


def test_assert_isolated_rejects_foreign_paths(clones):
    a, _, _ = clones
    lb.bootstrap(a)
    tree = lb._build_tree(a, None, {"README.md": b"x", "leases/ok.json": b"{}"})
    sha = lb._commit(a, tree, None, "bad")
    with pytest.raises(lb.IsolationError):
        lb.assert_isolated(a, sha)


def test_check_isolation_flags_unignored_leases_dir(clones):
    a, _, _ = clones
    (a / ".gitignore").write_text("")
    with pytest.raises(lb.IsolationError):
        lb.check_isolation(a)


def test_malformed_lease_file_is_tolerated(clones):
    a, b, _ = clones
    tip = lb.bootstrap(a)
    sha = lb._commit(a, lb._build_tree(a, tip, {"leases/junk.json": b"{not json"}), tip, "junk")
    assert lb._push(a, sha)
    lb.claim(b, "alpha", "agent-b")
    assert [lz.slug for lz in lb.list_leases(a)] == ["alpha"]


def test_no_remote_is_unavailable(tmp_path):
    repo = tmp_path / "solo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    with pytest.raises(lb.LeaseBranchUnavailable):
        lb.claim(repo, "alpha", "agent-a")


def test_not_a_repo_is_unavailable(tmp_path):
    with pytest.raises(lb.LeaseBranchUnavailable):
        lb.list_leases(tmp_path)


def test_unreachable_remote_is_unavailable(clones, tmp_path):
    a, _, _ = clones
    _run(a, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    with pytest.raises(lb.LeaseBranchUnavailable):
        lb.claim(a, "alpha", "agent-a")


def test_invalid_slug_rejected(clones):
    a, _, _ = clones
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(lb.LeaseBranchError):
            lb.claim(a, bad, "agent-a")


def test_privacy_helpers(monkeypatch):
    assert lb.slug_of("features/foo.local.md") == "foo.local"
    assert lb.slug_of("bugs/bar.md") == "bar"
    assert not lb.publishable("foo.local")
    assert lb.publishable("bar")
    monkeypatch.setenv("ANCHOR_LEASE_PUBLISH_LOCAL", "1")
    assert lb.publishable("foo.local")


def test_compact_reroots_to_single_commit(clones):
    a, b, bare = clones
    lb.claim(a, "alpha", "agent-a")
    lb.claim(b, "beta", "agent-b")
    lb.compact(a)
    assert _run(bare, "rev-list", "--count", "refs/heads/leases") == "1"
    assert {lz.slug for lz in lb.list_leases(b)} == {"alpha", "beta"}


def test_cli_status_from_second_clone(clones, capsys):
    a, b, _ = clones
    lb.claim(a, "alpha", "agent-a")
    assert lb.main(["--root", str(b), "--status"]) == 0
    assert "alpha · agent-a" in capsys.readouterr().out
    assert lb.main(["--root", str(b), "--status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["slug"] == "alpha" and data[0]["expired"] is False


# --- composite store (plan_lease wiring) -----------------------------------

import plan_lease  # noqa: E402


def _plan(clone: Path, rel: str) -> Path:
    path = clone / ".plans" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Plan: t\n\n## Goal\ng\n", encoding="utf-8")
    (clone / ".plans" / "in-progress").mkdir(exist_ok=True)
    return clone / ".plans"


def test_claim_and_move_refused_on_other_clone_before_plan_moves(clones):
    a, b, _ = clones
    pa = _plan(a, "features/p1.md")
    pb = _plan(b, "features/p1.md")
    plan_lease.claim_and_move(pa, "features/p1.md", "agent-a")
    with pytest.raises(plan_lease.ClaimError, match="agent-a"):
        plan_lease.claim_and_move(pb, "features/p1.md", "agent-b")
    assert (pb / "features" / "p1.md").is_file()  # never left the ready lane
    assert "features/p1.md" in plan_lease.claimed_rels(pb)
    assert plan_lease.owner_of(pb, "features/p1.md") == "agent-a"
    assert [lz.slug for lz in lb.list_leases(b)] == ["p1"]


def test_release_and_return_to_ready_free_the_shared_lease(clones):
    a, b, _ = clones
    pa = _plan(a, "bugs/p2.md")
    plan_lease.claim_and_move(pa, "bugs/p2.md", "agent-a")
    assert lb.holder_of(b, "p2") is not None
    plan_lease.return_to_ready(pa, "in-progress/p2.md", agent_id="agent-a")
    assert lb.holder_of(b, "p2") is None


def test_renew_mirrors_to_branch(clones):
    a, _, bare = clones
    pa = _plan(a, "bugs/p3.md")
    plan_lease.claim_and_move(pa, "bugs/p3.md", "agent-a")
    lb.renew(a, "p3", "agent-a", force=True)
    plan_lease.renew(pa, "in-progress/p3.md", "agent-a")
    assert lb.holder_of(a, "p3").agent_id == "agent-a"


def test_local_plans_not_published_by_default(clones, monkeypatch):
    a, b, _ = clones
    pa = _plan(a, "features/priv.local.md")
    plan_lease.claim_and_move(pa, "features/priv.local.md", "agent-a")
    assert lb.list_leases(b) == []
    monkeypatch.setenv("ANCHOR_LEASE_PUBLISH_LOCAL", "1")
    pa2 = _plan(a, "features/pub.local.md")
    plan_lease.claim_and_move(pa2, "features/pub.local.md", "agent-a")
    assert [lz.slug for lz in lb.list_leases(b)] == ["pub.local"]


def test_offline_falls_back_to_local_with_warning(clones, tmp_path, capsys):
    a, _, _ = clones
    _run(a, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    plan_lease._warned.clear()
    pa = _plan(a, "features/off.md")
    lease, dest = plan_lease.claim_and_move(pa, "features/off.md", "agent-a")
    assert dest.is_file() and lease.agent_id == "agent-a"
    assert "using local lease only" in capsys.readouterr().err


def test_strict_refuses_when_unavailable(clones, tmp_path, monkeypatch):
    a, _, _ = clones
    _run(a, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    monkeypatch.setenv("ANCHOR_LEASE_STRICT", "1")
    pa = _plan(a, "features/strict.md")
    with pytest.raises(plan_lease.ClaimError, match="strict"):
        plan_lease.claim_and_move(pa, "features/strict.md", "agent-a")
    assert (pa / "features" / "strict.md").is_file()


def test_branch_layer_can_be_disabled(clones, monkeypatch):
    a, b, _ = clones
    monkeypatch.setenv("ANCHOR_LEASE_BRANCH", "0")
    pa = _plan(a, "features/off2.md")
    plan_lease.claim_and_move(pa, "features/off2.md", "agent-a")
    assert lb.list_leases(b) == []


def test_next_skips_plan_leased_on_another_clone(clones):
    import plan_select

    a, b, _ = clones
    for clone in (a, b):
        for name in ("first", "second"):
            _plan(clone, f"features/{name}.md")
    plan_lease.claim_and_move(_plan(a, "features/first.md"), "features/first.md", "agent-a")
    skip = {r for r in plan_lease.claimed_rels(_plan(b, "features/first.md"))}
    rec = plan_select.select_one(
        _plan(b, "features/first.md"), plan_select.Worker(name="t", tier="mid"),
        skip_rels=skip,
    )
    assert rec is not None and rec.slug == "second"


# --- review round 1 regressions --------------------------------------------


def _as_host(monkeypatch, name):
    monkeypatch.setenv("ANCHOR_LEASE_HOST", name)


def test_same_agent_id_on_another_host_does_not_steal_or_delete(clones, monkeypatch):
    a, b, _ = clones
    _as_host(monkeypatch, "host-a")
    lb.claim(a, "alpha", "mcp-agent")
    _as_host(monkeypatch, "host-b")
    with pytest.raises(lb.LeaseConflict, match="host-a"):
        lb.claim(b, "alpha", "mcp-agent")
    with pytest.raises(lb.LeaseConflict):
        lb.renew(b, "alpha", "mcp-agent", force=True)
    with pytest.raises(lb.LeaseConflict):
        lb.release(b, "alpha", "mcp-agent")
    with pytest.raises(lb.LeaseConflict):
        lb.release(b, "alpha")  # no agent id: host must still match
    _as_host(monkeypatch, "host-a")
    assert lb.holder_of(a, "alpha").host == "host-a"
    assert lb.release(a, "alpha", "mcp-agent") is True


def test_same_agent_other_host_expired_needs_recover(clones, monkeypatch):
    a, b, _ = clones
    monkeypatch.setenv("ANCHOR_LEASE_SKEW_SECONDS", "0")
    _as_host(monkeypatch, "host-a")
    lb.claim(a, "old", "mcp-agent", ttl_seconds=1)
    time.sleep(1.2)
    _as_host(monkeypatch, "host-b")
    with pytest.raises(lb.LeaseConflict, match="recover"):
        lb.claim(b, "old", "mcp-agent")
    assert lb.claim(b, "old", "mcp-agent", recover=True).host == "host-b"


def test_git_runs_with_c_locale(clones, monkeypatch):
    a, _, _ = clones
    seen = {}
    real = lb.subprocess.run

    def spy(*args, **kwargs):
        seen["env"] = kwargs.get("env")
        return real(*args, **kwargs)

    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setattr(lb.subprocess, "run", spy)
    lb._git(a, "status")
    assert seen["env"]["LC_ALL"] == "C" and seen["env"]["LANGUAGE"] == "C"


def test_non_orphan_remote_leases_branch_is_not_adopted(clones, tmp_path):
    a, b, bare = clones
    _run(a, "push", "-q", "origin", "HEAD:refs/heads/leases")  # shares history with HEAD
    before = _run(bare, "rev-parse", "refs/heads/leases")
    with pytest.raises(lb.LeaseBranchUnavailable, match="not a lease branch"):
        lb.claim(b, "alpha", "agent-b")
    assert _run(bare, "rev-parse", "refs/heads/leases") == before


def test_clean_tree_but_shared_history_is_not_an_orphan(clones):
    a, b, bare = clones
    head = _run(a, "rev-parse", "HEAD")
    tree = lb._build_tree(a, None, {"leases/x.json": b"{}"})
    sha = lb._commit(a, tree, head, "tree is clean, history is not")
    _run(a, "push", "-q", "origin", f"{sha}:refs/heads/leases")
    with pytest.raises(lb.LeaseBranchUnavailable, match="not an orphan"):
        lb.claim(b, "alpha", "agent-b")
    assert _run(bare, "rev-parse", "refs/heads/leases") == sha


def test_non_isolated_orphan_remote_branch_is_not_adopted(clones):
    a, _, bare = clones
    tree = lb._build_tree(a, None, {"README.md": b"x"})
    sha = lb._commit(a, tree, None, "foreign orphan")
    _run(a, "push", "-q", "origin", f"{sha}:refs/heads/leases")
    with pytest.raises(lb.LeaseBranchUnavailable, match="not a lease branch"):
        lb.claim(a, "alpha", "agent-a")
    assert _run(bare, "rev-parse", "refs/heads/leases") == sha


def test_foreign_remote_branch_degrades_claim_and_move_to_local(clones, capsys):
    a, _, bare = clones
    _run(a, "push", "-q", "origin", "HEAD:refs/heads/leases")
    plan_lease._warned.clear()
    pa = _plan(a, "features/fb.md")
    lease, dest = plan_lease.claim_and_move(pa, "features/fb.md", "agent-a")
    assert dest.is_file() and lease.agent_id == "agent-a"
    assert "using local lease only" in capsys.readouterr().err


def test_unrelated_local_leases_branch_is_left_alone(clones):
    a, b, _ = clones
    _run(a, "branch", "leases", "HEAD")  # a user's own, unrelated branch
    mine = _run(a, "rev-parse", "refs/heads/leases")
    lb.claim(a, "alpha", "agent-a")
    assert _run(a, "rev-parse", "refs/heads/leases") == mine
    assert lb.holder_of(b, "alpha") is not None


def test_local_leases_branch_follows_ours(clones):
    a, _, bare = clones
    lb.claim(a, "alpha", "agent-a")
    first = _run(a, "rev-parse", "refs/heads/leases")
    lb.claim(a, "beta", "agent-a")
    assert _run(a, "rev-parse", "refs/heads/leases") == _run(bare, "rev-parse", "refs/heads/leases")
    assert _run(a, "rev-parse", "refs/heads/leases") != first


def test_forced_local_release_never_deletes_foreign_shared_lease(clones, monkeypatch):
    a, b, _ = clones
    pa = _plan(a, "features/fx.md")
    pb = _plan(b, "features/fx.md")
    _as_host(monkeypatch, "host-a")
    plan_lease.claim_and_move(pa, "features/fx.md", "mcp-agent")
    _as_host(monkeypatch, "host-b")
    (pb / ".leases").mkdir(exist_ok=True)
    plan_lease.release(pb, "in-progress/fx.md", agent_id="mcp-agent", force=True)
    plan_lease.release(pb, "features/fx.md", force=True)
    assert lb.holder_of(b, "fx").host == "host-a"


def test_non_blocking_calls_warn_instead_of_raising(clones, monkeypatch, capsys):
    a, b, _ = clones
    pa = _plan(a, "features/nb.md")
    pb = _plan(b, "features/nb.md")
    _as_host(monkeypatch, "host-a")
    plan_lease.claim_and_move(pa, "features/nb.md", "agent-a")
    _as_host(monkeypatch, "host-b")
    plan_lease.claim(pb, "in-progress/nb.md", "agent-b")  # local-only lease
    plan_lease._warned.clear()
    plan_lease.renew(pb, "in-progress/nb.md", "agent-b")  # shared holder differs: warn, no raise
    plan_lease.release(pb, "in-progress/nb.md", agent_id="agent-b")
    assert "shared lease not changed" in capsys.readouterr().err
    assert lb.holder_of(a, "nb").agent_id == "agent-a"

    def boom(root):
        raise lb.LeaseBranchError("git rev-parse failed")

    monkeypatch.setattr(lb, "list_leases", boom)
    assert plan_lease.claimed_rels(pb) == set()
    assert plan_lease.owner_of(pb, "features/zzz.md") is None


def test_warn_once_dedupes_per_reason(clones, monkeypatch, capsys):
    a, _, _ = clones
    msgs = iter(("gone-one", "gone-two"))

    def boom(_root):
        raise lb.LeaseBranchUnavailable(next(msgs))

    monkeypatch.setattr(lb, "list_leases", boom)
    plan_lease._warned.clear()
    plan_lease.claimed_rels(_plan(a, "features/w1.md"))
    plan_lease.claimed_rels(_plan(a, "features/w2.md"))
    err = capsys.readouterr().err
    assert err.count("using local lease only") == 1
    assert "gone-one" in err and "gone-two" not in err


def test_heartbeat_interval_capped_by_ttl(clones):
    a, _, bare = clones
    lb.claim(a, "short", "agent-a", ttl_seconds=3)
    before = _run(bare, "rev-parse", "refs/heads/leases")
    lb.renew(a, "short", "agent-a", ttl_seconds=3)  # inside ttl/3 = 1s: throttled
    assert _run(bare, "rev-parse", "refs/heads/leases") == before
    time.sleep(1.2)
    lb.renew(a, "short", "agent-a", ttl_seconds=3)  # past ttl/3: pushes despite the 2h default
    assert _run(bare, "rev-parse", "refs/heads/leases") != before


def test_network_timeout_is_unavailable(clones, monkeypatch):
    a, _, _ = clones
    lb.claim(a, "alpha", "agent-a")
    calls: list[tuple[list, object]] = []
    real = lb.subprocess.run

    def spy(*args, **kwargs):
        argv = list(args[0]) if args else list(kwargs.get("args") or [])
        calls.append((argv, kwargs.get("timeout")))
        return real(*args, **kwargs)

    monkeypatch.setattr(lb.subprocess, "run", spy)
    lb.fetch(a)

    def verb(argv: list) -> str:
        if len(argv) > 3 and argv[0] == "git" and argv[1] == "-C":
            return argv[3]
        return argv[1] if len(argv) > 1 else ""

    fetch_t = [t for argv, t in calls if verb(argv) == "fetch"]
    remote_t = [t for argv, t in calls if verb(argv) == "remote"]
    assert fetch_t and all(t == lb.net_timeout_seconds() for t in fetch_t)
    assert all(t is None for t in remote_t)

    def hang(*args, **kwargs):
        raise lb.subprocess.TimeoutExpired(cmd="git fetch", timeout=1)

    monkeypatch.setattr(lb.subprocess, "run", hang)
    with pytest.raises(lb.LeaseBranchUnavailable, match="timed out"):
        lb.fetch(a)


def test_mutate_attempt_does_one_fetch(clones, monkeypatch):
    a, _, _ = clones
    lb.claim(a, "alpha", "agent-a")
    fetches: list = []
    real = lb._git

    def spy(root, *args, **kwargs):
        if args and args[0] == "fetch":
            fetches.append(args)
        return real(root, *args, **kwargs)

    monkeypatch.setattr(lb, "_git", spy)
    lb.claim(a, "beta", "agent-a")
    assert len(fetches) == 1


def test_payload_has_no_branch_name(clones):
    a, _, bare = clones
    _run(a, "checkout", "-q", "-b", "feature/secret.local")
    lb.claim(a, "alpha", "agent-a")
    blob = _run(bare, "show", "refs/heads/leases:leases/alpha.json")
    assert "branch" not in json.loads(blob) and "secret" not in blob


def test_one_round_trip_fetch_and_first_write_bootstraps(clones):
    a, b, bare = clones
    assert lb.fetch(a) is None  # no branch yet: absent, not an error
    lb.claim(a, "alpha", "agent-a")  # first writer creates the orphan branch
    assert _run(bare, "rev-list", "--count", "refs/heads/leases") == "2"  # init + claim


def test_claim_and_move_expired_ready_lease_is_reclaimable(clones, monkeypatch):
    a, b, _ = clones
    monkeypatch.setenv("ANCHOR_LEASE_SKEW_SECONDS", "0")
    _as_host(monkeypatch, "host-a")
    _plan(a, "features/old.md")
    pb = _plan(b, "features/old.md")
    lb.claim(a, "old", "agent-a", ttl_seconds=1)
    time.sleep(1.2)
    _as_host(monkeypatch, "host-b")
    lease, dest = plan_lease.claim_and_move(pb, "features/old.md", "agent-b")
    assert dest.name == "old.md" and lease.agent_id == "agent-b"
    assert lb.holder_of(b, "old").host == "host-b"


def test_claim_and_move_expired_in_progress_needs_recover(clones, monkeypatch):
    a, _, _ = clones
    monkeypatch.setenv("ANCHOR_LEASE_SKEW_SECONDS", "0")
    pa = _plan(a, "features/ip.md")
    plan_lease.claim_and_move(pa, "features/ip.md", "agent-a", ttl_seconds=1)
    time.sleep(1.2)
    with pytest.raises(plan_lease.ClaimError, match="recover"):
        plan_lease.claim_and_move(pa, "in-progress/ip.md", "agent-b")
    lease, _dest = plan_lease.claim_and_move(
        pa, "in-progress/ip.md", "agent-b", recover=True
    )
    assert lease.agent_id == "agent-b"


def test_expired_own_lease_resets_claimed_at(clones, monkeypatch):
    a, _, _ = clones
    monkeypatch.setenv("ANCHOR_LEASE_SKEW_SECONDS", "0")
    first = lb.claim(a, "old", "agent-a", ttl_seconds=1)
    time.sleep(1.2)
    second = lb.claim(a, "old", "agent-a")
    assert second.claimed_at > first.claimed_at


def test_owner_of_surfaces_foreign_host(clones, monkeypatch):
    a, b, _ = clones
    pa = _plan(a, "features/fx.md")
    pb = _plan(b, "features/fx.md")
    _as_host(monkeypatch, "host-a")
    plan_lease.claim_and_move(pa, "features/fx.md", "mcp-agent")
    _as_host(monkeypatch, "host-b")
    assert plan_lease.owner_of(pb, "features/fx.md") == "mcp-agent@host-a"


def test_local_leases_branch_follows_compact(clones):
    a, b, bare = clones
    lb.claim(a, "alpha", "agent-a")
    lb.claim(b, "beta", "agent-b")
    before = _run(b, "rev-parse", "refs/heads/leases")
    lb.compact(a)
    lb.bootstrap(b)
    after = _run(b, "rev-parse", "refs/heads/leases")
    assert after == _run(bare, "rev-parse", "refs/heads/leases")
    assert after != before


def test_hook_rejection_is_unavailable_not_contention(clones, monkeypatch):
    a, _, _ = clones
    real = lb._git

    def spy(root, *args, **kwargs):
        if args and args[0] == "push":
            class _P:
                returncode = 1
                stdout = b""
                stderr = (
                    b"! [remote rejected] sha -> leases "
                    b"(pre-receive hook declined)\n"
                )
            return _P()
        return real(root, *args, **kwargs)

    monkeypatch.setattr(lb, "_git", spy)
    with pytest.raises(lb.LeaseBranchUnavailable, match="pre-receive hook declined"):
        lb.claim(a, "alpha", "agent-a")


def test_ref_lock_race_is_contention_not_unavailable(clones, monkeypatch):
    """Bare-remote CAS loser: ref lock / failed to update ref → retry, not unavailable."""
    a, _, _ = clones
    lb.bootstrap(a)
    sha = _run(a, "rev-parse", "refs/heads/leases")
    real = lb._git

    def spy(root, *args, **kwargs):
        if args and args[0] == "push":
            class _P:
                returncode = 1
                stdout = b""
                stderr = (
                    b"remote: error: cannot lock ref 'refs/heads/leases': "
                    b"is at abc but expected def\n"
                    b"! [remote rejected] sha -> leases (failed to update ref)\n"
                    b"error: failed to push some refs to 'origin'\n"
                )
            return _P()
        return real(root, *args, **kwargs)

    monkeypatch.setattr(lb, "_git", spy)
    assert lb._push(a, sha) is False
