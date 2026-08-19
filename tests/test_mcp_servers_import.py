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


def test_no_server_imports_the_removed_module_unguarded():
    # A bare `from mcp.server.fastmcp import ...` is the shape that broke. It may
    # only appear as a guarded fallback inside a try/except ImportError.
    for server_name in SERVERS:
        source = (REPO / "mcp" / server_name / "server.py").read_text(encoding="utf-8")
        for i, line in enumerate(source.splitlines()):
            if "mcp.server.fastmcp" not in line or line.lstrip().startswith("#"):
                continue
            assert line.startswith((" ", "\t")), (
                f"{server_name}/server.py:{i + 1} imports the removed module at "
                f"module level: {line.strip()}"
            )
