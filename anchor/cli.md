# The plan-workflow CLI: what `anchor` does itself, and what it hands back

`anchor plans | work | review | draft | fleet-watch` runs the `.plans/` workflow from a
terminal, with no chat harness. It is a small, deterministic program: every
decision it makes comes from a fixed set of outcomes with a rule you can name,
and it runs no model on any default path. Anything that needs judgment is either
**delegated** (only when you ask, and only interactively) or **handed back** as
a named pending step.

Implementation: verb logic lives in `scripts/anchor_ops.py` (a typed operations
registry). `scripts/anchor_cli.py` is the terminal adapter — parser, prompts,
text/JSON rendering — reached through `scripts/anchor.py` (`bin/anchor`) when
the first argument is a verb. Every other invocation is the scaffolder,
unchanged. A project directory that happens to be named `plans`, `work`,
`review` or `draft` is scaffolded as `./work`. `anchor --help` is the
scaffolder; verb help is `anchor work --help` (etc.). A verb plus a
scaffolder-only flag (`--platform`, `--fleet`, …) still exits 2 and prints
``did you mean `anchor ./work …` to scaffold the directory?``.

`--delegate` / `--endpoint` read an endpoints YAML (`--registry`, default
`scripts/endpoints.yaml`). A machine-local overlay such as
`~/.config/anchor/endpoints.local.yaml` is the right place for localhost
Ollama and NVIDIA Build. `anchor` loads a gitignored repo-root `.env`
(setdefault) before verbs run; Authorization is the first set of
`ANCHOR_API_KEY`, `NVIDIA_API_KEY`, `NGC_API_KEY`. `--run` hands the claimed
plan to `orchestrate.py` with no extra registry args — it uses the default
fleet file, not `--registry`.

## The rule for the split

A step is **deterministic** when its answer follows from files on disk, git and
the plan headers alone: pick, claim, lane moves, dependency and fit checks, the
merge gate. The CLI does those itself, **by calling the module that already owns
the rule**. It never re-derives lane priority, fit or `Depends on`:

| Rule | Owner the CLI calls |
|------|---------------------|
| where plans live, slugs, lane moves | `plan_store.py` |
| ready-lane priority, fit, `Depends on` | `plan_select.py` |
| claim, lease, heartbeat, finish, return | `plan_lease.py` (through `work_once.pick_claim_one` for a claim) |
| worker identity from tier, model, effort, endpoint | `work_once.resolve_worker` |
| the scoped merge gate | `merge_feature.run` |
| hold notes | `pending_merges.is_held` |

A step **needs a model** when its output is prose or judgment: writing a plan,
a critic pass, carrying out a plan's Steps. A step **needs an operator** when
doctrine requires a human answer given in this session. A flag can't supply
that answer, so the CLI has none that tries.

## Per verb

### `anchor plans`

| Part | Kind | Why |
|------|------|-----|
| list every lane (or `--lane`) with slug and title | deterministic | a directory read |
| `--board` | deterministic | hands off to `plan_board.py`; JSON when headless |

### `anchor work`

| Part | Kind | Why |
|------|------|-----|
| `--list`: ready plans with your fit and deps | deterministic | `plan_select.inventory` |
| claim (bare pick or named slug) | deterministic | `work_once.pick_claim_one`: the same pick, skip and lease rules as `work_once.py` |
| `--heartbeat`, `--finish` (→ `review-needed/`), `--return` | deterministic | `plan_lease`; only the lease holder may move its plan |
| carry out the plan's Steps | **model** | returned as pending `execute`; `--run` (interactive only) hands the plan to `orchestrate.py` |

`anchor work` has no merge. Finishing moves the plan to `review-needed/`, the
same place every unattended finish goes. Landing work is `anchor review`'s job
(or `/work`'s culmination question inside a harness).

### `anchor review`

| Part | Kind | Why |
|------|------|-----|
| list `review-needed/` with hold notes | deterministic | directory read + `pending_merges.is_held` |
| the review package: branch, target, head, changed files, fast-forward? | deterministic | git, via `merge_feature` helpers |
| AI critic pass | **model** | pending `critic`; `--delegate` sends it to an endpoint |
| **Approve / Needs Work / Skip / Defer** | **operator** | the `/review` sign-off; never inferred |
| Approve after a critic verdict of REVISE, ESCALATE or unreadable | **operator** | a second, explicit "approve despite critic concerns?" yes; anything else leaves the plan in `review-needed/` |
| Needs Work: which ready lane, and the notes | **operator** | notes must be real; an empty answer counts as no answer |
| Defer: what blocks it | **operator** | same |
| Approve → merge | deterministic, **after** the answer | `merge_feature.run`; fast-forward only; integration branch only |
| lane move after the decision | deterministic | `plan_store.move` |

**Approve merges only by fast-forward.** A merge commit is a tree that neither
branch was prepped in, so it needs `/commit-prep`, which is a harness skill. The
CLI never stages one. It calls `merge_feature.run(..., ff_only=True)`, which
refuses a non-fast-forward before any conflict probe and checks again at the
moment of merging. So even if the integration branch moves while the operator is
deciding, nothing is staged and the checkout is restored. Either way it stops
with exit 3 and a pending `merge-commit` step that names `/review <slug>`.
A `feature/<slug>` that exists only as a remote-tracking branch also stops with
exit 3 (`local-branch`), because approving would otherwise archive the plan
without merging it. The gate gets the head **shown to the operator**
as `--expect-head`, so if the branch moved after they looked, the merge is
refused. Scope is everything they were shown. `main`/`master` is never a
target: `merge_feature` refuses mainline. A lane move is not committed; the
output prints the plans-only commit command.

### `anchor draft`

| Part | Kind | Why |
|------|------|-----|
| `--list` drafts | deterministic | directory read |
| scaffold `drafts/<slug>` (`--local` for private) | deterministic | a header skeleton; refuses a slug already in use anywhere |
| write the Goal, Steps and Done when | **model** | pending `plan-prose`; `--delegate` asks the planner endpoint, and the reply is written only if it has all three sections |
| `--promote <slug> --to bugs\|features` | deterministic | `plan_store.move` |
| which ready lane, when `--to` is omitted | **operator** | asked interactively; exit 3 headless |

The CLI edits no plan metadata. Priority, assignee and dependencies stay as
their authors wrote them. `--goal` only seeds the skeleton of a new draft.

### `anchor fleet-watch`

| Part | Kind | Why |
|------|------|-----|
| `--status`, `--list`, `--triage` | deterministic | wraps `fleet_watch.py`; fit/lease unchanged |
| `--once` | harness | one `work_once` pull |
| `--emit systemd\|cron` | harness | prints the same unit / crontab text as `fleet_watch.py`; does not write the host |
| `--write-dir` | **operator** | writes unit files into a directory; headless exits 3 and writes nothing |
| `--install-user` | **operator** | writes `~/.config/systemd/user`; headless (including `--yes` without a TTY) exits 3 and writes nothing |

`--worker tier=…,agent=…,interval=5m` defaults to event-driven units (`work_once --watch`, `Type=simple`) plus a oneshot poll timer as heartbeat. `watch=0` restores interval-only oneshot timers.

## Two modes, one code path

| | Interactive | Non-interactive |
|---|---|---|
| Chosen when | stdin **and** stdout are terminals, and nothing below applies | `--non-interactive`, `ANCHOR_NONINTERACTIVE=1`, stdin or stdout not a terminal, stdin closed or uninspectable |
| Prompts | yes, through one prompter | **never**: the prompter raises instead of reading |
| Output | text (or `--json`) | always JSON |
| A step that needs an operator | asks it | exit **3**, naming the answer in `pending` |
| A step that needs a model | runs it with `--delegate`, else lists it in `pending` | lists it in `pending`; `--delegate` and `--run` are ignored with a note |
| Merge | only after Approve, through the gate | **never** (Approve cannot be answered) |

Any doubt about the environment resolves to non-interactive. That direction can
only stop and hand back; it cannot ask or act on a guess. When an agent runs the
CLI, the agent is already the model. So a headless run does not start another
one; it reports the step and the calling agent does it.

## Output contract

Every verb emits one JSON object with `--json`, and always when headless:

```json
{
  "schema_version": 1,
  "verb": "review",
  "action": "review",
  "mode": "non-interactive",
  "exit_code": 3,
  "ok": false,
  "result": {"plan": "review-needed/foo.md", "branch": "feature/foo", "...": "..."},
  "pending": [
    {"step": "critic", "needs": "model", "detail": "..."},
    {"step": "review-decision", "needs": "operator", "detail": "..."}
  ],
  "notes": [],
  "error": null
}
```

`needs` is one of `model`, `operator`, `harness`. `pending` can be non-empty on
exit 0. It then lists the next steps (for example `execute` after a claim);
this run did not stop for them.

| Exit | Meaning |
|------|---------|
| 0 | done |
| 1 | nothing to do (empty list, nothing claimable) |
| 2 | usage or hard error (no `.plans/`, not the lease holder, slug in use, refused merge) |
| 3 | stopped: an operator answer, or a harness-only step, is required. See `pending` |

## Delegation

`--delegate [ENDPOINT]` sends one judgment step through `anchor_client.py` to an
endpoint in `endpoints.yaml` (`--registry`, default `scripts/endpoints.yaml`).
The bare flag takes the first endpoint for the step's role (`critic` for review,
`planner` for draft), using the registry's own `roles:` routing. Model quirks
stay in `anchor_client.py`. Delegation always either happens or says why it
didn't: no registry, no endpoints, no endpoint by that name, a missing
`requests`/`pyyaml`, a failed call, or a headless run. It is never skipped
silently.

## Where plans live: `plan_store`

The CLI and every workflow script reach `.plans/` through `scripts/plan_store.py`.
Callers see lanes, slugs and `rel` strings (`<lane>/<name>`), never a file
extension, a glob, or whether a plan is a file or a directory. Today's layout is
one `<slug>.md` / `<slug>.local.md` file per plan. `tests/test_plan_store.py`
runs the unchanged callers against a second, folder-per-plan layout to show
that a layout change stays inside that module.
