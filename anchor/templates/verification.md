# Verification: <task title>

<!-- Filled by TOOLING where possible, not by the model. Model claims are inputs, never evidence. -->

## Automated
| Check | Command | Result |
|---|---|---|
| Build | <cmd> | PASS/FAIL |
| Tests | <cmd> | PASS/FAIL (n passed / n failed) |
| Lint/format | <cmd> | PASS/FAIL |
| Dead/unused code | <linter unused-symbol/dead-code check> | PASS/FAIL |
| Diff scope | files changed ⊆ files in scope | PASS/FAIL |

## Manual spot-checks
- [ ] Riskiest claim in the executor's output re-derived independently
- [ ] One acceptance criterion exercised by hand

## Outcome
PASS → merge / next task
FAIL (1st) → return to executor with the failing output verbatim
FAIL (2nd) → escalate to stronger model with full history
