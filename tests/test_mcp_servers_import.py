"""Every MCP server imports against the SDK that is actually installed.

This deliberately imports the **real** installed SDK. A test that stubs `FastMCP`
into `sys.modules` satisfies the import no matter what the real SDK does — useful
for exercising a server's own logic without an install, and useless for catching
an SDK break. An SDK break is exactly what shipped: `mcp.server.fastmcp` was
removed in SDK 2.0, while the servers declared an unbounded `mcp[cli]>=1.2.0`, so
a fresh install crashed at import.

Two hazards this test has to dodge, both of which hid the original bug:

1. The child must be importing the **real** SDK, not something local. Anchor has a
   top-level ``mcp/`` directory; it is only a PEP 420 namespace portion, so an
   installed package still wins — but it does mask the honest "not installed"
   error when the SDK is absent. Each import therefore runs in a subprocess with
   cwd set elsewhere, and the child asserts it resolved a site-packages ``mcp``
   before trusting the result.
2. Skipping on a missing SDK must not become skipping always. The skip is keyed to
   a real probe, and `requirements-dev.txt` installs the SDK so CI does not skip.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVERS = ("model-fleet", "anchor-prompts", "project-orchestrator")

# Exit codes are distinct on purpose: only a genuinely ABSENT SDK may skip.
# A present-but-broken SDK that skipped would recreate the very failure mode this
# file exists to remove — a test that never runs looks exactly like one that passes.
_PROBE_ABSENT, _PROBE_UNUSABLE = 3, 4

_PROBE = """
import sys
try:
    import mcp
except ModuleNotFoundError as exc:
    if (exc.name or "").split(".")[0] == "mcp":
        sys.exit(3)                      # genuinely not installed -> skip
    raise                                # something else is broken -> fail
if not (mcp.__file__ or ""):
    sys.exit(3)          # namespace portion only: the SDK is not installed
print(getattr(mcp, "__version__", "unknown"))
"""


def _run(code: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)],
                          cwd=str(cwd), capture_output=True, text=True, timeout=120)


@pytest.fixture(scope="module")
def sdk_probe(tmp_path_factory) -> subprocess.CompletedProcess:
    outside = tmp_path_factory.mktemp("outside-repo")
    return _run(_PROBE, outside)


def _require_sdk(probe: subprocess.CompletedProcess) -> None:
    """Skip only when the SDK is absent; a broken one must fail loudly."""
    if probe.returncode == 0:
        return
    if probe.returncode == _PROBE_ABSENT:
        pytest.skip("MCP SDK not installed (requirements-dev.txt installs it in CI)")
    pytest.fail(
        f"MCP SDK is present but unusable (probe exit {probe.returncode}):\n"
        f"{probe.stderr[-1500:]}"
    )


@pytest.mark.parametrize("server_name", SERVERS)
def test_server_imports_against_the_installed_sdk(server_name, tmp_path, sdk_probe):
    _require_sdk(sdk_probe)
    server_dir = REPO / "mcp" / server_name
    assert (server_dir / "server.py").is_file(), server_dir
    # Importing is not enough. project-orchestrator defers its SDK import into
    # build_server(), so `import server` succeeds even on code that cannot run —
    # proven when this file was replayed against the pre-fix tree, where that one
    # server passed while the other two failed. Force the server object to exist.
    result = _run(
        f"""
        import mcp, sys
        assert "site-packages" in mcp.__file__, mcp.__file__
        sys.path.insert(0, {str(server_dir)!r})
        import server
        built = getattr(server, "mcp", None) or server.build_server()
        assert built is not None
        print("OK")
        """,
        tmp_path,
    )
    assert result.returncode == 0, (
        f"{server_name} failed to import against the installed SDK:\n"
        f"{result.stderr[-1500:]}"
    )
    assert "OK" in result.stdout


def test_servers_declare_a_bounded_sdk_range():
    # The original defect was an UNBOUNDED `mcp[cli]>=1.2.0`: a new major silently
    # became the resolved version and every server died at import.
    for server_name in SERVERS:
        toml = (REPO / "mcp" / server_name / "pyproject.toml").read_text(encoding="utf-8")
        line = next(ln for ln in toml.splitlines() if "mcp[cli]" in ln)
        assert "<" in line, (
            f"{server_name}/pyproject.toml pins no upper bound on mcp[cli]: {line.strip()}"
        )


REMOVED_MODULE = "mcp.server.fastmcp"
_IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _handler_catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:  # bare except
        return True
    names = (
        [handler.type] if isinstance(handler.type, ast.Name)
        else list(handler.type.elts) if isinstance(handler.type, ast.Tuple)
        else []
    )
    return any(isinstance(n, ast.Name) and n.id in _IMPORT_ERRORS for n in names)


def _guarded_nodes(tree: ast.AST) -> set[int]:
    """Every node sitting inside a try/except that catches an import failure.

    Both halves count: the attempted import in the ``try`` body and the fallback
    in the handler — the shim puts the removed module in the handler.
    """
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not any(_handler_catches_import_error(h) for h in node.handlers):
            continue
        for branch in (node.body, *(h.body for h in node.handlers)):
            for stmt in branch:
                for child in ast.walk(stmt):
                    guarded.add(id(child))
    return guarded


def _imports_of(tree: ast.AST, module: str) -> list[ast.stmt]:
    """Every import that reaches *module*, in any of the shapes Python allows.

    Asymmetry here was a real hole: matching `ImportFrom` on exact equality let
    ``from mcp.server.fastmcp.prompts import base`` and ``from mcp.server import
    fastmcp`` through untouched, and SDK 1 genuinely exposes both paths.
    """
    parent, _, leaf = module.rpartition(".")
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == module or mod.startswith(module + "."):
                found.append(node)                      # from mcp.server.fastmcp[...] import X
            elif mod == parent and any(a.name == leaf for a in node.names):
                found.append(node)                      # from mcp.server import fastmcp
        elif isinstance(node, ast.Import):
            if any(a.name == module or a.name.startswith(module + ".")
                   for a in node.names):
                found.append(node)
    return found


@pytest.mark.parametrize("server_name", SERVERS)
def test_removed_module_is_only_imported_as_a_guarded_fallback(server_name):
    # A bare `from mcp.server.fastmcp import ...` is the shape that broke. Parsed,
    # not grepped: indentation says nothing about whether an import is actually
    # protected — one inside a plain `if` or a function body is still unguarded.
    source = (REPO / "mcp" / server_name / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename=f"{server_name}/server.py")
    guarded = _guarded_nodes(tree)
    for node in _imports_of(tree, REMOVED_MODULE):
        assert id(node) in guarded, (
            f"{server_name}/server.py:{node.lineno} imports {REMOVED_MODULE!r} "
            f"without a try/except ImportError guard — that is the exact shape "
            f"that broke on SDK 2.0"
        )


def test_the_guard_detector_actually_detects():
    # A test whose failure mode is "silently passes" is worth testing itself.
    unguarded = ast.parse("from mcp.server.fastmcp import FastMCP\n")
    assert _imports_of(unguarded, REMOVED_MODULE)
    assert not _guarded_nodes(unguarded)

    plain_indent = ast.parse(
        "if True:\n    from mcp.server.fastmcp import FastMCP\n"
    )
    # Indented but NOT guarded — the old line-based check passed this.
    node = _imports_of(plain_indent, REMOVED_MODULE)[0]
    assert id(node) not in _guarded_nodes(plain_indent)

    shim = ast.parse(
        "try:\n    from mcp.server import MCPServer\n"
        "except ImportError:\n    from mcp.server.fastmcp import FastMCP\n"
    )
    node = _imports_of(shim, REMOVED_MODULE)[0]
    assert id(node) in _guarded_nodes(shim)


@pytest.mark.parametrize("source", [
    "from mcp.server.fastmcp import FastMCP",            # the shape that broke
    "import mcp.server.fastmcp",
    "import mcp.server.fastmcp.prompts",
    "from mcp.server.fastmcp.prompts import base",       # submodule from-import
    "from mcp.server import fastmcp",                    # bind the module itself
])
def test_every_route_to_the_removed_module_is_detected(source):
    # Matching ImportFrom on exact equality let the last two through untouched,
    # and SDK 1 really does expose mcp.server.fastmcp.Context and
    # mcp.server.fastmcp.prompts.base — so a type hint would have sailed past.
    assert _imports_of(ast.parse(source), REMOVED_MODULE), source


@pytest.mark.parametrize("source", [
    "from mcp.server import MCPServer",
    "import mcp.server.mcpserver",
    "from mcp.server.mcpserver import MCPServer",
])
def test_the_replacement_module_is_not_flagged(source):
    assert not _imports_of(ast.parse(source), REMOVED_MODULE), source


def test_a_sibling_handler_does_not_launder_an_unguarded_import():
    # try/except ValueError around it is not an import guard.
    tree = ast.parse(
        "try:\n    pass\nexcept ValueError:\n"
        "    from mcp.server.fastmcp import FastMCP\n"
    )
    node = _imports_of(tree, REMOVED_MODULE)[0]
    assert id(node) not in _guarded_nodes(tree)
