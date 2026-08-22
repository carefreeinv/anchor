---
title: The MCP servers stopped starting, and our own install command was the cause
authors: [carefree]
tags: [fix, tooling]
---

If `python server.py` gave you `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`, this was us.

<!-- truncate -->

All three Anchor MCP servers — `model-fleet`, `anchor-prompts`, and
`project-orchestrator` — opened with:

```python
from mcp.server.fastmcp import FastMCP
```

MCP Python SDK **2.0** removed that module and renamed `FastMCP` to `MCPServer`.
Our `pyproject.toml` files declared `mcp[cli]>=1.2.0` with **no upper bound**, so
a fresh install resolved 2.x and every server died at import. Worse, the install
command printed in each README and module docstring was the unbounded
`pip install "mcp[cli]"` — we were handing people the command that broke them.

## The fix

The decorator surface (`tool`, `prompt`, `resource`) and `run()` are unchanged
across the rename, so this needed two names, not a rewrite:

```python
try:  # SDK 2.x
    from mcp.server import MCPServer as MCPServerClass
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as MCPServerClass
```

The dependency is now bounded `>=1.2.0,<3`. A fresh install gets 2.x and works; an
operator pinned to 1.x keeps working. Both were verified by importing all three
servers against 1.29.0 and 2.0.0.

## Why it took so long to notice

Two things hid it, and both are worth knowing about independently.

**Nothing in CI installed the SDK.** No test ever imported a server, so no test
could fail.

**The tests that should have covered it skipped.** They used
`pytest.importorskip("mcp.server.fastmcp")`, and since CI never had the SDK, that
skip was permanent rather than situational — a test that never runs looks exactly
like a test that passes.

## What replaces them

`tests/test_mcp_servers_import.py` imports each server against the **actually
installed** SDK, in a subprocess run from outside the repo so the directory
shadowing cannot fool it, and asserts the child resolved a real site-packages
`mcp` before trusting the result. It also fails if any server declares an
unbounded SDK range again, or reaches for the removed module outside a guarded
fallback. `requirements-dev.txt` now installs the SDK, so CI exercises it.

We kept a separate set of tests that *stub* the SDK — those cover the delegate
gate without needing an install. They are useful and they could never have caught
this: a stub satisfies the import no matter how broken the real path is. Both
kinds are needed, for different jobs.
