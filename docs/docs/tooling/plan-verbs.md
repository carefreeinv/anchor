---
sidebar_position: 1.5
sidebar_label: Plan workflow verbs
---

<!-- synced-from: anchor/cli.md @ a366e74ea0ad590e2f5b0d8112e2fdb767ceded5 -->

# The plan-workflow CLI: what `anchor` does itself, and what it hands back

`anchor plans | work | review | draft | fleet-watch | models` runs the `.plans/` workflow from a
terminal, with no chat harness. It is a small, deterministic program: every
decision it makes comes from a fixed set of outcomes with a rule you can name,
and it runs no model on list/heartbeat/finish/return. **`anchor work`** picks
the highest-priority ready plan and executes it (`--no-run` claims only).
**`anchor review`** picks the highest-priority `review-needed/` plan and runs
the critic (`--list` still lists). **`anchor draft "a short brief"`** asks the
planner for a full plan under `drafts/` (default `*.local.md`; `--no-delegate`
keeps the skeleton). Survey/merge stays with a human on a TTY.

**Operator loop** (cwd is a project with `.plans/`; `anchor --help` is still the scaffolder):

```bash
anchor plans                         # every lane
anchor work --list --tier mid        # ready + fit; add --endpoint <nick> after `anchor models nick`
anchor work                          # claim top ready plan + orchestrate.py
anchor work --no-run                 # claim only
anchor work --finish <slug>          # in-progress → review-needed/ (or let execute exit 0 park it)
anchor review --list
anchor review                        # critic on the top review-needed/ plan
anchor review --promote              # empty queue: integration → mainline (explicit)
anchor draft "fix leftover worktrees"
anchor models list
anchor fleet-watch --status
```

`--run` is the default for `anchor work` (interactive **and** headless). Exit 0 parks in `review-needed/` unless `--no-finish`. Empty `review-needed/` with integration ahead of mainline: `anchor review` exits 2 and names `anchor review --promote`. `--root` if cwd has no `.plans/`. Skills (`/work`, `/review`, `/draft`) prefer
these verbs when `anchor` answered once this session.

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
`scripts/endpoints.yaml`) and resolve a canonical `name:` **or an overlay
nickname**. A machine-local overlay such as
`~/.config/anchor/endpoints.local.yaml` (or `var/endpoints.local.yaml`) holds
localhost Ollama, NVIDIA Build, and operator nicknames (`aliases`, `machine`,
`effort`). Duplicate names/aliases fail at load (`RegistryConflict`). Two
overlays that both define the same alias also fail. `anchor models nick`
writes only the overlay, never the shared registry. `--effort` on the CLI
still wins over a nickname default. Machine is a label, not a locality
flag. `anchor` loads a gitignored repo-root `.env`
(cwd, then this tree, then the primary git checkout when cwd is a linked
worktree; setdefault) before verbs run; Authorization is the first set of
`ANCHOR_API_KEY`, `NVIDIA_API_KEY`, `NGC_API_KEY`. Named-slug execute (and the `--run` alias) hands the claimed
plan to `orchestrate.py` with the same `--endpoint`/`--registry` used to claim
(omit them to use the default fleet file) and forwards `--worktree` to the
feature worktree (`var/worktrees/<agent-id>/`, never main/master/dev/develop).
That default `Fleet.pick` probes LAN rows
before chat and falls back to NVIDIA Build when the probe is live (see
`platforms/nvidia-build/BUILD.md`). `orchestrate.py --endpoint` is the first
executor try; remaining healthy executor-role endpoints are failover unless
`--no-failover`. Planner/critic stay on the full fleet. Highest listed Preferred
**tier** is a floor: swarm/`small` workers (and execute / `orchestrate.py`) refuse
mid-or-higher plans unless `--no-fit-check` / `--insist`. Preferred `small` alone
is tiny-ok. `orchestrate.py` applies unified diffs or whole-file fences
from the executor reply into `--worktree` before scope/verify. `work_once.py
--once --ensure-worktree` forwards `--worktree`; extra `-- --worktree <dir>`
still works. Footer-only replies do not write files.

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
| carry out the plan's Steps | **model** | default after claim (interactive **and** headless); `--no-run` claims only |

`anchor work` has no merge. Interactive execute that exits 0 (and
`work_once --once` exit 0) moves the plan to `review-needed/` the same way
`--finish` does. `--no-finish` leaves the lease. Exit 2
never finishes. Landing work is `anchor review`'s job (or `/work`'s
culmination question inside a harness).

### `anchor review`

| Part | Kind | Why |
|------|------|-----|
| list `review-needed/` with hold notes | deterministic | directory read + `pending_merges.is_held` |
| the review package: branch, target, head, changed files, fast-forward? | deterministic | git, via `merge_feature` helpers |
| AI critic pass | **model** | bare `anchor review` picks the top `review-needed/` plan and runs the critic (headless too; `--list` lists; `--no-delegate` skips). The package includes `git diff --stat` and `check_docs_sync.py` so the critic does not REVISE for missing logs |
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
target: `merge_feature` refuses mainline. A lane move is committed on the
light path (`git commit -m "Plans: …" -- .plans/`) when `.plans/` is tracked.
Untracked trees (or `*.local.md`) note `lane move (untracked)` and commit
nothing. A merge in progress, or staged paths outside `.plans/`, refuse
without committing.

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

### `anchor models`

| Part | Kind | Why |
|------|------|-----|
| `list` (`--json`) | deterministic | merged registry + overlays: name, aliases, machine, model, effort, tier |
| `nick ALIAS --endpoint NAME [--machine …] [--effort …]` | deterministic | writes `endpoints.local.yaml`; refuses the shared registry |

`anchor work --endpoint lightning --list` is a good-fit list for that row’s tier once the nickname exists.

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

## Command reference

Generated from the parser (`COLUMNS=80 anchor <verb> --help`); `tests/test_anchor_cli.py` fails if this section and `--help` disagree.

### `anchor plans`

```text
usage: anchor plans [-h] [--root ROOT] [--json] [--non-interactive]
                    [--lane LANE] [--board]

options:
  -h, --help         show this help message and exit
  --root ROOT        project root containing .plans/ (default: cwd)
  --json             machine-readable output (schema_version 1)
  --non-interactive  never prompt; JSON output; stop with exit 3 where an
                     answer is needed
  --lane LANE        only this lane (repeatable)
  --board            hand off to plan_board (one frame)
```

### `anchor work`

```text
usage: anchor work [-h] [--root ROOT] [--json] [--non-interactive] [--list]
                   [--agent-id AGENT_ID] [--tier TIER] [--model MODEL]
                   [--effort EFFORT] [--endpoint ENDPOINT]
                   [--registry REGISTRY] [--no-fit-check] [--run] [--no-run]
                   [--no-finish] [--heartbeat SLUG] [--finish SLUG]
                   [--return SLUG]
                   [slug]

positional arguments:
  slug                 claim this plan (default: highest-priority fit)

options:
  -h, --help           show this help message and exit
  --root ROOT          project root containing .plans/ (default: cwd)
  --json               machine-readable output (schema_version 1)
  --non-interactive    never prompt; JSON output; stop with exit 3 where an
                       answer is needed
  --list               ready plans with your fit; claim nothing
  --agent-id AGENT_ID  lease identity (default: anchor-$USER)
  --tier TIER          your fit tier: small|mid|reasoner|frontier
  --model MODEL        your model name, for Preferred-models matching
  --effort EFFORT      current reasoning effort (Grok family maps it to a
                       tier)
  --endpoint ENDPOINT  take model+tier from this registry endpoint
  --registry REGISTRY  endpoints.yaml for --endpoint
  --no-fit-check       ignore Preferred models
  --run                execute after claim (default); kept as an explicit
                       alias
  --no-run             claim only; do not start orchestrate.py
  --no-finish          with --run, leave the plan in in-progress/ even when
                       orchestrate exits 0
  --heartbeat SLUG     extend your lease on SLUG
  --finish SLUG        your in-progress SLUG → review-needed/
  --return SLUG        release your in-progress SLUG back to its ready lane
```

### `anchor review`

```text
usage: anchor review [-h] [--root ROOT] [--json] [--non-interactive] [--list]
                     [--promote] [--delegate [ENDPOINT]] [--no-delegate]
                     [--registry REGISTRY]
                     [slug]

positional arguments:
  slug                  review this plan (default: highest-priority in review-
                        needed/)

options:
  -h, --help            show this help message and exit
  --root ROOT           project root containing .plans/ (default: cwd)
  --json                machine-readable output (schema_version 1)
  --non-interactive     never prompt; JSON output; stop with exit 3 where an
                        answer is needed
  --list                list review-needed plans
  --promote             promote integration → mainline when the review queue
                        is empty
  --delegate [ENDPOINT]
                        send the judgment step to ENDPOINT from the registry
                        (bare flag: first endpoint for the 'critic' role;
                        critic/planner also run headless); alias of the
                        default critic
  --no-delegate         skip the critic chat (package + operator decision
                        only)
  --registry REGISTRY   endpoints.yaml (default: scripts/endpoints.yaml)
```

### `anchor draft`

```text
usage: anchor draft [-h] [--root ROOT] [--json] [--non-interactive] [--list]
                    [--title TITLE] [--goal GOAL] [--local] [--shared]
                    [--promote SLUG] [--to {bugs,features}]
                    [--delegate [ENDPOINT]] [--no-delegate]
                    [--registry REGISTRY]
                    [words ...]

positional arguments:
  words                 brief (spaces ok) or existing slug; kebab slug is
                        derived

options:
  -h, --help            show this help message and exit
  --root ROOT           project root containing .plans/ (default: cwd)
  --json                machine-readable output (schema_version 1)
  --non-interactive     never prompt; JSON output; stop with exit 3 where an
                        answer is needed
  --list                list drafts
  --title TITLE         plan title (default: the slug)
  --goal GOAL           one-paragraph Goal to seed the draft
  --local               private *.local.md (default)
  --shared              tracked drafts/<slug>.md instead of .local.md
  --promote SLUG        move drafts/SLUG to a ready lane
  --to {bugs,features}  with --promote: the ready lane
  --delegate [ENDPOINT]
                        send the judgment step to ENDPOINT from the registry
                        (bare flag: first endpoint for the 'planner' role;
                        critic/planner also run headless); alias of the
                        default critic
  --no-delegate         skip the critic chat (package + operator decision
                        only)
  --registry REGISTRY   endpoints.yaml (default: scripts/endpoints.yaml)
```

### `anchor fleet-watch`

```text
usage: anchor fleet-watch [-h] [--root ROOT] [--json] [--non-interactive]
                          [--project PROJECT] [--status] [--list] [--once]
                          [--triage] [--emit {systemd,cron,both}]
                          [--install-user] [--yes] [--worker SPEC]
                          [--tier TIER] [--agent-id AGENT_ID]
                          [--endpoint ENDPOINT] [--model MODEL]
                          [--registry REGISTRY] [--run] [--load-watcher]
                          [--write-dir WRITE_DIR] [--python PYTHON]

options:
  -h, --help            show this help message and exit
  --root ROOT           project root containing .plans/ (default: cwd)
  --json                machine-readable output (schema_version 1)
  --non-interactive     never prompt; JSON output; stop with exit 3 where an
                        answer is needed
  --project PROJECT     project root (alias of --root)
  --status              inspect .plans/ and installed timers
  --list                work_once --list for this project
  --once                work_once --once (one pull)
  --triage              mechanical take/skip/reject
  --emit {systemd,cron,both}
                        print unit files / crontab lines (does not install)
  --install-user        write systemd user units (interactive operator only)
  --yes                 with --install-user, skip the confirm (still requires
                        a TTY)
  --worker SPEC         tier=mid,agent=id,interval=5m[,watch=0] (repeatable)
  --tier TIER           for --list/--once/--triage
  --agent-id AGENT_ID   for --list/--once/--triage
  --endpoint ENDPOINT   registry endpoint for --list/--once
  --model MODEL         model name for --list/--once
  --registry REGISTRY   endpoints.yaml for --endpoint
  --run                 with --once, execute (omit to pass --no-run to
                        work_once)
  --load-watcher        also emit the inference_load --watch unit
  --write-dir WRITE_DIR
                        write emitted units into this directory (interactive
                        operator only)
  --python PYTHON       interpreter for ExecStart
```

### `anchor models`

```text
usage: anchor models [-h] [--root ROOT] [--json] [--non-interactive]
                     [--endpoint ENDPOINT] [--machine MACHINE]
                     [--effort EFFORT] [--overlay OVERLAY]
                     [--registry REGISTRY] [--list]
                     [{list,nick}] [alias]

positional arguments:
  {list,nick}
  alias                with nick: the short name

options:
  -h, --help           show this help message and exit
  --root ROOT          project root containing .plans/ (default: cwd)
  --json               machine-readable output (schema_version 1)
  --non-interactive    never prompt; JSON output; stop with exit 3 where an
                       answer is needed
  --endpoint ENDPOINT  canonical registry name to nickname
  --machine MACHINE    operator machine label (flippy, rack, …)
  --effort EFFORT      default reasoning effort for this nickname
  --overlay OVERLAY    write nicknames here (default:
                       ~/.config/anchor/endpoints.local.yaml)
  --registry REGISTRY  shared endpoints.yaml to resolve --endpoint
  --list               same as `models list`
```
