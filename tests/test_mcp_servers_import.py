"""Every MCP server imports against the SDK that is actually installed.

This is deliberately **not** the stubbed-`FastMCP` approach used in
`test_model_fleet_load.py`. That stub satisfies the import no matter what the real
SDK does, which is right for testing the delegate gate and useless for catching an
SDK break — and an SDK break is exactly what shipped: `mcp.server.fastmcp` was
removed in SDK 2.0, while the servers declared an unbounded `mcp[cli]>=1.2.0`, so
a fresh install crashed at import.

Two hazards this test has to dodge, both of which hid the original bug:

1. Anchor has its own top-level ``mcp/`` **directory**, which shadows the installed
   ``mcp`` package for anything running from the repo root — where pytest runs. So
   each import happens in a subprocess with cwd set elsewhere, and the child
   asserts it resolved a site-packages ``mcp`` before trusting the result.
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

_PROBE = """
import mcp, sys
if "site-packages" not in (mcp.__file__ or ""):
    sys.exit(3)          # shadowed by some local directory, not the real package
print(getattr(mcp, "__version__", "unknown"))
"""


def _run(code: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)],
                          cwd=str(cwd), capture_output=True, text=True, timeout=120)


@pytest.fixture(scope="module")
def sdk_available(tmp_path_factory) -> bool:
    outside = tmp_path_factory.mktemp("outside-repo")
    return _run(_PROBE, outside).returncode == 0


@pytest.mark.parametrize("server_name", SERVERS)
def test_server_imports_against_the_installed_sdk(server_name, tmp_path, sdk_available):
    if not sdk_available:
        pytest.skip("MCP SDK not installed (requirements-dev.txt installs it in CI)")
    server_dir = REPO / "mcp" / server_name
    assert (server_dir / "server.py").is_file(), server_dir
    result = _run(
        f"""
        import mcp, sys
        assert "site-packages" in mcp.__file__, mcp.__file__
        sys.path.insert(0, {str(server_dir)!r})
        import server
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
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            found.append(node)
        elif isinstance(node, ast.Import):
            if any(alias.name == module or alias.name.startswith(module + ".")
                   for alias in node.names):
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


def test_the_guard_detector_actually_detects(tmp_path):
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
