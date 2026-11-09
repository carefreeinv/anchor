# CLI typed decisions

Every place the Harness *chooses* rather than computes. Output is a finite
set; the rule is named. Default paths generate **zero** tokens. Opt-in
`--delegate` / `--run` (via `work_once`) is not a default-path decision.

| Decision | Finite set | Rule |
|----------|------------|------|
| Verb vs scaffolder | `verb` \| `scaffold` | First argv token in the verb set (`plans`, `work`, `review`, `draft`, `models`, `fleet-watch`, …) |
| Plan lane | `bugs` \| `features` \| `in-progress` \| `review-needed` \| `drafts` \| `completed` \| `ambiguous` \| `blocked` | Directory under `.plans/` (path is authoritative) |
| Fit | `good` \| `overqualified` \| `underqualified` \| `unknown` | `plan_select.classify_fit` — highest Preferred **tier** is the floor |
| Effort advice | `ok` \| `wasteful` \| `underpowered` \| `unknown` | `plan_select` effort map; does not gate eligibility alone |
| Ready pick skip | `take` \| `skip-deps` \| `skip-assignee` \| `skip-fit` \| `skip-lease` | Unmet Depends-on, human Assignee, poor fit, foreign lease |
| Work finish | `review-needed` \| `stay in-progress` | `plan_finish_gate` evidence vs empty claim |
| Review decision (operator) | `approve` \| `needs-work` \| `skip` \| `defer` | Prompted; CLI never infers |
| Promote vs plan review | `promote` \| `plan` | `--promote` or empty queue + integration ahead |
| Draft privacy | `local` \| `shared` | `--local` default `*.local.md` |
| Draft ready lane | `bugs` \| `features` | `--to` or inferred from Goal/Value |
| Delegate | `yes` \| `no` | Interactive TTY + not `--no-delegate`; headless never |
| JSON vs table | `json` \| `table` | `--json` / no TTY / `--non-interactive` |
| Endpoint resolve | `hit` \| `miss` | Registry name or overlay alias |
| Fast-forward merge | `ff` \| `not-ff` \| `already-contained` | git ancestry vs integration |

Findings (none to widen here): critic `## Verdict` body text can still parse
`REVISE` from the word appearing under an `ACCEPT` heading — that is
`critic_verdict` parsing, not a free-text *decision* the CLI emits.
