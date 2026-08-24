"""model-fleet MCP server's own tool logic — list_fleet / lookup_endpoint — tested
against a fixture registry, independent of whether the real mcp SDK is installed.

Runs in a subprocess (not a shared sys.modules stub) because every MCP server in
this repo names its module "server"; importing several of them into one process
risks one file's stub colliding with another's real import — the same hazard
test_mcp_servers_import.py isolates against.

This file's concern is narrower than that one's: not "does the module import
against the real SDK" (test_mcp_servers_import.py owns that), but "does
list_fleet/lookup_endpoint's own logic do what the deferred-catalog plan requires"
— summary only by default, full non-secret detail on demand, no base_url/model
leaked through the summary. A minimal stand-in for the SDK's tool-registration
surface is enough for that: a real decorator registers the tool and returns the
function unchanged, so the module's own functions stay directly callable here.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_SCRIPT = """
import sys, types
sys.path.insert(0, {scripts!r})
sys.path.insert(0, {server_dir!r})

mcp_pkg = types.ModuleType("mcp")
mcp_server_pkg = types.ModuleType("mcp.server")

class _StubMCPServer:
    def __init__(self, name):
        self.name = name
        self.tools = {{}}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco

    def run(self):
        raise AssertionError("run() should never be called by this test")

mcp_server_pkg.MCPServer = _StubMCPServer
mcp_pkg.server = mcp_server_pkg
sys.modules["mcp"] = mcp_pkg
sys.modules["mcp.server"] = mcp_server_pkg

import server
from anchor_client import Fleet

server._fleet = Fleet({fixture!r})

summary = server.list_fleet()
assert "fixture-ep" in summary, summary
assert "swarm" in summary, summary
assert "http://fixture/v1" not in summary, summary
assert "fixture-model" not in summary, summary
assert "roles:" in summary, summary

detail = server.lookup_endpoint("fixture-ep")
assert "http://fixture/v1" in detail, detail
assert "fixture-model" in detail, detail
assert "strip_think=True" in detail, detail

missing = server.lookup_endpoint("does-not-exist")
assert "does-not-exist" in missing, missing
assert "fixture-ep" in missing, missing

print("OK")
"""


def test_list_fleet_and_lookup_endpoint_round_trip(tmp_path):
    fixture = tmp_path / "endpoints.yaml"
    fixture.write_text(
        "endpoints:\n"
        "  - name: fixture-ep\n    tier: swarm\n    base_url: http://fixture/v1\n"
        "    model: fixture-model\n    quirks: {strip_think: true}\n"
        "roles: {tuner: [swarm]}\n"
    )
    server_dir = REPO / "mcp" / "model-fleet"
    script = _SCRIPT.format(
        scripts=str(REPO / "scripts"), server_dir=str(server_dir), fixture=str(fixture),
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
