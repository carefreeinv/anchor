# Review: <task/plan title>

<!-- Critic pass. Run in a FRESH context — the reviewer must not be the executor's conversation. -->

## Inputs
- Original task spec / plan
- The diff / produced artifact
- Verification output (test/lint/build logs)

## Checklist
- [ ] Every acceptance criterion demonstrably met (cite evidence, not claims)
- [ ] Nothing outside scope was touched
- [ ] No invented APIs, flags, or file contents (spot-check 2 riskiest)
- [ ] Error handling for the failure modes the plan listed
- [ ] Verification commands actually run and pass (attach output)
- [ ] SOLID + the project's idiomatic composition mechanism used, not deep inheritance (see `ANCHOR-CONVENTIONS.md` if present)
- [ ] No dead code, unreachable branches, or commented-out blocks introduced
- [ ] No step ran on a tier more expensive than the task needed

## Verdict
ACCEPT | REVISE (with the single most important fix) | ESCALATE (with what the bigger model must decide)

## Notes for next task
<anything the planner should know>
