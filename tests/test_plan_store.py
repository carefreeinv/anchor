"""plan_store: the single access module, and proof that callers are layout-blind.

The second half runs **unchanged** callers (plan_select, plan_lease, plan_board,
check_plans, pending_merges, release_progress, the coordinator) against a
test-only folder-per-plan layout. If any caller still assumed "a plan is a
``.md`` file in a lane directory", these tests fail — which is the whole point:
a new layout lands behind ``plan_store`` without any caller changing.
"""
from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import check_plans
import pending_merges
import plan_board
import plan_lease
import plan_select
import plan_store
import pytest
import release_progress
from plan_select import Worker

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "mcp" / "project-orchestrator"))


PLAN = """# Plan: {slug}

- **Value:** {value}
- **Priority:** {priority}
- **Preferred models:** mid
- **Depends on:** {deps}
{extra}
## Goal
Do {slug}.

## Steps
1. thing

## Done when
- done
"""


class FolderLayout:
    """Test-only layout: ``<lane>/<slug>/plan.md``; private plans ``<slug>.local/``."""

    DOC = "plan.md"
    LOCAL = ".local"

    def entries(self, lane_dir: Path) -> Iterator[tuple[str, Path]]:
        for d in lane_dir.iterdir():
            if d.is_dir() and (d / self.DOC).is_file():
                yield d.name, d / self.DOC

    def entry_path(self, lane_dir: Path, name: str) -> Path:
        return lane_dir / name

    def doc_path(self, lane_dir: Path, name: str) -> Path:
        return lane_dir / name / self.DOC

    def slug_of(self, name: str) -> str:
        return name[: -len(self.LOCAL)] if name.endswith(self.LOCAL) else name

    def names_for(self, slug: str) -> tuple[str, ...]:
        return (slug, f"{slug}{self.LOCAL}")

    def is_entry_name(self, text: str) -> bool:
        return text.endswith(self.LOCAL)

    def is_local(self, name: str) -> bool:
        return name.endswith(self.LOCAL)

    def name_from_path(self, lane_dir: Path, path: Path) -> str | None:
        try:
            rel = path.relative_to(lane_dir)
        except ValueError:
            return None
        if len(rel.parts) == 2 and rel.parts[1] == self.DOC:
            return rel.parts[0]
        if len(rel.parts) == 1 and (lane_dir / rel.parts[0] / self.DOC).is_file():
            return rel.parts[0]
        return None

    def git_pathspecs(self, lane: str, slug: str) -> tuple[str, ...]:
        return tuple(
            f"{lane}/{stem}/{self.DOC}"
            for stem in (slug, f"{slug}{self.LOCAL}", f"*-{slug}", f"*-{slug}{self.LOCAL}")
        )


def _write(plans: Path, lane: str, slug: str, *, local: bool = False, layout=None, **kw) -> Path:
    """Test fixture writer — the only code here that knows each layout's shape."""
    lay = layout or plan_store.layout()
    name = lay.names_for(slug)[1 if local else 0]
    doc = lay.doc_path(plans / lane, name)
    doc.parent.mkdir(parents=True, exist_ok=True)
    body = PLAN.format(
        slug=slug,
        value=kw.get("value", "medium"),
        priority=kw.get("priority", "P2"),
        deps=kw.get("deps", "none"),
        extra=kw.get("extra", ""),
    )
    doc.write_text(body, encoding="utf-8")
    return doc


LAYOUTS = {"flat": plan_store.FlatLayout, "folder": FolderLayout}


@pytest.fixture(params=sorted(LAYOUTS))
def layout(request):
    with plan_store.using_layout(LAYOUTS[request.param]()) as lay:
        yield lay


@pytest.fixture
def plans(tmp_path: Path) -> Path:
    root = tmp_path / ".plans"
    for lane in check_plans.KNOWN_LANES:
        (root / lane).mkdir(parents=True)
    return root


# --- the module itself ---------------------------------------------------------


def test_flat_names_and_slugs():
    lay = plan_store.FlatLayout()
    assert lay.names_for("foo") == ("foo.md", "foo.local.md")
    assert lay.slug_of("foo.local.md") == "foo"
    assert lay.slug_of("foo.md") == "foo"
    assert lay.is_local("foo.local.md") and not lay.is_local("foo.md")
    assert plan_store.strip_date_prefix("2026-08-01-foo") == "foo"


def test_list_lane_skips_readme_and_sorts(plans: Path):
    (plans / "bugs" / "README.md").write_text("# lanes\n", encoding="utf-8")
    _write(plans, "bugs", "zeta")
    _write(plans, "bugs", "alpha", local=True)
    refs = plan_store.list_lane(plans, "bugs")
    assert [r.rel for r in refs] == ["bugs/alpha.local.md", "bugs/zeta.md"]
    assert [r.slug for r in refs] == ["alpha", "zeta"]
    assert refs[0].local and not refs[1].local
    assert plan_store.count(plans, "bugs") == 2
    assert plan_store.list_lane(plans, "no-such-lane") == []


def test_lane_names_ignore_sidecars(plans: Path):
    (plans / ".leases").mkdir()
    (plans / ".releases").mkdir()
    assert ".leases" not in plan_store.lane_names(plans)
    assert "bugs" in plan_store.lane_names(plans)


def test_find_slug_matches_dated_completion(plans: Path):
    _write(plans, "completed", "2026-08-01-foo")
    _write(plans, "features", "bar")
    assert [r.rel for r in plan_store.find_slug(plans, "foo")] == [
        "completed/2026-08-01-foo.md"
    ]
    assert plan_store.find_slug(plans, "foo", dated=False) == []
    assert plan_store.find_slug(plans, "FOO")[0].base_slug == "foo"


def test_get_lookup_ref_for_path(plans: Path):
    doc = _write(plans, "features", "foo")
    ref = plan_store.get(plans, "features/foo.md")
    assert ref is not None and ref.path == doc
    assert plan_store.get(plans, "features/nope.md") is None
    assert plan_store.get(plans, "foo.md") is None
    assert [r.rel for r in plan_store.lookup(plans, "features", "foo")] == ["features/foo.md"]
    assert plan_store.ref_for_path(plans, doc).rel == "features/foo.md"
    assert plan_store.ref_for_path(plans, plans.parent / "elsewhere.md") is None


def test_move_keeps_name_and_refuses_collision(plans: Path):
    _write(plans, "features", "foo", local=True)
    new = plan_store.move(plans, "features/foo.local.md", "in-progress")
    assert new.rel == "in-progress/foo.local.md" and new.path.is_file()
    _write(plans, "features", "foo", local=True)
    with pytest.raises(plan_store.PlanMoveError, match="already exists"):
        plan_store.move(plans, "features/foo.local.md", "in-progress")
    with pytest.raises(plan_store.PlanMoveError, match="missing"):
        plan_store.move(plans, "features/ghost.md", "blocked")


def test_stray_entries(plans: Path):
    (plans / "README.md").write_text("# plans\n", encoding="utf-8")
    (plans / "loose.md").write_text("# loose\n", encoding="utf-8")
    assert plan_store.stray_entries(plans) == ["loose.md"]


def test_release_files(plans: Path):
    (plans / ".releases").mkdir()
    (plans / ".releases" / "r1.md").write_text("# Release: r1\n", encoding="utf-8")
    assert [s for s, _ in plan_store.list_release_files(plans)] == ["r1"]
    assert plan_store.release_file(plans, "r1").is_file()


# --- callers are layout-blind (Step 2 of the CLI plan) -------------------------


def test_inventory_and_select_under_any_layout(plans: Path, layout):
    _write(plans, "features", "feat-a", priority="P2")
    _write(plans, "features", "feat-b", priority="P1")
    _write(plans, "bugs", "bug-a", local=True)
    _write(plans, "drafts", "draft-a")

    recs = plan_select.inventory_ready(plans, Worker("m", "mid"))
    assert [(r.lane, r.slug) for r in recs] == [
        ("bugs", "bug-a"),
        ("features", "feat-b"),
        ("features", "feat-a"),
    ]
    assert all(r.path.is_file() for r in recs)

    pick = plan_select.select_one(plans, Worker("m", "mid"))
    assert pick is not None and pick.slug == "bug-a"

    named = plan_select.resolve_target(plans, slug="feat-a")
    assert named is not None and named.lane == "features"
    by_path = plan_select.resolve_target(plans, path=named.path)
    assert by_path is not None and by_path.rel == named.rel
    assert plan_select.plan_slug(named.path) == "feat-a"


def test_dependencies_under_any_layout(plans: Path, layout):
    _write(plans, "completed", "2026-01-01-done-dep")
    _write(plans, "features", "open-dep")
    _write(plans, "features", "needs", deps="done-dep, open-dep")
    rec = plan_select.resolve_target(plans, slug="needs")
    assert rec is not None
    assert rec.deps_unmet == ("open-dep",)
    ok, note = plan_select.dependency_status(plans, "done-dep", git_check=False)
    assert ok and "completed" in note


def test_claim_park_return_under_any_layout(plans: Path, layout):
    _write(plans, "features", "work-me")
    rel = plan_store.lookup(plans, "features", "work-me")[0].rel

    lease, path = plan_lease.claim_and_move(plans, rel, "agent-1")
    assert lease.plan_rel.startswith("in-progress/")
    assert path.is_file() and path == plan_store.get(plans, lease.plan_rel).path.resolve()
    assert plan_lease.in_progress_owned_by(plans, "agent-1") == [lease.plan_rel]
    assert plan_select.inventory_ready(plans) == []

    plan_lease.renew(plans, lease.plan_rel, "agent-1")
    parked = plan_lease.park(plans, lease.plan_rel, "blocked", agent_id="agent-1")
    assert parked.is_file()
    blocked_rel = plan_store.list_lane(plans, "blocked")[0].rel
    back = plan_lease.return_to_ready(plans, blocked_rel)
    assert back.is_file()
    assert [r.slug for r in plan_select.inventory_ready(plans)] == ["work-me"]


def test_board_check_merges_releases_under_any_layout(plans: Path, layout):
    _write(plans, "features", "shipping", extra="- **Release:** r1\n")
    _write(plans, "completed", "2026-02-02-shipped", extra="- **Release:** r1\n")
    (plans / ".releases").mkdir()
    (plans / ".releases" / "r1.md").write_text(
        "# Release: r1\n\n- **Status:** open\n", encoding="utf-8"
    )

    cols = dict(plan_board.build_columns(plans, include_parked=True))
    assert [r.slug for r in cols["Ready"]] == ["shipping"]

    assert check_plans.check_plans(plans.parent) == []

    project = plans.parent
    assert pending_merges.completed_slugs(project) == {"shipped"}
    found = pending_merges.plan_file(project, "shipping")
    assert found is not None and found.is_file()

    info = release_progress.scan_releases(plans)["r1"]
    assert info.file_exists and info.total == 2 and info.completed == 1


def test_coordinator_stale_report_under_any_layout(plans: Path, layout):
    import coordinator

    _write(plans, "blocked", "parked-one")
    cfg = coordinator.CoordinatorConfig(
        project_root=plans.parent,
        capabilities=("L0",),
        parked_stale_hours=0,
    )
    report = coordinator.plans_stale_report(cfg)
    parked = [w for w in report["warnings"] if w["code"] == "STALE-PARKED"]
    assert [w["slug"] for w in parked] == ["parked-one"]


# --- no caller references the layout -------------------------------------------

CALLERS = [
    "scripts/plan_select.py",
    "scripts/plan_lease.py",
    "scripts/plan_board.py",
    "scripts/plan_fit.py",
    "scripts/check_plans.py",
    "scripts/fleet_watch.py",
    "scripts/pending_merges.py",
    "scripts/release_progress.py",
    "scripts/work_once.py",
    "scripts/batch_dispatch.py",
    "scripts/merge_feature.py",
    "scripts/orchestrate.py",
    "mcp/project-orchestrator/coordinator.py",
    "scripts/anchor_cli.py",
    "scripts/lease_branch.py",
]

# Non-plan markdown these callers legitimately name (not a plan layout leak).
ALLOWED = {
    ("scripts/orchestrate.py", "human-reports"),  # human report file, not a plan
    ("scripts/release_progress.py", ".releases/"),  # release definition, not a plan
    # leases branch key is basename-without-.md (keeps `.local`); not a lane glob
    ("scripts/lease_branch.py", 'endswith(".md")'),
}

_PLAN_TOKENS = {".md", ".local.md", "*.md", "*.local.md", "README.md"}


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def layout_leaks(rel: str) -> list[str]:
    src = (REPO / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    docs = _docstring_ids(tree)
    lines = src.splitlines()
    hits: list[str] = []
    for node in ast.walk(tree):
        bad = False
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            bad = node.value in _PLAN_TOKENS or ".local.md" in node.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("glob", "rglob") and node.args:
                arg = node.args[0]
                bad = isinstance(arg, ast.Constant) and ".md" in str(arg.value)
        if not bad:
            continue
        line = lines[node.lineno - 1]
        context = "\n".join(lines[max(0, node.lineno - 6) : node.lineno])
        if any(f == rel and frag in context for f, frag in ALLOWED):
            continue
        hits.append(f"{rel}:{node.lineno}: {line.strip()}")
    return hits


def test_no_caller_references_plan_file_layout():
    leaks = [hit for rel in CALLERS for hit in layout_leaks(rel)]
    assert leaks == [], "layout leaked outside plan_store:\n" + "\n".join(leaks)


def test_leak_detector_catches_a_leak(tmp_path: Path, monkeypatch):
    bad = tmp_path / "scripts" / "bad.py"
    bad.parent.mkdir()
    bad.write_text(
        'from pathlib import Path\n'
        'def f(d):\n'
        '    """Docstrings may say .md freely."""\n'
        '    return list(Path(d).glob("*.md")) + [n for n in d if n.endswith(".local.md")]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.modules[__name__], "REPO", tmp_path)
    hits = layout_leaks("scripts/bad.py")
    assert len(hits) == 3  # glob call, its "*.md", and ".local.md"
    assert all(re.search(r"bad\.py:4:", h) for h in hits)
