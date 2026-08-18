"""Local delegation is refused while the site inference-load cap is on.

The gate itself lives in ``inference_load.endpoint_refusal`` so it is testable
without the MCP SDK. The thin server wrapper is covered too, against a **stubbed**
``FastMCP``: the real SDK is not installed in CI, and current SDK releases no
longer expose ``mcp.server.fastmcp`` at all, so an ``importorskip`` here would skip
forever and quietly leave the delegate gate unverified.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path
from unittest.mock import patch

import inference_load as il
import pytest
from anchor_client import Endpoint

REPO = Path(__file__).resolve().parents[1]


def _local(tier: str = "swarm") -> Endpoint:
    return Endpoint(name="box", tier=tier, base_url="http://127.0.0.1:11434/v1",
                    model="qwen3:4b")


def _cloud() -> Endpoint:
    return Endpoint(name="api", tier="frontier", base_url="https://api.example.com/v1",
                    model="big")


def _level(root: Path, level: str, **kw) -> None:
    il.write_cache(root / il.DEFAULT_CACHE_REL,
                   il.LoadPolicy(level=level, received_at=time.time(), **kw))


# -- the gate ---------------------------------------------------------------

def test_local_endpoint_refused_when_level_off(tmp_path):
    _level(tmp_path, "off", reason="grid-peak")
    refusal = il.endpoint_refusal(_local(), tmp_path)
    assert refusal is not None
    assert refusal.startswith(il.LOAD_LIMITED)
    assert "grid-peak" in refusal
    assert "No work was sent" in refusal


def test_local_endpoint_allowed_at_matching_level(tmp_path):
    _level(tmp_path, "low")
    assert il.endpoint_refusal(_local("swarm"), tmp_path) is None


def test_heavy_local_endpoint_refused_at_low(tmp_path):
    _level(tmp_path, "low")
    refusal = il.endpoint_refusal(_local("reasoner"), tmp_path)
    assert refusal is not None
    assert "not allowed at level=low" in refusal


def test_executor_heavy_maps_to_mid(tmp_path):
    _level(tmp_path, "mid")
    assert il.endpoint_refusal(_local("executor-heavy"), tmp_path) is None
    _level(tmp_path, "low")
    assert il.endpoint_refusal(_local("executor-heavy"), tmp_path) is not None


def test_cloud_endpoint_never_refused(tmp_path):
    _level(tmp_path, "off")
    assert il.endpoint_refusal(_cloud(), tmp_path) is None


def test_unconfigured_site_never_refuses(tmp_path):
    assert il.endpoint_refusal(_local(), tmp_path) is None


def test_stale_policy_refuses_under_default_failsafe(tmp_path):
    il.write_cache(tmp_path / il.DEFAULT_CACHE_REL,
                   il.LoadPolicy(level="high", ttl_s=10, received_at=time.time() - 600))
    refusal = il.endpoint_refusal(_local(), tmp_path)
    assert refusal is not None
    assert "failsafe:hold" in refusal


def test_unknown_registry_tier_falls_back_to_the_level_gate(tmp_path):
    _level(tmp_path, "low")
    # An unmapped tier cannot be tier-checked, so only "is local work allowed at
    # all" applies — it must not be silently treated as small.
    assert il.endpoint_refusal(_local("bespoke-tier"), tmp_path) is None
    _level(tmp_path, "off")
    assert il.endpoint_refusal(_local("bespoke-tier"), tmp_path) is not None


def test_registry_tier_mapping():
    assert il.registry_tier_to_fit("swarm") == "small"
    assert il.registry_tier_to_fit("executor") == "mid"
    assert il.registry_tier_to_fit("reasoner") == "reasoner"
    assert il.registry_tier_to_fit("nonsense") is None
    assert il.registry_tier_to_fit(None) is None


# -- the MCP wrapper (against a stubbed SDK, so CI actually runs these) ------

class _StubFastMCP:
    """Enough FastMCP for import: ``@mcp.tool()`` returns the function unchanged."""

    def __init__(self, name):
        self.name = name

    def tool(self, *a, **kw):
        return lambda fn: fn

    def run(self):  # pragma: no cover - never called under test
        raise AssertionError("the stub server must not be run")


@pytest.fixture
def server(monkeypatch):
    """Import mcp/model-fleet/server.py against a stubbed SDK."""
    for name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
        module = types.ModuleType(name)
        if name == "mcp.server.fastmcp":
            module.FastMCP = _StubFastMCP
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules["mcp"].server = sys.modules["mcp.server"]
    sys.modules["mcp.server"].fastmcp = sys.modules["mcp.server.fastmcp"]
    monkeypatch.syspath_prepend(str(REPO / "mcp" / "model-fleet"))
    monkeypatch.delitem(sys.modules, "server", raising=False)
    import server as server_module

    yield server_module
    sys.modules.pop("server", None)


def test_delegate_refuses_without_sending_work(tmp_path, server):
    _level(tmp_path, "off")
    with patch.object(server, "REPO", tmp_path), \
         patch.object(server, "fleet") as fake_fleet, \
         patch.object(Endpoint, "chat") as chat:
        fake_fleet.return_value.pick.return_value = _local()
        out = server.delegate("task spec", role="executor")
    assert out.startswith(il.LOAD_LIMITED)
    chat.assert_not_called()


def test_delegate_proceeds_when_allowed(tmp_path, server):
    _level(tmp_path, "high")
    with patch.object(server, "REPO", tmp_path), \
         patch.object(server, "fleet") as fake_fleet, \
         patch.object(server, "load_prompt", return_value="SYS"), \
         patch.object(Endpoint, "chat",
                      return_value="w\n\n## Result\nr\n\n## How to verify\nv") as chat:
        fake_fleet.return_value.pick.return_value = _local()
        out = server.delegate("task spec", role="executor")
    chat.assert_called_once()
    assert il.LOAD_LIMITED not in out


def test_parallel_review_refuses_rather_than_running_one_pass(tmp_path, server):
    _level(tmp_path, "off")
    with patch.object(server, "REPO", tmp_path), \
         patch.object(server, "fleet") as fake_fleet, \
         patch.object(server, "load_prompt", return_value="TPL"), \
         patch.object(Endpoint, "chat") as chat:
        fake_fleet.return_value.pick.return_value = _local("reasoner")
        out = server.delegate_parallel_review("spec", "work")
    assert out.startswith(il.LOAD_LIMITED)
    chat.assert_not_called()


def test_list_fleet_reports_the_site_level(tmp_path, server):
    _level(tmp_path, "low", reason="solar")
    with patch.object(server, "REPO", tmp_path), \
         patch.object(server, "fleet") as fake_fleet:
        fake_fleet.return_value.endpoints = [_local(), _cloud()]
        fake_fleet.return_value.roles = {"executor": ["swarm"]}
        out = server.list_fleet()
    assert "site load: LOAD level=low" in out
    assert "local tiers allowed: small" in out
    assert "- box [swarm] local" in out
