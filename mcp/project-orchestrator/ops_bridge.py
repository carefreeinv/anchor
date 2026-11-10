"""Call ``anchor_ops`` with an Answers port that never answers (MCP)."""
from __future__ import annotations

from typing import Any

import anchor_ops as ops
from plan_lease import ClaimError


class BridgeError(Exception):
    """Mapped onto CoordinatorError by the caller."""


def call_op(agent_id: str, name: str, params: Any) -> dict[str, Any]:
    """Run one registered operation; never prompt; never delegate."""
    ctx = ops.Ctx(
        mode=ops.Mode(False, "mcp"),
        agent_id=agent_id,
        delegate=None,
        run_orchestrate=None,
    )
    try:
        res = ops.run(name, params, ops.NeverAnswers(), ctx)
    except ops.NeedsOperator as exc:
        env = ops.Result(name.split(".", 1)[0], name.split(".", 1)[-1])
        env.exit_code = ops.EXIT_NEEDS_OPERATOR
        env.need(exc.step, ops.NEEDS_OPERATOR, str(exc))
        env.error = str(exc)
        return env.to_json(ops.Mode(False, "mcp"))
    except (ops.CliError, ClaimError, ValueError) as exc:
        raise BridgeError(str(exc)) from exc
    return res.to_json(ops.Mode(False, "mcp"))
