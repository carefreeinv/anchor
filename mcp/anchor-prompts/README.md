# anchor-prompts MCP server

Serves the Anchor discipline as tools, so a lesser model doesn't have to *remember* how to behave — it can fetch and be checked.

Tools: `get_doctrine`, `get_system_prompt(model)`, `get_template(name)`, `tune_prompt(rough_task)`, `preflight_check(task_spec)`.
Prompts: `plan_task(goal)`, `critique_work(spec, work)`.

`preflight_check` is the quiet workhorse: a *deterministic* gate that refuses under-specified work before any tokens are spent — exactly the check small models skip.

## Install

```bash
cd mcp/anchor-prompts && pip install "mcp[cli]" requests pyyaml
# Claude Code
claude mcp add anchor-prompts -- python /abs/path/mcp/anchor-prompts/server.py
# Any other MCP client: stdio transport, command = python server.py
```
