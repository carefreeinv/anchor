# Changelog

Notable, user-visible changes to Anchor. Updated by `/commit-prep` before each
commit; format loosely follows [Keep a Changelog](https://keepachangelog.com).
Newest first.

## [Unreleased]

### Added

- **CLI critic thinking-on + confirmation pass.** `delegate()` passes `thinking=True` for critic (short system prompt, no mythos-core). Empty body retries thinking-off. Default two independent critic chats; disagreement takes the more cautious word (UNKNOWN never becomes ACCEPT). `--critic-passes 1` skips the confirmation.

- **`anchor review --approve`.** `--needs-work`, `--skip`, `--defer` consume the survey from the CLI. `--force-approve` is required when the critic is REVISE/UNKNOWN/ESCALATE. No decision flag still exits 3 and does not merge.

### Fixed

- **CLI critic `## Verdict` is a single word.** Last-slice instruct, critic system prompt, and `templates/review.md` require the next line after `## Verdict` to be exactly ACCEPT, REVISE, or ESCALATE; rationale goes under `## Notes` so “do not REVISE …” prose cannot flip an ACCEPT.

- **CI covers `--approve` blocked on critic REVISE.** The test injects a REVISE critic and asserts exit 3 without `--force-approve`; `--force-approve` still archives.

- **`anchor work --finish` sees commits in the plan's git worktree.** Finish-gate `since..HEAD` uses the linked `feature/<slug>` worktree when the primary checkout is still on `dev`/`main`.

## [0.4.0] - 2026-11-10

### Added

- **`anchor release`.** Unmerged-work table vs the release base, suggested next tag, optional plan-diff critic. `--dry-run` never writes git. TTY `--yes` folds CHANGELOG, bumps `pyproject.toml` when present, and creates an annotated tag. TTY `--push` publishes the base and tag without `--force`. Headless `--yes`/`--push` exit 3. Never merges.

- **CLI verbs discover the project from cwd.** `anchor work` / `review` / `draft` / `plans` walk parents of `--root` (default cwd) until they find a `.plans/` tree, so a PATH-installed `anchor` works from a nested directory in another repo. Bare `anchor` with no verb inside such a tree exits 2 and names `anchor work` instead of scaffolding. Explicit `--root` that already contains `.plans/` is unchanged.

- **CLI next-command hints.** `anchor work` / `review` / `draft` print `Run \`anchor …\` to …` on success and failure (same sentence in JSON `pending[].detail`): finish → `anchor review <slug>`; claim-only → `anchor work --finish <slug>`; failed `--run` → `anchor work <slug>`; draft create → `anchor draft --promote <slug>`; promote → `anchor work <slug>`.

- **Per-call model reasoning logs.** `Endpoint.chat` (CLI `--delegate` / `--run`,
  orchestrate, MCP) appends `message.reasoning` / thinking and extracted
  `<think>` blocks to `var/log/reasoning-YYYY-MM-DD.log` before think-strip.
  Returned chat text is unchanged. `ANCHOR_LOG_DIR` relocates; empty dir or
  `ANCHOR_NO_REASONING_LOG=1` disables; `ANCHOR_LOG_PROMPTS=1` includes prompt
  bodies (local debug). Fail-open on write errors. Distinct from
  `var/task-transcripts/` (full executor replies). `var/` remains gitignored.

- **`anchor plans --board` one frame + JSON envelope.** Interactive runs pass `--once` to `plan_board` so the TTY board exits after one draw. `--json` / headless wrap `plan_board`'s dump as `result.board` in the schema-v1 envelope (`verb=plans`, `action=board`).

- **CLI `--run` commit-prep.** After orchestrate exit 0, `work_once` / `anchor work --run` runs tests (and a CHANGELOG nudge when the apply is user-visible), then one product commit on `feature/<slug>` before auto-finish. Prep red stays in `in-progress/` with no commit. `--no-commit` keeps apply-only. Never commits on `main`/`master`/`dev`/`develop`.

- **Default CLI loop.** `anchor work` claims the top ready plan and runs orchestrate (`--no-run` claims only). `anchor review` critics the top `review-needed/` plan (`--list` lists). `anchor draft "brief"` derives a kebab slug and asks the planner (default `*.local.md`). Empty review queue + integration ahead still exits 2 and names `anchor review --promote`.

- **project-orchestrator MCP tools from `anchor_ops`.** List/claim/heartbeat/return/finish/complete/draft/review-prepare share the CLI envelope. Approve/promote/`--delegate` stay unexposed. Legacy `plans_*` names remain.

- **Harness budget ratchet.** `anchor/harness-budget.toml` freezes install
  deps (0), banned modules on `import anchor` (0), generated tokens on the
  default path (0), import-module count, and `--help` / `work --list` walls.
  `python3 scripts/check_harness_budget.py` reproduces each number and fails
  CI with the budget name. Typed decisions: `anchor/cli-decisions.md`.

- **Registry `quirks.timeout`.** `Endpoint.chat` uses it as the HTTP timeout
  when the caller omits `timeout=` (default remains 600s). NVIDIA Build
  overlay does not set a higher default. Aider against Build should use
  `timeout: 900`. Health `GET /models` stays 3s.

- **Empty-finish gate.** `scripts/plan_finish_gate.py` refuses
  `in-progress/` → `review-needed/` when the only commits since the
  integration merge-base are under `.plans/**` or miss the plan Touches.
  `work_once` auto-finish and `anchor work --finish` stay put on fail.
  Operator exception: `## Handoff` line or `ANCHOR_EMPTY_FINISH=1`.

- **Executor Touches file paste.** `orchestrate.py` `execute_task` appends a
  read-only `FILES` block with the current worktree text of paths named in the
  Step Touches cell (or a `Touches:` line), capped per file and dropped
  largest-first when the prompt would exceed `max_context`. Secrets (`.env`,
  keys) and `.plans/**` are omitted. Chat-only executors can emit a unified
  diff or whole-file fence against that text.

- **`anchor models`.** `list` prints registry name, aliases, machine, model,
  effort, and tier. `nick ALIAS --endpoint NAME [--machine …] [--effort …]`
  writes only a machine-local overlay (`~/.config/anchor/endpoints.local.yaml`
  or `--overlay`). `--endpoint lightning` on `work` / `--run` / `--delegate`
  resolves through `Fleet.lookup` (canonical `name:` or overlay alias).
  Duplicate aliases fail at load (`RegistryConflict`). Overlay `effort`
  is the worker default when `--effort` is omitted; the CLI flag still wins.

- **Event-driven plan watchers.** `work_once.py --watch` stays up and pulls on
  `.plans/{bugs,features,in-progress}` inotify events (debounced) with a long
  poll heartbeat when inotify is missing. Optional MQTT poke
  (`ANCHOR_MQTT_PLANS_TOPIC` or `anchor/v1/sites/{site}/plans/poke`) is a no-op
  when unconfigured. `fleet_watch.py` emits `Type=simple` `--watch` units plus a
  oneshot poll timer (`watch=0` restores interval-only). New `scripts/plan_watch.py`
  ships in `FLEET_FILES`.

- **`anchor fleet-watch`.** Status/list/once/emit wrap `fleet_watch.py`;
  `--install-user` is operator-only (headless `--yes` still exits 3 and writes
  nothing).

- **Repo-root `.env` for fleet keys.** `anchor` plan verbs and
  `nvidia_build_probe.py --probe` load a gitignored `.env` with setdefault
  (exported environment wins). `Endpoint.chat` sends `Authorization` from the
  first set of `ANCHOR_API_KEY`, `NVIDIA_API_KEY`, `NGC_API_KEY`. Template:
  `.env.example`.

- **Site inference-load limits over MQTT** — an operator (home-energy automation, lab controller, UPS monitor) publishes one **load level** for a site and every Anchor project honors it before running **local** inference. New **`scripts/inference_load.py`** carries the normative v1 contract: topic `anchor/v1/sites/{site_id}/inference/load` plus an optional per-project override topic that **outranks** it while fresh (mirrored under separate scopes, so a site heartbeat cannot erase a standing override, and a stale override falls through to the site rather than to the fail-safe), a JSON payload whose only required field is `level`, and the level→action matrix `off`→nothing · `low`→`small` · `mid`→`small,mid` · `high`→all fit tiers (aliases `0`–`3`, `full`, `none`; an explicit `allowed_tiers` replaces the row, and `off` denies regardless). **Opt-in and fail-safe by construction:** with nothing configured the resolved policy is `high` from source `disabled` and no worker changes behavior; once configured, `ttl_s` is measured against **local receipt time** — not the publisher's `ts`, so a skewed clock cannot hand out an immortal "full load" — a payload that **omits** `ttl_s` ages out after `ANCHOR_LOAD_MAX_AGE` (default 900s, `0` disables) so freshness is the consumer's guarantee rather than something a publisher can decline, and a missing, stale, or corrupt policy falls back to `ANCHOR_LOAD_FAILSAFE` (`hold`, the default, treats it as `off`; `last_known` keeps the stale level for labs; `unrestricted` opts out). An unknown level is a **parse error**: malformed messages are dropped, never applied, and can never widen the cap. **MQTT is confined to the subscriber** (`--watch`, the only `paho-mqtt` user), which validates and mirrors accepted messages to `.anchor/inference-load.json`; every consumer reads that mirror with the standard library, so a load check adds no dependency, no socket, and no stall to the claim path, a broker outage cannot hang a worker, and CI needs no broker. Writing the mirror by hand (`--set low --reason grid-peak`) or from any other bus runs the whole feature **without MQTT**. Endpoints gained an optional top-level **`local: true|false`** (not a quirk) with `Endpoint.is_local` and a base-URL heuristic behind it (loopback / RFC1918 / CGNAT / link-local / `.local`-style hostnames); every public hostname is **not** local, so a mis-set policy can never silently block a cloud tier. An explicit `local:` value that parses as neither true nor false is treated as **unknown** and falls through to that heuristic rather than as "not local" — a mangled annotation must not be able to switch the governor off — and the PyYAML-less fallback registry parser strips inline comments, so the documented `local: true  # my rack` form is read correctly on a lean install. Consumers: **`work_once.py`** refuses **before claiming** when a local-bound worker's tier is barred and exits idle (`1`) — leaving the backlog untouched rather than parked under a lease nobody is running — with `--local-worker` for tier-only workers and `--ignore-load` as a per-run override; **`fleet_watch.py`** copies the load settings into emitted systemd units and cron lines (**no secrets**: unit files and crontabs are world-readable, so `ANCHOR_MQTT_PASSWORD` is never emitted and `user:pass@` userinfo is stripped from `ANCHOR_MQTT_URL`, which is not used for auth anyway), accepts `local=1` in a `--worker` spec, and shows the current level in `--status`; the **model-fleet MCP** returns a structured `LOAD-LIMITED` refusal from `delegate` / `delegate_parallel_review` instead of sending work (refusing rather than quietly running one of the two independent critic passes), marks local endpoints and the site level in `list_fleet`, and leaves `fleet_health` ungated but labelled — you need to see a box come back before the cap lifts. New **`scripts/mqtt_load_publish.py`** is the operator-side publisher sharing that configuration, with `--retain` (warned when used without `--ttl`), `--dry-run`, `--mirror` (skipped when the publish failed, so a broker outage cannot leave one project on a local-only level), and explicit scope selection — it defaults to the **site** topic even when `ANCHOR_MQTT_PROJECT` is exported, with `--project` / `--topic` to opt into an override and the resolved topic always printed. `max_concurrent_local` is carried and displayed but **advisory**: nothing enforces a concurrency cap, and the docs and `--help` say so. `fleet_watch --load-watcher` emits a supervised `Type=simple` / `Restart=always` unit for the mirror **writer**, without which a configured broker plus a forgotten watcher leaves the fleet capped with no explanation. Freshness edges: a publisher `ts` can only make a message look **older** (so a retained message redelivered on reconnect cannot revive an abandoned level), and `ttl_s: 0` means stale-on-arrival rather than never. `Endpoint.is_local` and `endpoint_is_local` are now one implementation, so `local: "false"` cannot mean different things to `work_once` and the MCP. Both scripts ship to consumer projects via `FLEET_FILES`. Documented at [Site load via MQTT](/tooling/site-load), cross-linked from fleet workers, utility scripts, and the savings page's solar section. Covered by `tests/test_inference_load.py`, `tests/test_mqtt_load_publish.py` (publisher payload → subscriber accept path, no broker), `tests/test_model_fleet_load.py`, and new cases in `tests/test_work_once.py` / `test_fleet_watch.py` / `test_anchor_client.py`

- **`scripts/anchor_ops.py` — transport-neutral operations registry under the CLI.**
  Every `anchor plans|work|review|draft` verb/action is a named handler
  (`plans.list`, `work.claim`, `review.review`, …) with typed params, a
  `mutates` flag, and a `requires` class. `anchor_cli.py` is the terminal
  adapter (parser, prompts, JSON/text). Adapters supply an `Answers` port;
  a headless or future MCP adapter that never answers cannot merge or
  substitute an operator flag. Golden `--json` snapshots pin the envelope.
  Scaffolded with `--fleet` as `.anchor/scripts/anchor_ops.py`.

- **`anchor plans | work | review | draft` — the plan workflow from a terminal.**
  `anchor work --list` / `anchor work [<slug>]` / `--heartbeat` / `--finish` /
  `--return`, `anchor review [--list | <slug>]`, `anchor draft <slug>` /
  `--promote <slug> --to features|bugs`, and `anchor plans [--board]` do the
  deterministic parts (pick, claim, lane moves, the merge gate) by calling
  `plan_select`, `plan_lease`, `work_once` and `merge_feature`, with no model on
  any default path. Headless runs (`--non-interactive`, `ANCHOR_NONINTERACTIVE=1`,
  or no TTY) never prompt, always print schema-v1 JSON, never merge and never
  start a model; a step that needs an operator exits `3` naming the answer.
  `anchor review` merges only after an in-terminal Approve, only by fast-forward
  through `merge_feature.py`'s gate (new `run(..., ff_only=True)` mode, re-checked
  at merge time so a target that moves mid-prompt never leaves a staged merge),
  onto `dev`/`develop`, never `main`. After a delegated critic says REVISE or
  ESCALATE, Approve also needs an explicit "approve despite critic concerns?"
  yes; a remote-only `feature/<slug>` stops instead of archiving unmerged.
  `--delegate [ENDPOINT]` (interactive only) sends a critic pass or plan prose to
  an `endpoints.yaml` endpoint via `anchor_client.py`. Existing
  `anchor <project-dir> [flags]` scaffolding is unchanged; a project directory
  named like a verb is `./work`. Contract: `anchor/cli.md`, docs
  *Tooling → Plan workflow verbs*.

- **`scripts/plan_store.py` — one module for plans on disk.** Every workflow
  script (and the project-orchestrator MCP) now lists lanes, finds slugs, reads
  and moves plans through it instead of globbing `.plans/` itself; callers see
  lanes, slugs and `<lane>/<name>` only. Scaffolded with `--fleet` as
  `.anchor/scripts/plan_store.py`.

- **Shared plan leases on an orphan `leases` branch** (`scripts/lease_branch.py`).
  With a git remote, a claim is published to `leases/<slug>.json` before the plan
  leaves `bugs/`|`features/`, so a plan already leased from another clone is
  refused and `plan_select.py --next` skips it; the fast-forward push is the lock.
  `python scripts/lease_branch.py --status [--json]` lists live leases,
  `--check-isolation` verifies the branch holds only `leases/*.json`, and
  `--compact` (operator only) re-roots its history. No remote or an unreachable
  one falls back to the local lease with a warning; `ANCHOR_LEASE_STRICT=1`
  refuses instead. `*.local.md` plans are not published unless
  `ANCHOR_LEASE_PUBLISH_LOCAL=1`; `ANCHOR_LEASE_BRANCH=0` disables the layer.
  A lease is owned by agent id **plus host**, so same-named agents on different
  machines cannot take or delete each other's claims; a foreign `leases` branch is
  never adopted or overwritten. An expired shared lease on a **ready** plan
  (`bugs/`/`features/`) is reclaimable after clock-skew slack; an expired lease
  on `in-progress/` still needs explicit recover. Push retries treat ref-lock /
  `failed to update ref` as a lost CAS race; hook and protected-branch refusals
  stay unavailable. Scaffolded projects receive the module via `FLEET_FILES`.

- **Agents offer `smky` for reusable browser smoke tests, only when it fits.**
  `anchor/ANCHOR.md` ("Code quality defaults") now tells an agent that is about to
  verify a UI change with a one-off browser probe or throwaway script to ask once,
  in interactive sessions, whether to install [smky](https://carefreeinv.com/smky/)
  instead. It applies only to Playwright projects that want smoke-level coverage
  (no mature Playwright/Cypress suite already in place), shows the exact install
  command, and installs only on an explicit yes. Nothing is scaffolded or
  auto-installed, and unattended runs never ask.

### Changed

- **`/review` uses one critic engine.** When `anchor` is configured this session, `anchor review` is the AI pass. Do not also spawn a Grok/Claude reviewer. Harness `spawn_subagent` is the fallback when the CLI is missing or failed, or when the operator asks for a second opinion. Dual ACCEPT is not a merge gate; the human survey still is.

- **Public docs lead with the CLI loop.** README Quick start, intro, quick-start (technical and non-technical), skill overview, and how-work-reaches-dev name `anchor work` / `anchor review` / `anchor draft "<desc>"` as the daily path; slash skills are the in-harness adapter after one probe. CHANGELOG Unreleased is a single Added/Changed/Fixed stack. That three-verb loop, `--run` commit-prep, and CLI-first docs are the shipped CLI cut; operator `/release` tags after `/review --promote` to `main`.

- **Skills and standing rules match the default CLI loop.** GROK.md rule 13,
  CLAUDE.md prefer-anchor, `/work` `/review` `/draft` skill tables (and
  `.claude/commands` copies), and docs mirrors now name `anchor work`
  (pick+execute; `--no-run` claims), `anchor review` (pick+critic;
  empty+ahead → `anchor review --promote`), and `anchor draft "<desc>"`.
  `work_once.py` is the no-TTY fallback if headless `anchor work` is refused.

- **`work_once --ensure-worktree` reuses a leftover `var/worktrees/` checkout**
  that already has `feature/<slug>`. It no longer exits 2 with a generic git
  checkout error after a successful claim. If the branch is checked out
  outside `var/worktrees/`, the claim returns to the ready lane.

- **Bare `anchor review` with an empty queue.** If integration is ahead of
  mainline, the command exits 2 and tells you to run `anchor review --promote`
  instead of listing nothing. `--list` still lists an empty queue (exit 1).

- **CLI critic pick-order rule.** Every critic slice (not only the last) tells
  the model that `Fleet.executor_candidates` must match `Fleet.pick`: NVIDIA
  Build only when the LAN executor list is empty. An **added** `found = [fb,
  *found]` line in a product `.py` file (not tests, not the critic packaging
  module, not CHANGELOG quotes) is flagged in VERIFICATION as a Done-when
  failure (REVISE).

- **CLI critic runs ops transport tests when ``anchor_ops.py`` changes.**
  `critic_pytest_paths` also schedules `tests/test_anchor_ops_transport.py`
  so a new `@_op` cannot ACCEPT without the never-answers adapter sweep.

- **CLI critic pytest TIMEOUT is evidence, not REVISE.** Last-slice instruct
  REVISEs on pytest exit non-zero only. A 60s cap miss is still printed in
  VERIFICATION so a human/Grok can Needs Work.

- **CLI critic runs pytest on touched tests.** `critic_verification_block`
  executes `pytest` on `tests/` paths in the review range (60s cap) and
  attaches the exit code. Last-slice instruct REVISEs on non-zero pytest
  exit only. TIMEOUT is evidence in VERIFICATION, not a REVISE trigger.
  Docs-sync alone is not enough to ACCEPT.

- **`.env` from the primary git checkout.** `load_dotenv` still prefers cwd then
  this tree; a linked worktree with no copied `.env` also loads the main
  checkout's gitignored `.env` (`git rev-parse --git-common-dir`).

- **Skills prefer CLI after one successful probe.** `/work`, `/review`, and
  `/draft` dispatch list/claim/finish/promote/critic to `anchor` / `work_once`
  when the binary answered this session. Last-known-good wins over redoing
  those ops in chat. Standing rules (Claude + Grok) match.

- **Executor failover after a 0-ok pass.** `orchestrate.py` retries remaining
  healthy executor-role endpoints when the first pass lands 0 ok (NOOP/FORMAT).
  `--endpoint` is the first try and does not pin planner/critic.
  `--no-failover` keeps a single executor. `failed-scope` / `failed-role`
  stop failover. Exhausted roster still exits 2 and skips the critic.
  NVIDIA Build is appended only when no healthy LAN executor remains.

- **GROK standing rules match Claude on CLI ops.** Rule 13 names `anchor
  plans` and the `scripts/work_once.py` exists-fallback. `/fleet-watch`
  prefers `anchor fleet-watch` when the CLI is on PATH.

- **Default execute and default critic.** `work_once.py --once` invokes
  `orchestrate.py` unless `--no-run`. Interactive `anchor review <slug>` runs
  the critic unless `--no-delegate`. `--run` and `--delegate` remain aliases.
  `fleet-watch --once` without `--run` passes `--no-run`. Headless review still
  does not start a model.

- **CLI docs lead with the work loop.** README, Quick Start, the scaffolder
  CLI page, `anchor/cli.md` / Plan workflow verbs, and `/work` skill docs
  name `anchor work --list|--run|--finish`, `models`, and `fleet-watch`
  as the terminal path; slash `/work` stays the harness execute skill.

- **`work_once --run` exit 0 auto-finishes** the claim to `review-needed/`
  (same as `anchor work --finish`). Exit 2 / nonzero leaves the lease.
  `--no-finish` keeps the in-progress hold. Interactive
  `anchor work --run` does the same on exit 0 (`--no-finish` there too).

- **Claude and Grok standing rules prefer `anchor` / `work_once`** for
  deterministic plan ops (list, finish, return, models, fleet-watch).
  `/work` cheaper-capacity dispatch names `anchor work --list` then
  `work_once.py --once --run --ensure-worktree`. Missing `anchor` falls
  back to `python scripts/…` and `/install-anchor`.

- **Shared-lease fetch warnings** collapse SSH/`ssh_askpass` failures to
  `SSH auth failed` and skip the network round-trip when every ready plan is
  `*.local.md`.

- **`anchor work --run` forwards `--endpoint` / `--registry`** into
  `orchestrate.py` (claim identity is the execute identity). Headless `--run`
  still does not start a model; it notes when an endpoint was set.

- **`anchor` verbs commit their own plans-only lane moves** when `.plans/` is
  tracked (`git commit -m "Plans: <slug> → <lane> (anchor …)" -- .plans/`).
  Untracked / `*.local.md` trees note `lane move (untracked)`. A merge in
  progress or staged paths outside `.plans/` refuse without committing.

- **`anchor fleet-watch --emit`** prints the same `### name` / crontab text as
  `fleet_watch.py`. `--write-dir` is operator-only (headless exits 3, writes
  nothing). `--emit cron` prints crontab lines only. `--list` / `--once` /
  `--triage` require `--tier` or `--endpoint`.

- **NVIDIA Build example model** is `nvidia/nemotron-3.5-lightning-30b-a3b`
  (live `/v1/models` + chat, 2026-10-28). The previous catalog id
  `nvidia/llama-3.3-nemotron-super-49b-v1` returns HTTP 410 on
  `integrate.api.nvidia.com`. Self-hosted NIM image names are unchanged.
  Docs note that hosted ids churn.

- **README / Quick Start** name `anchor plans | work | review | draft` as the
  terminal `.plans/` loop (`anchor --help` stays the scaffolder).

- **Two finish workflows for tracked plans.** Human-assisted `/work` still parks
  in `review-needed/` (or merges to `dev` only when the operator answers the
  culmination question). Autonomous / cloud runs (`work_once.py`, fleet,
  coordinator MCP) loop executor → critic until **ACCEPT**, then move the plan
  `in-progress/` → `completed/` **on `feature/<slug>`** and open a pull request
  targeting integration. They still **never merge**. Critic **REVISE** never
  archives and never opens a PR. `/review` remains the human survey for
  `review-needed/` and still does not auto-open a PR. Doctrine, `/work`,
  `/review`, Chat, platform briefs, and
  [How work reaches `dev`](https://carefreeinv.com/anchor/tooling/how-work-reaches-dev)
  describe the split.

### Fixed

- **`critic_verdict` ignores REVISE mentioned in ACCEPT prose.** Negation/meta spans (`do not REVISE`, `against REVISE`, `do not REVISE solely for TIMEOUT`) and a `## Verdict ACCEPT` heading no longer lose to a later mention of the word. A later ATX heading (`### Notes`) ends the verdict section, so a backticked `Verdict: REVISE` example in notes does not override ACCEPT. A later labeled `Verdict: REVISE` in the same section still wins. Mixed “I would REVISE; ACCEPT otherwise” without a heading stays REVISE.

- **Tiny / swarm workers refuse mid-or-higher plans.** Highest listed
  Preferred tier is the floor: `small, mid` is mid work. `classify_fit`,
  `work_once` execute, and `orchestrate.py` refuse before chat (`--no-fit-check`
  / `--insist` override). Unlabeled plans are a mid floor for `small` workers.
  Preferred `small` alone stays swarm-eligible.

- **NOOP retry names whole-file fences.** After `NoApplyableHunks` or an
  unchanged worktree, the executor history line asks for a unified diff or a
  whole-file fence.

- **CLI critic UNKNOWN on duplicated `## Verdict`.** `critic_verdict`
  skips empty `## Verdict` headings and uses the last non-empty section, so
  Lightning's `## Verdict` / `## Verdict ACCEPT` pair is ACCEPT. An empty
  section still stays UNKNOWN when the only ACCEPT is prior-round prose.

- **CLI critic first-pass false REVISE.** `anchor review` attaches a
  VERIFICATION block (`git diff --stat` plus `check_docs_sync.py` when that
  script exists) to every critic slice, and the last slice is told to verdict
  the whole plan. Lightning was REVISEing when logs were missing from the
  prompt or when the last 8k chunk was tests/docs only.

- **`anchor review --delegate` critic budget.** Critic chat uses thinking-off
  and a short critic system prompt (not full mythos-core). Diffs are split on
  `diff --git` boundaries (~8k chars) so NVIDIA Lightning can emit a
  `## Verdict` instead of HTTP 200 / `finish_reason=length` / empty content.

- **`reply_has_applyable` does not raise on overlapping patches.** The probe
  treats `ApplyError` as applyable so orchestrate records APPLY instead of
  traceback exit 1. `extract_patches` still rejects overlap when applying.

- **`anchor models nick` resolves overlay-only endpoints.** Lookup includes
  the target overlay’s existing rows, so a name that lives only in
  `~/.config/anchor/endpoints.local.yaml` can receive an alias without
  `--overlay`. Stolen-alias `RegistryConflict` is unchanged.

- **Interactive `anchor work --run` forwards `--worktree`** to `orchestrate.py`
  (feature worktree under `var/worktrees/<agent-id>/`; never apply on
  main/master/dev/develop). Headless `--run` still does not start a model.

- **`orchestrate.py` skips the critic chat when no executor task is `ok`.**
  Zero-task and all-fail runs still write `orchestration_run.json` with
  `review` set to `critic skipped: 0/N tasks ok` (plus statuses). Mixed
  ok+fail still reviews. `--insist` does not force a critic on an empty
  executor. Exit 2 on 0 ok is unchanged.

- **Executor apply runs even when the Result footer is missing.** A reply
  with a whole-file fence or unified diff is applied before the FORMAT
  retry; prose with neither payload nor footer still FORMAT-retries.

- **`orchestrate.py` exits 2 when no task is `ok`.** All-escalate / all-hold /
  all-failed runs (with ≥1 task) no longer report success after `0/N tasks ok`.
  One `ok` among mixed results still exits 0. `failed-noop` remains 2.

- **Orphan `---` in an executor reply** no longer aborts apply. A whole-file
  fence plus a later prose `---` still writes the fenced file; residual that
  is only orphan `---` stays `NoApplyableHunks`.

- **`--run` escalates before chat** when a task Touches `.plans/**`
  (executor write-deny). `insist` still dispatches. A task that only names
  `scripts/plan_store.py` still chats.

- **`--run` applies executor unified diffs** into `--worktree` before
  scope/verify. `work_once.py --ensure-worktree --run` forwards `--worktree`.
  Footer-only replies still fail closed (`failed-noop`). Parser is stdlib-only
  (`scripts/apply_executor_diff.py`); apply errors fail the attempt. Whole-file
  fences (a markdown fence whose info-string is a path, or `File: path` plus a
  language fence) apply the same way when the model cannot emit `@@` hunks.

- **Orchestrate `failed-noop`.** A well-formed footer plus an already-green
  `--verify` is not `ok` when the worktree is unchanged, or when `## Result` is
  empty / stall phrasing (“will produce after”, “let me examine”). `orchestrate.py`
  retries once then exits 2. Footer is format, not evidence of edits.

- **`Fleet.pick` skips unreachable LAN endpoints** (`GET {base}/models`, ~3s)
  and falls back to NVIDIA Build when `NVIDIA_API_KEY` is live. Dead H100 no
  longer waits on a 600s chat timeout. `ANCHOR_PREFER_LOCAL` /
  `orchestrate.py --prefer-local` skip Build. Super 49B is not selected.

- **`anchor work` claim** light-path commits a tracked `.plans/` move to
  `in-progress/` (`Plans: <slug> → in-progress (anchor work claim)`).

- **`anchor work` error JSON** names the sub-action (`heartbeat` / `finish` /
  `return` / `claim`) instead of repeating the verb.

- **Site load: retained MQTT redelivery no longer resets freshness.** A
  retained payload that matches the mirror keeps the original `received_at`.
  `fleet_watch --load-watcher` enables the watcher `.service` (and `@reboot`
  on cron emit). `ANCHOR_LOAD_MAX_AGE` is copied into emitted units.

- **`anchor work --platform …` names the scaffold form.** A verb plus a
  scaffolder-only flag (or a cwd directory named like the verb, on parse
  failure) prints `did you mean \`anchor ./work …\` to scaffold the
  directory?` and still exits 2.

- **`anchor review --delegate` prints the critic before the decision prompt.**
  Interactive non-JSON runs display `--- critic (endpoint) ---` from the
  operations core (`Ctx.display`) before Approve can merge. Headless runs
  refuse `delegate` / `--run` even if an adapter injected the capability.

- **`anchor review --delegate` no longer treats a template options line or a
  struck-through ACCEPT as the critic verdict.** `critic_verdict` ignores
  `ACCEPT | REVISE | ESCALATE` option lists and `~~strike~~`, then reads only
  the `## Verdict` section (or labeled `Verdict:` lines when there is no
  heading). Of what remains, the most cautious word wins (ESCALATE > REVISE >
  ACCEPT). An empty heading is `UNKNOWN`, so a prior-round `verdict: ACCEPT`
  cannot skip the "despite critic concerns?" gate.

## [0.3.0] - 2026-09-24

### Added

- **`/work --batch` is documented on the published skill page** —
  `docs/docs/skills/work.md` now covers the flag its Claude and Grok surfaces
  already shipped: what `scripts/batch_dispatch.py` selects, that it never
  spawns an agent, that a plan without touch points is excluded, and its real
  flag list. `/review --batch` was already mirrored; `/work --batch` was not.

- **`/review` batch mode** (`--batch [N]`; on by default — see Changed) reviews up to `N` (default 3)
  top-priority `review-needed/` plans in one invocation. Every plan still
  gets its own full pipeline and its own required, never-inferred survey —
  batching removes re-typing `/review` between items, not per-plan sign-off.
  An appropriateness check excludes (falls back to single-item review) a
  `## Handoff` hold note, a large diff (>8 files or ±300 lines net vs
  integration), or two candidates sharing a touched path (the same overlap
  rule `/work --batch`'s `batch_dispatch.py` applies for parallel execution,
  restated in prose so this check is self-contained). Refuses to combine
  with `--skip-ai`; promotion review stays
  single-decision, untouched by batch mode. Documented in both `/review`
  surfaces (Claude + Grok) and `docs/docs/skills/review.md`.

- **`/local-models` confirmed-stack autowire** — `scripts/local_models_autowire.py`
  detects when a project's local model stack is actually confirmed (guest-reachable
  API **and** that API serves the Default-for-wire model, not just "responds") and,
  on operator confirm, writes a machine-local `var/endpoints.local.yaml` overlay,
  the gitignored `.env` (reusing `write_aider_env.py`), an idempotent conventions
  note, and — when `aider` is on `$PATH` — `.aider.conf.yml` plus a portable
  launcher (`hardware/personal-devices/configs/aider-ollama-launcher.sh`).
  Detection never writes; only an explicit yes does. Never installs Ollama or
  pulls weights. Documented in `docs/docs/skills/local-models.md` and both
  `/local-models` surfaces (Claude + Grok).
- **`/work --batch [N]`** — `scripts/batch_dispatch.py` selects up to `N`
  (default 10) ready plans whose `## Likely touch points` don't overlap, then
  claims + creates a dedicated worktree for each (reusing existing
  Priority/Value/fit/Depends-on rules unchanged), so an operator or
  orchestrating session can hand each prepared plan to its own parallel
  executor session. Never spawns an agent itself — selection + preparation
  only. A plan with no touch-point data is excluded from batch selection and
  still runs through ordinary serial `/work`. Documented in
  `docs/docs/tooling/scripts.md`, both `/work` surfaces (Claude + Grok).
- **`## Likely touch points` on plans** — `/draft` now populates an optional,
  advisory-only "Likely touch points" section (file + function/class,
  deduped, whole-plan) right after a plan's header bullets, so an executor
  sees roughly where to look before reading the rest of the plan. Never
  authoritative and never enforced — the per-step Steps `Touches` column and
  a task spec's scope-gate-checked `## Files in scope` are unchanged.
  Documented in `anchor/templates/plan.md`, `.plans/README.md`, both
  `/draft` surfaces (Claude + Grok), and `docs/docs/skills/draft.md`.

- **Release grouping for `.plans/`** — a plan may carry an optional
  `- **Release:** <slug>` header pointing at a `.plans/.releases/<slug>.md`
  file (`Status`/`Target` metadata only, never a member list — membership is
  always computed by scanning plans, so a growing release needs no second
  file edited). New `scripts/release_progress.py` reports per-release
  completion (`--list`, `--status`, `--json`) and orphan `unknown-release`
  references. `plan_select.py`'s ready-lane picker gives a **soft** tiebreak
  to the release closest to complete — strictly within the same
  Priority+Value, never across it. A plan naming a release with no file (a
  typo) sorts **neutrally**, never demoted. `plan_board.py` applies the same
  affinity in its Ready column, so its head is the plan `/work` would actually
  claim (regression-tested against the mtime tiebreak, which can otherwise mask
  a broken bias). `/work` and `/review` (both platform surfaces) ask **once**,
  interactively, when a release's every member plan reaches `completed/`,
  offering to hand off to `/release` — never auto-run. `release_progress.py`
  reads plans without modifying them; the one thing it writes is a release
  file's `Status:`, flipped `ready -> open` when a ready release gains an
  incomplete member (`--no-reconcile` skips that pass). Documented in
  `.plans/README.md` and `docs/docs/tooling/scripts.md`.
- **`aider` platform** — `anchor --platform aider` scaffolds `AIDER.md` (drone
  brief: queen-bee plans, Aider runs `/work` only — no draft/review/merge) and
  a tracked `.aider.conf.yml.example` (`read: AIDER.md`). No slash-command
  runtime is assumed; other Anchor commands point back to a Claude Code/Grok
  Build session. Documented in `docs/docs/platforms/aider.md`.
- **`aider` skills index** — scaffold also writes `platforms/aider/skills-index.md`
  (loaded via the same `read:` list), a roster naming `/work` as the only
  skill Aider runs and every other Anchor command as queen-bee-only, so a
  drone session points the operator back to Claude Code/Grok Build instead of
  guessing at an unimplemented skill.
- **`aider` swarm profile (Qwen3 ≤8B)** — scaffold also writes
  `platforms/aider/work-drone.md` (a ≤1-screen, script-first `work` card:
  claim via `work_once.py`/`plan_fit.py`, execute Steps, finish to
  `review-needed/`, never merge) and `platforms/aider/.aider.conf.swarm.yml.example`
  (thin `read:` = drone card only, `edit-format: diff`, `map-tokens: 1024`,
  `timeout: 60`, `stream: false` — verified live against Aider 0.86.2).
  `skills-index.md` now tells small/swarm models to use the card instead of
  the fuller `AIDER.md` procedure. Also documents, in both files: Aider
  intercepts any message starting with `/` as its own built-in command, so a
  bare `/work` never reaches the model — type `work` with no leading slash.
- **Local drone doctrine + recipe** — `docs/docs/skills/local-models.md` now
  states the queen-bee/drone split (any local model is an executor, never a
  planner) and adds a machine-local drone recipe: a gitignored
  `var/endpoints.local.yaml` entry for this host's reachable local endpoint,
  claimed one-shot with `work_once.py --endpoint … --registry
  var/endpoints.local.yaml` or watched durably with `fleet_watch.py --emit
  systemd --worker …,registry=var/endpoints.local.yaml` — never the shared
  `scripts/endpoints.yaml`. `AIDER.md` and its docs mirror cross-link the same
  recipe as the unattended twin to interactive Aider `/work`.
- **NVIDIA Build inference preference** — `scripts/nvidia_build_probe.py`
  detects whether NVIDIA's hosted Build API (`integrate.api.nvidia.com/v1`,
  keyed via `NVIDIA_API_KEY`/`NGC_API_KEY`) is configured and reachable, and
  computes a preference rule: prefer Build over local inference when live,
  unless the operator explicitly opted for local. Never crashes or falls
  back loudly on a missing/invalid key. Documented at
  `platforms/nvidia-build/BUILD.md`, cross-linked from and distinguished
  clearly against self-hosted NIM (`platforms/nvidia-nim/NEMOTRON.md`).
- **`fit_device.py` Default for wire vs Max fit** — `--probe` reports a
  memory-safer **Default for wire** (Aider / `.env` / launcher) alongside **Max
  fit** (capability ceiling). Uses free/available RAM × safety factor when known;
  WSL/iGPU/≤24GB profiles bias the smallest catalog fit under pressure (LENOVO
  16GB class: 8B max, 4B default). `--emit-endpoint` emits the wire default.
  Documented in `/local-models` and tooling scripts.

- **`aider_repo_map_preflight.py`** — one actionable warning when git HEAD/index
  still lists paths deleted on disk (Aider maps `HEAD`∪index; `git add -u` alone
  does not quiet repo-map floods). Optional confirmed `--write-aiderignore` /
  `--stage` (never auto-commits). Documented in
  `platforms/aider/REPO_MAP_PREFLIGHT.md` (network-lunar `.md`→`.mdx` class) and
  `/local-models`. Shipped via `FLEET_FILES`.

### Fixed

- **`bin/anchor` works when symlinked onto `PATH`** — the install
  `/install-anchor` performs. It resolved `scripts/anchor.py` next to the
  *link*, so a symlinked `anchor` failed with "can't open file"; it now follows
  the link chain first.

- **`pip install -e .` ships every module `anchor` imports.** `anchor --platform
  aider` from a pip install failed on the missing `write_aider_env` /
  `fit_device`; `pyproject.toml` now lists those and the plan-workflow modules
  the verbs wrap (a test checks the list against the real import graph).

- **`check_plans.py` no longer reports `.plans/.releases/*.md` as an "unknown
  lane"** — dot-directories under `.plans/` are sidecars, not lanes.

- **Aider + Ollama guidance no longer tells operators to type `/no_think`** —
  Ollama 0.34.0 and 0.34.2 ignored that suffix when measured, so a session
  following the docs still reasoned on every turn. The docs and the swarm example
  now name the API-level `think: false`, reached from Aider via
  `reasoning_effort: none`. New `platforms/aider/.aider.model.settings.yml.example`
  (scaffolded by `anchor --platform aider`) sets that, with an optional commented
  `num_ctx` (Aider already sizes it per request for Ollama). The Qwen3 canary
  note now states the measured causes of the hang on that host (thinking never
  off, CPU-only serving) instead of "not further isolated", and `map-tokens` /
  `timeout` are marked as GPU-host defaults.

- **`aider_repo_map_preflight.py --stage` no longer leads operators into losing
  renamed files** — it stages the delete side only, so an operator following
  the shipped checklist after a `.md`→`.mdx` migration committed a
  deletion-only change and dropped the new files (git reports the add side as a
  collapsed `?? dir/`, which is easy to miss). The warning block, `--stage`
  help, its success output and `platforms/aider/REPO_MAP_PREFLIGHT.md` now all
  say to stage both sides (`git add -A -- <dir>/`). Also: a repo with **no
  commits** no longer hard-errors with a raw `fatal: Not a valid object name
  HEAD` (an absent HEAD is an empty HEAD set, as Aider itself treats it);
  `.aiderignore` entries starting `#` or `!` or containing `[` are escaped
  rather than silently read as comment/negation/character-class, and the
  written block says to delete it after committing; `--sample 0` no longer
  prints an empty `sample:` header.

- **Shipped files no longer cite private plan slugs** — eleven references to
  `.plans/` working-backlog slugs were removed from the `/work` and
  `/local-models` skill surfaces (both Claude and Grok), `scripts/batch_dispatch.py`,
  `scripts/local_models_autowire.py`, `scripts/plan_board.py`,
  `docs/docs/skills/local-models.md` and the batch-dispatch blog post. Those
  slugs name files this repo never commits, and the skill surfaces and scripts
  are scaffolded verbatim into dependent projects, where the names mean
  nothing — `batch_dispatch.py --help` printed one. Docs that pointed at
  unbuilt `/local-models-config` / `/local-models-ensure` commands now describe
  the shipped behavior instead.
- **Aider's machine-local files are no longer offered for staging** — a project
  scaffolded with `anchor --platform aider` now ignores `.aider.conf.yml`,
  `.aider.model.settings.yml` and Aider's session artifacts
  (`.aider.chat.history.md`, `.aider.input.history`, `.aider.llm.history`,
  `.aider.tags.cache.v*/`). The ignore list has a single definition in
  `scripts/write_aider_env.py`, beside the existing `.env` contract, and is
  ensured on scaffold, backfilled by `anchor <project-dir> --upgrade` for
  projects created before the rules existed, and applied by
  `local_models_autowire.py` before it writes `.aider.conf.yml`. The config
  entries are root-anchored so the `.example` files Anchor ships stay tracked;
  an existing `.aider*` catch-all is treated as coverage rather than stacked on.
  Anchor's own `.gitignore` swaps that catch-all for the root-anchored rules,
  which no longer shadow `platforms/aider/.aider.conf*.yml.example` or a
  generated `.aiderignore`.

- **CI's Lint job is green again** — `ruff check .` had been failing on every
  branch for two unrelated findings, so a red Lint result carried no signal.
  `scripts/fit_device.py` dropped the redundant `socket.timeout` from
  `http_get_ok`'s `except` tuple (since Python 3.10 it *is* `TimeoutError`,
  already listed) along with its now-unused `import socket`, and
  `scripts/batch_dispatch.py` dropped a dead `plan_sort_key` import
  (`inventory_ready` already sorts). No behavior change: the probe still
  returns `False` rather than raising on a refused connection, and batch
  ordering is unchanged.

- **Bare `aider` connection-refused on WSL against host Ollama** — Aider reads
  `OLLAMA_API_BASE` from a repo-root `.env`, but nothing wrote a
  guest-reachable value there, so a plain `aider` invocation failed with
  `OllamaError: … Connection refused` even when the host Ollama was healthy.
  New `scripts/write_aider_env.py` reuses `fit_device.py`'s reachable-`base_url`
  discovery and writes it into a gitignored `.env` (idempotent — refreshes only
  that line after a reboot/gateway change; also ensures `.gitignore` covers
  `.env`). Documented in `docs/docs/skills/local-models.md` and both
  `/local-models` surfaces (Claude + Grok).
- **`AIDER.md`'s `/work` trigger never reached the model** — Aider treats any
  message starting with `/` as one of its own built-in commands and replies
  `Invalid command: work` without ever calling the LLM, so a bare `/work` as
  the brief instructed was silently swallowed by Aider itself, for every
  model size. `AIDER.md` and its docs mirror (`docs/docs/platforms/aider.md`)
  now say to type the word `work`, no leading slash — verified live against
  Aider 0.86.2 (bare `/work` still intercepted, unchanged; `work`/`work --list`
  reaches the model).
- **Empty OpenAI `content` from thinking Qwen3/Ollama** — `Endpoint.chat` no
  longer treats HTTP 200 + empty `message.content` as success when the model
  burned tokens into `reasoning` / hit `finish_reason=length`. Portable fix:
  `min_completion_tokens` floor, one think-off + higher-budget retry, then
  `EmptyAssistantText`. Optional Ollama-only `openai_think` (body `think`) is
  **not** emitted by `fit_device` by default — key presence would 400+retry
  llama.cpp / MLX / vLLM; after a 400 the client caches that the endpoint
  rejects `think`. `platforms/local-models/qwen3.md` documents the pitfall.
- **WSL reachable Ollama/`base_url`** — `fit_device.py --probe` discovers a
  guest-reachable OpenAI API URL (loopback → default gateway → `resolv.conf`
  nameserver) and emits that `base_url` instead of blind `http://localhost:…`
  when Windows Ollama only answers on the host gateway. Refuses
  `--emit-endpoint` dead-localhost stanzas on WSL when nothing answers.
  `/local-models` skills + personal-devices / scripts docs note re-probe after
  reboot and optional mirrored networking.

### Changed

- **Bare `/review` batches by default** (a trial) — with 2+ eligible plans in
  `review-needed/`, `/review` now opens a batch (default `N=3`) instead of one
  plan. Each plan still gets its own fresh-context critic and its own required,
  never-inferred survey; promotion review is never batched, and a named slug,
  `--promote`, `--skip-ai` or fewer than 2 eligible plans run single-item with no
  error. Opt out per run with `--no-batch` (alias `--single`); set it for good with
  `anchor --set-review-batch on|off` (project, in `.anchor/conventions.md`) or
  `./config.sh --review-batch on|off` (machine, `REVIEW_BATCH`). Order: flag, project,
  machine, built-in default (on); `anchor --show-review-batch` prints the effective
  value and its source, and each batch overview names the opt-out. `config.sh` keeps a
  saved `REVIEW_BATCH` when re-run without the flag. Documented in both `/review`
  surfaces, `/config`, and `docs/docs/skills/review.md`.

- **Plans that share a whole-tree gate are written as one plan** — `/draft`
  now says findings under one whole-tree check (`ruff check .`, `mypy .`,
  `tsc --noEmit`, a full `pytest`) belong in a single plan with per-file Steps,
  and the plan template requires every `## Done when` criterion to be satisfiable
  on a green tree. `/commit-prep` Gate 1 names a failure outside the plan's scope
  as still red: stop, report it, and let the operator decide (joint commit,
  recorded in each affected plan's `## Handoff`) — not a waiver.

## [0.2.0] - 2026-08-28

### Added

- **Bidirectional per-prompt model fit (`SUGGEST-DOWNGRADE`)** — mythos-core rule 10 formalizes over-tier work as a first-line `SUGGEST-DOWNGRADE: <cheaper target> — <reason>` (stop unless the operator insists); rule 11 remains upward `SUGGEST-ESCALATE` and, as of the dual-axis work below, also `SUGGEST-REROUTE` for specialty mismatch — all three tokens are now peers in the same fit gate (`orchestrate.py`'s `fit_gate_line`/`_FIT_GATE_PREFIXES`, including after mythos-core rule 13's preflight block). Good fit stays silent. Documented in `model-fitness.md`, `ANCHOR.md`, Claude/Grok/Chat/local-models platforms, and `scripts/anchor.py`'s scaffolded `.anchor/conventions.md` "Model routing" section (was escalate-only, so a freshly scaffolded or `--set-orchestrator` project never taught the downgrade or reroute tokens). `orchestrate.py` honors DOWNGRADE like escalate/re-route (no retry burn; `--insist` overrides). Covered by orchestrate and `plan_conventions` unit tests, including the after-preflight case.
- **`/tag`, `/push`, `/release` skills** — three focused release-workflow skills for both platforms, replacing the idea of a mega-pipeline that versions every branch push. **`/tag`** cuts an annotated tag, detecting the repo's existing scheme instead of inventing one (`--suggest` proposes the next version), refuses a dirty tree or an existing tag, and never pushes. **`/push`** pushes the current branch with the ceremony a shared branch deserves — confirms remote and branch, names the protected-branch risk, accepts **only** `--force-with-lease` and only when explicitly asked, never a bare `--force`, and never creates tags. **`/release`** is the intentional ship: it reports finished work that is *not* on the release base (classified by plan lane, so a branch sitting in `review-needed/` — the normal end state of agent work — is called out rather than silently omitted), plan–diff reviews what *is* on the base, then tags and pushes. **`/release` never merges**: branches reach `dev` through `/review` Approve or a `/work` scoped merge, and `main` only through `/review`'s promotion survey, so the release path is not a third route onto an integration branch. A HOLD finding gates the **tag**, which is the hard thing to retract. All three are scaffolded to consumer projects and carry the same `scripts/` → `.anchor/scripts/` substitution note the other dual-use skills use. Documented at [/skills/tag](/skills/tag), [/skills/push](/skills/push), [/skills/release](/skills/release)
- **Result-only return contract: only the structured footer crosses the executor→orchestrator boundary** — mythos-core rule 8's `## Result` / `## How to verify` / `## Deferred / concerns` is now the sole channel back into the coordinator's context; an executor's reasoning, false starts, and quoted templates never reach it. New `fleet_metrics.extract_footer(text, max_lines=60)` is a pure, tolerant parser (case/spacing drift, last-occurrence-wins when a model quotes the template while reasoning) requiring all three sections — missing any is a named rejection, never a partial accept — and caps the reconstructed footer so a full transcript can't be smuggled inside `## Result`. `scripts/orchestrate.py`'s `execute_task` now archives every dispatch's full raw reply to `var/task-transcripts/<task-hash>.log` (metadata header + output, appended across attempts) before relaying anything. The retry gate itself now requires `extract_footer(out).ok` — all three sections present, not the older two-section check — so a reply missing any required section, not just one with no footer at all, gets the pre-existing one-retry-then-escalate treatment (mythos-core rule 6/8) before it can reach the coordinator; a `status: ok` reply's `output` is therefore always the extracted footer via `relay_text(out)`, never a raw-capped fallback. That fallback branch of `relay_text` still exists for the claimed-vs-actual ledger's audit record on an exhausted-retries escalation. New `--transcripts` CLI flag mirrors `--metrics-ledger`'s default/disable pattern. `var/task-transcripts/` is rotated manually, same as the fleet metrics ledger — nothing here does it automatically. `anchor/ANCHOR.md`'s orchestrator-pattern section and the `docs/docs/doctrine.md` "Forced structure" bullet now describe the relay; mythos-core rule 8 gets a one-line cross-ref (no renumbering). Covered by new tests in `test_fleet_metrics.py` (`extract_footer`: clean, sloppy-case, missing-section, duplicate-heading, oversize) and `tests/test_footer_relay.py` (coordinator sees footer only, transcript file exists and accumulates across retries, malformed output gets exactly one retry)
- **Harness-enforced stop conditions** — mythos-core rule 6 ("two failed attempts → stop") is now mirrored harness-side instead of depending on a flailing model to count its own attempts. New `fleet_metrics.should_stop(task_id, model, ledger, tier=…)` is a pure function over the persistent `var/fleet-metrics/outcomes.jsonl` ledger: counting is per (task, model), a scope-gate rejection counts as a failure (it is one — rule 7), and a handoff never counts (it never reaches the ledger in the first place). `scripts/orchestrate.py`'s `execute_task` consults it before every (re)dispatch — two recorded failures at a tier refuse a third dispatch to that model and escalate to the next rung of the fleet's actually-configured tiers (`available_fit_tiers`/`pick_escalation_endpoint`), with both failures' evidence attached to the escalated spec's prompt; two failures already at the top available tier produce a structured `render_human_report` (tried / observed / hypothesis / what a stronger model or human should look at, honest that the ledger is metadata-only so it has no diagnosis to offer) that `main()` writes to `var/human-reports/` even when the model never wrote one. Because failures are only persisted on a task's *final* attempt, this backstop is invisible within one continuous run and only bites on a resumed/re-invoked task — exactly the case a model's own in-memory attempt count can't cover. `anchor/ANCHOR.md`'s Escalation-paths bullet, mythos-core rule 6, and the `docs/docs/doctrine.md` mirror now cross-reference the mechanism (no renumbering). Covered by new tests in `test_fleet_metrics.py` and `test_orchestrate_metrics.py`/`test_orchestrate.py` (including a `main()`-level fixture that asserts the report file actually lands on disk)

- **Grok 4.6 fitness row** and effort→tier table in model-fitness (4.5 row retained as prior gen).

- **Deferred fleet catalogs — the registry gets right-sized too** — a coordinator/planner role, or an executor task that is itself about routing, used to have no way to see what the fleet offers without either hand-reading `scripts/endpoints.yaml` or the model-fleet MCP's `list_fleet` pasting every endpoint's `base_url` and model name into context. New `router.summarize_endpoints(fleet)` generates a capped one-line-per-endpoint summary (name, tier, context size, one capability phrase derived from the endpoint's own quirks — no `base_url`, model name, or quirk values, so nothing that could leak infrastructure ships by default) and `router.fleet_summary_block(fleet)` wraps it for splicing into a prompt. `orchestrate.py`'s planner phase injects that summary — it picks `Route to` targets and needs fleet awareness — and `prompt_tuner.py` injects it into a generated task spec's `## Provided context` only when the rough task is itself routing-related (mentions an endpoint, tier, escalation, dispatch, …); an ordinary implementation task never sees it. Full endpoint detail (base_url, model, quirks) is now a deliberate, on-demand `router.endpoint_detail(fleet, name)` call — the model-fleet MCP's `list_fleet` tool switched to the summary, and a new `lookup_endpoint(name)` tool returns full non-secret detail for one endpoint by name. `ANCHOR_API_KEY` was already an environment read at request time rather than a registry field, and stays that way — nothing here changes where secrets live. Covered by new tests in `test_router.py`, `test_prompt_tuner.py`, `test_orchestrate.py` (asserting the raw registry never reaches a generated prompt), and `test_model_fleet_server.py` (a fixture-registry round-trip through `list_fleet`/`lookup_endpoint`). `anchor/ANCHOR.md`'s right-size section and its `docs/docs/doctrine.md` mirror, `mcp/model-fleet/README.md`, and `docs/docs/tooling/{mcp-servers,scripts}.md` updated
- **Mechanical (no-LLM) plan triage** — daemons and fleet workers can now answer accept/skip/reject for a plan without a model in the loop. New `scripts/plan_parse.py` provides the shared primitives: `strip_code_fences()` blanks fenced code block bodies before any header regex runs, so a plan quoting an example header inside a fence (a doc walkthrough, `anchor/templates/plan.md` itself) can never be mistaken for the file's own field — a real gap in the prior whole-file-regex approach; `safe_read_text()` never raises, so one corrupt/unreadable `.local.md` can no longer crash a daemon's polling loop; `triage_plan()` is the three-way verdict — **reject** (unreadable, missing `## Goal`, human Assignee, unmet deps, underqualified — never eligible for this worker), **skip** (overqualified, or leased by another agent — eligible for someone else), **take** (good/unknown fit, deps met, agent-assignable). A maintained CommonMark library was considered and deliberately not added: `scripts/` ships standalone into every consumer project, so a fence-aware line scan gets the real robustness win without one more dependency to install everywhere. `plan_select.py`'s `_record_from_path` (the hot path `inventory_ready`/`inventory_in_progress` share) now goes through `safe_read_text` + `strip_code_fences` and carries two new `PlanRecord` fields, `parse_error` and `has_goal` — additive, defaulting to `None`/`True`, so existing callers are unaffected. `plan_fit.py`'s existing take/skip CLI output is unchanged; the new reject distinction is additive. New `work_once.py --triage` (mirrored as `fleet_watch.py --triage`) prints one `take:`/`skip:`/`reject:` line per ready + own-in-progress plan, never claims/moves/dispatches, and never opens a network connection. Covered by `tests/test_plan_parse.py` (23 tests, including `tests/fixtures/plans/` fixtures for underqualified/overqualified/human-assignee/unmet-deps/missing-goal/unknown-preferred/a fenced-example-header case), plus new integration tests in `test_plan_select.py`, `test_work_once.py`, and `test_fleet_watch.py`. `scripts/plan_parse.py` added to `FLEET_FILES`. Documented at `/tooling/scripts` and `/tooling/fleet-workers`

- **Dual-axis model fit (power + specialty)** — mythos-core rule 11 now requires both a **power** gate (`SUGGEST-ESCALATE` for weak-column / orchestration) and a **specialty** gate (`SUGGEST-REROUTE: <target or profile> — <reason>` when power is OK but the product shape is wrong — e.g. general-chat or swarm-local leaving multi-file software for `coding-agent`). The token argument is always the **destination**. Closed profile tags: `coding-agent`, `terminal-agent`, `critic`, `planner`, `general-chat`, `multimodal`, `swarm-local`. Documented in `anchor/model-fitness.md` (profile column on every catalog row), plan template Preferred models, Claude/Grok/Chat/local-models platform standing rules, and `/work` skills. `scripts/orchestrate.py` treats `SUGGEST-REROUTE` like escalate (no retry burn; `--insist` overrides), including when mythos-core rule 13's six-line preflight precedes the token. `plan_select` ignores specialty tags for power fit; optional `plan_fit.py --profile` / JSON `specialty_hint` is soft only. Docs: `/model-fitness`, `/doctrine`, `/skills/work`, `/platforms/local-models`.

- **`scripts/plan_board.py --json`** — machine-readable kanban dump (`schema_version: 1`) with the same columns, membership, and Priority → Value → mtime sort as the terminal board: per-plan slug/rel/lane/title/priority/value/preferred/depends_on/assignee/path, optional log `last_event`, and the 7-day Completed/Processed throughput block. Single-frame (auto-once); `--include-parked` adds Ambiguous/Blocked. Stdlib-only and read-only — for CI, dashboards, and other projects that should not import Anchor internals or talk MCP. Documented in `docs/docs/tooling/scripts.md` and the kanban blog post
- **Structured handoff + planned continuations for tasks that outgrow one context window** — an executor approaching its declared `## Budget` ceiling now emits a **handoff artifact** instead of a truncated answer, and the orchestrator respawns a **fresh** context seeded with it. New template `anchor/templates/handoff.md` (`## Done` with per-item verification status · `## Remaining` as ready-to-dispatch sub-specs · `## Decisions made` · `## Files touched` · `## Open concerns`) and new module **`scripts/handoff.py`** (`looks_like_handoff` structural detection, strict `parse_handoff`, `check_scope_shrinks`, `accumulate`, `build_continuation`). In `scripts/orchestrate.py`: token accounting attaches a **budget notice** to any dispatch at ≥80% of the picked endpoint's `max_context` (`HANDOFF_THRESHOLD`) telling the executor to hand off rather than start work it cannot finish; a handoff reply is recognized **before** the output-footer gate (a handoff has no `## Result` footer by design) so it is never retried as a format error; each continuation restates the original task, carries accumulated done items and decisions forward as do-not-redo/do-not-reverse, and dispatches only the remaining sub-specs. Guardrails: remaining work with no `Verify by:` line is rejected with one corrective retry then escalates (an undispatchable "finish the rest" item is what makes continuations fail); a continuation whose scope **grew** beyond the original spec's `## Files in scope` is refused and routed back to the planner; and the cap is **2 respawns** per task (`--max-respawns`, `0` disables) — past it the task is reported as a decomposition error rather than respawned again. Landed as **mythos-core rule 15** (hand off, never truncate) with matching doctrine in `anchor/ANCHOR.md`; documented at `/doctrine` and `/tooling/scripts`. The template ships to consumer projects via `CORE_FILES` — mythos-core rule 15 is scaffolded, so the file it mandates must be too — and `scripts/handoff.py` ships via `FLEET_FILES`. Covered by `tests/test_handoff.py` (the shipped template is itself the round-trip fixture) and new `tests/test_orchestrate.py` cases, including a handoff→continuation run whose verify command actually executes and passes
- **`/work` culminates in a handoff choice — review, scoped merge, or hold** — an interactive `/work` that finishes a plan on green `/commit-prep` gates now asks **once** what should happen to it: **1. Review it now** (default — plan → `review-needed/`, hand off to `/review`), **2. Merge to `dev` now** (scoped-merge gate → merge → plan → `completed/` with a `## Handoff` note recording the skipped review), or **3. Hold for testing** (plan → `review-needed/` with a `## Handoff` hold note; branch and worktree left intact). The question is skipped entirely on red gates, no-op plans, non-Git projects, and every **non-interactive** path — `work_once.py`, fleet workers, and the coordinator MCP never ask and never merge, and finish to `review-needed/` exactly as before. New **`scripts/merge_feature.py`** implements the gate: a pure `evaluate_gate(...)` (**provenance** — the branch head is the commit this run made; **clean tree**; **file scope** via `scope_gate.check_scope` against the run's declared touched set; **mergeability**, fast-forward preferred; and **target resolution that aborts on `main`/`master`**) plus a thin git shell mirroring `/review` §11's merge semantics so the two authorization paths cannot drift. The gate refuses rather than assuming: an **empty touched set** is a refusal (not "scope check inactive"), `--expect-head` is **required** (provenance is must-hold, not opt-in), `--base` must be an ancestor of both the branch head and the natural merge-base (a base inside the range would hide commits from the scope check), the diff is taken with `--no-renames` (so a rename's deleted source cannot vanish from view), `--target` is resolved through git and accepted only when it names an integration branch, and a target already checked out in another worktree is reported up front instead of failing mid-merge (after the content checks, so a scope violation is never masked by "run this somewhere else"). The **clean-tree check follows the feature branch's worktree**, not `--root` — the two are different directories on the topology the tool itself recommends, and checking the wrong one would make the guarantee false by default. CLI `--root --slug --touched <file|-> --base --expect-head --target --dry-run`, exiting `0` merged/would-merge · `3` scope violation (naming the path) · `4` precondition · `5` conflict · `2` git error; it never pushes, force-updates, or deletes a branch. Deliberately **no** `--yes`/`--confirmed` flag — the human answer is the one check a flag could fake, so it stays in the skill. Any gate failure falls back to `/review`; partial path-scoped landing is rejected outright (it fabricates a commit matching no branch state and hides the out-of-scope change). Covered by `tests/test_merge_feature.py`
- **`pending_merges.py` shows where unmerged work physically sits** — each row gains `worktree` (joined from `git worktree list --porcelain`, falling back to `var/worktrees/registry.json` and labeling those rows **stale registry**, since git is the authority), `dirty` (uncommitted changes in that worktree), `plan_lane` (the lane currently holding the plan, not just `completed/`), and `held` (the plan body carries a `## Handoff` hold note). Scripts a scaffolded skill tells consumer agents to run — `merge_feature.py`, `pending_merges.py`, `plan_fit.py`, and their `scope_gate`/`roles` dependencies — are now in `FLEET_FILES` so they actually reach consumer projects, with a **guard test** asserting that every `scripts/*.py` named by a scaffolded skill is shipped (nine were silently orphaned; the scaffolder itself is an explicit, documented exception). New `--brief` prints exactly one line — `handoff: N branch(es) ahead of dev · M completed awaiting merge · K held` — for the tail of another command's output, and `--worktrees/--no-worktrees` (default on) toggles the join. `--json` is **additive**: every pre-existing field is unchanged
- **`/commit-prep` closes with a handoff section** — after its three gates it prints what is committed but **not yet on `dev`** (via `pending_merges.py`, falling back to `git branch --no-merged dev` for projects without Anchor scripts) plus the ladder `feature/<slug>` → (`/review` Approve | `/work` scoped merge) → `dev` → (`/review` Promote) → `main`. Explicitly **not a fourth gate**: unmerged branches are the normal state of a healthy repo, never make prep red, and `/commit-prep` still commits nothing
- **New docs page [How work reaches `dev`](/tooling/how-work-reaches-dev)** — the two routes onto integration side by side, the six gate conditions, and how to see what has not landed
- **`/optimize` skill** — scans a project against **known/emerging/popular standards for its detected type** (web app: OG/Twitter cards, `robots.txt`, `sitemap.xml`, `llms.txt`, favicon set, structured data; CLI/library: `CODEOWNERS`, `SECURITY.md`, `CONTRIBUTING.md`, release config, `.editorconfig`; docs site: `llms.txt`/`llms-full.txt`, search config; any repo: dependency-update bot, `LICENSE`, `CHANGELOG`, issue/PR templates), then proposes **up to 10** ranked improvement candidates (impact/effort → Priority map) and writes only **checkbox-picked** candidates as `.plans` files. Project-type detection gates the checklist first so a pure CLI tool never gets web-only suggestions or vice versa; a baseline checklist keeps runs reproducible, with a `(emerging — verify still current)` tag for anything proposed beyond it. Unlike `/audit`, there is **no** frontier/reasoner refuse gate — `mid, reasoner` is a soft preference only. Default write lane is `.plans/drafts/opt-<kebab>.local.md` (sticky `.local`); `--to features`/`--to bugs` opts in to a ready lane using the same bug-vs-feature inference as `/draft --promote`. `--dry-run`, `--write`, `--continue` for a deferred backlog past the cap. Scaffolded for Claude (`.claude/commands/optimize.md`) and Grok (`.grok/skills/optimize/SKILL.md`), registered in `scripts/anchor.py` so `bin/anchor <project>` and `--check` reconcile install it into every dependent project, not just this repo; docs at `/skills/optimize`; listed in skills overview, quick start, and platform briefs (`CLAUDE.md` / `GROK.md`)
- **`## Progress` checklist convention for `.plans` files** — the plan template (`anchor/templates/plan.md`) now includes an optional `## Progress` section, placed right after the header bullets: one `- [ ] Step N: <label>` bullet per Steps-table row plus a trailing `- [ ] Done when holds` bullet, populated **last** by `/draft` (after Steps and Done when are drafted) with everything starting unchecked. `/work` keeps it in sync during execution — checks off a Step bullet once that step's Verify by passes, checks off `Done when holds` before the `review-needed/` move, and leaves bullets untouched on a mid-plan pause; "resume from the first incomplete step" now concretely means the first unchecked bullet. Advisory only — never parsed or enforced by any tooling, and fully optional on the existing backlog (no retrofit). Most valuable for a human-assigned plan (`- **Assignee:** human`) worked over multiple sessions, where nothing previously showed step-level progress in between. Claude (`.claude/commands/{draft,work}.md`) and Grok (`.grok/skills/{draft,work}/SKILL.md`) both updated; docs at `/skills/draft` and `/skills/work`; `.plans/README.md` documents the shape
- **`/deploy` skill** — ships an Anchor-dependent project with **the deployment tooling that project already uses**, detected before anything is built: a project entrypoint (`make deploy` / `npm run deploy` / `scripts/deploy*`), CI push-to-deploy (GitHub Actions / GitLab / Jenkins — where `git push` *is* the deploy, then `gh run watch`), a platform CLI (`vercel.json`, `netlify.toml`, `fly.toml`, `.do/app.yaml`, `wrangler.toml`, `serverless.yml`, `Procfile`), a release framework (**Deployer** `deploy.php`, Capistrano, **Kamal**, Fabric, Ansible, Shipit, goreleaser, Helm/kubectl), package publication (twine/npm/cargo), or a plain `production` git remote. When **nothing** is detected it stops and asks where the project should deploy (GitHub Pages · Vercel · Netlify · Cloudflare · DigitalOcean · Fly · AWS · GoDaddy/shared hosting · VPS over SSH · a registry), who runs it (CI or human), and which environments — then sets up the framework that fits the stack, with **Deployer's release model as the bar for every SSH-style target in any language** (timestamped `releases/`, symlinked shared dirs, atomic `current` flip, keep N, one-command rollback). Guardrails: dirty tree refused (`--allow-dirty` overrides), target + branch + SHA printed and confirmed before the first remote command (production prints a risk line even under `--yes`), never commits/merges/promotes/force-pushes, no `terraform destroy` / dropped databases / `--force` deploy flags, secrets referenced by **name** only, and the deploy is **verified** (URL status / release SHA / platform status) before it is called done. `--dry-run`, `--status`, `--setup` (writes config + dry run, then stops), `--target <host>`, `--rollback` via the tool's native path. Scaffolded for Claude (`.claude/commands/deploy.md`) and Grok (`.grok/skills/deploy/SKILL.md`); docs at `/skills/deploy`; listed in skills overview, quick start, and platform briefs (`CLAUDE.md` / `GROK.md`)
- **`/audit` skill** — exhaustive security audit of first-party code **and** dependencies that writes prioritized bug-fix plans under `.plans/bugs/` (or `--to drafts`). **Frontier/reasoner only** by default (`--force-model` override); each emitted plan carries `Preferred models: frontier, reasoner` (or `frontier` alone for critical) and `Priority` from a severity map (P1–P3). Confirm-before-write, `--dry-run`, 25-plan cap, sticky `.local.md` basenames, no exploit PoCs / no auto-fix. Scaffolded for Claude (`.claude/commands/audit.md`) and Grok (`.grok/skills/audit/SKILL.md`); docs at `/skills/audit`; listed in skills overview and platform briefs (`CLAUDE.md` / `GROK.md`)
- **"Surface the best-fit skill" doctrine** — agents now proactively suggest an *available* skill or slash-command when one would do the current request faster or more correctly, so operators discover cutting-edge features through the work they're already doing instead of having to know the `/command` exists first. Landed as **mythos-core rule 14** (`anchor/system-prompts/mythos-core.md`) with a matching anti-pattern, mirrored as a standing rule in `platforms/claude-code/CLAUDE.md` and hard rule 13 in `platforms/grok-build/GROK.md`, and documented at `/doctrine`. Guardrails keep it from becoming noise: **available-only** (never name a command that isn't loaded, never invent a feature), **at most once per capability per session**, and only when the concrete efficiency win can be named — it is a one-line *suggestion*, never a gate, and the agent proceeds with the request the same turn. Explicitly *not* a 7th pre-flight item; rule 13's block stays six lines
- **`scripts/plan_board.py`** — standalone, zero-dependency, read-only terminal kanban board for a scaffolded project's `.plans/`: **Drafts | Ready | In Progress | Review Needed | Completed**, each sorted by the same Priority → Value → mtime order `/work` uses; header shows rolling 7-day **Completed**/**Processed** (into `review-needed/`) throughput counters, preferring `.plans/logs/*.csv` event files when present and falling back to git-commit-time/mtime (immune to fresh-clone mtime resets) otherwise; each card shows a brief label for its most recent logged event, if any (unrecognized event strings degrade to a safe title-cased label rather than erroring). Auto-refreshes every 60s (`--interval` to override) with an animated highlight when a card changes column between polls; `--once` for a single frame (piping/CI), `--include-parked` to also show `ambiguous/`/`blocked/`, `--no-color` (also auto-disabled on non-TTY output). Column color accents (green/yellow/orange/red) are supplementary only — column names stay the authoritative signal. Registered in `FLEET_FILES` (`scripts/anchor.py`) for scaffolding into consumer projects; documented in `.plans/README.md` and `docs/docs/tooling/scripts.md`
- **`/review` skill** — human sign-off for `.plans/review-needed/`: pick **one** plan per invocation, check out `feature/<slug>` when safe, optional low-risk local launch, fresh-context **AI critic** (`templates/review.md`), then a survey (**Approve** / **Needs Work** / **Skip**) with follow-ups. Approve → `completed/`; Needs Work → `bugs/` or `features/` (same inference as `/draft --promote`, never `in-progress/`). Scaffolded for Claude (`.claude/commands/review.md`) and Grok (`.grok/skills/review/SKILL.md`); docs at `/skills/review`; cross-linked from `/work` and `.plans/README.md`
- **`scripts/plan_fit.py` — read-only "which ready plans should I take?" triage** — one command answers fit for a whole backlog so a model never judges it by reading plan headers. Identify the worker with `--tier` / `--model` / `--endpoint` (resolved from `endpoints.yaml`), optionally `--effort`; it prints one `take:`/`skip:` line per ready plan with the reason (`underqualified`, `overqualified`, `deps UNMET`, `assigned to <who>`), plus an effort note when the reasoning dial is wrong for that plan's tier. `--json`, `--eligible-only`, `--next` (path only, for scripts/cron guards); exit `0` eligible / `1` nothing / `2` error. It never claims or moves anything — pair with `plan_select.py --next --claim`. Backed by a new **effort model** in `plan_select.py` (`classify_effort` / `TIER_EFFORT`, the `/work` cost-right-size table as data, with `off`/`max`/`med` synonyms) whose load-bearing invariant is tested: effort is a cost dial, never a tier promotion — no `--effort` value changes which plans are eligible. Wired into both `/work` skills and documented on the scripts / fleet-workers pages
- **`/tag` skill** — detects a repo's existing git version-tag scheme (`v`-prefixed semver, bare semver, calver, or an unrecognized pattern it asks about rather than guessing) and never invents a second scheme once one is in use. `/tag` / `--status` shows the latest tag and suggests the next version (patch by default, `--suggest minor|major` for other bumps, cross-checked against a package manifest version when present); `/tag vX.Y.Z` / `--create` creates a **local annotated tag only** after confirming — refuses a dirty tree (`--allow-dirty` overrides, with a printed risk line) and refuses to move/force an existing tag name. Never pushes a tag or branch, and is not a release: deciding what merges before a version ships stays a separate, more deliberate step. Scaffolded for Claude (`.claude/commands/tag.md`) and Grok (`.grok/skills/tag/SKILL.md`), registered in `scripts/anchor.py` so `bin/anchor <project>` installs it into every dependent project; docs at `/skills/tag`; listed in skills overview
- **`/push` skill** — publishes the **current branch only**: confirms the exact remote/branch before running anything, `git push -u` by default, `--tags` pushes tags already reachable from `HEAD` (after a separate confirm listing which ones — never creates a tag itself), `--prep` runs `/commit-prep` first and stops if red. Never force-pushes unless the user has explicitly asked for it in the conversation; a push to `main`/`master`/`dev`/`develop` prints a risk line and requires confirmation even under an otherwise non-interactive flow. Never merges. Scaffolded for Claude (`.claude/commands/push.md`) and Grok (`.grok/skills/push/SKILL.md`); docs at `/skills/push`; listed in skills overview
- **Human-owned plans via an optional `Assignee` header** — a plan can carry `- **Assignee:** <name | username | email>` (or `human`) to mark work a **person** must complete; agents auto-skip claiming it across `/work`, `scripts/plan_fit.py`, `scripts/work_once.py`, and the project-orchestrator MCP `plans_claim`, regardless of model fit. The field defaults to **ai** — absent, `ai`, `agent`, or `unassigned` stays agent-eligible exactly as before — and a trailing note survives the parse (`alice@corp.com — owns the migration`). Agents may still **read** an assigned plan and **edit its body** (status/comments) and commit that; only claiming/completing it is reserved. `work_once.py --allow-assigned` forces a named claim when an operator wants an agent to take it. Parsing/gating live in `plan_select.py` (`parse_assignee`, `is_agent_assignable`, `PlanRecord.assignee`/`agent_assignable`, new list-table column); documented in the plan template, `.plans/` README, `/work` + `/draft` skills, and docs. Covered across `test_plan_select.py`, `test_plan_fit.py`, `test_work_once.py`, `test_project_orchestrator.py`

### Changed

- **`/local-models` is dual-use** (Anchor base **and** scaffolded projects) — source of truth is `.grok/skills/local-models/SKILL.md` / `.claude/commands/local-models.md` (scaffolded like `/work`, not only from `platforms/…`). From the Anchor checkout it can guide **operator defaults** (`config.sh` / `/config`) and this host’s fleet wiring; from a project it still offers a reconfigure draft. **Multi-machine clones:** probe is always **this host**; never commit localhost fit as project-wide law; prefer machine-local writes (`~/.config/anchor`, gitignored overlays, `.local.md` drafts) and portable “local when reachable” conventions. `scripts/anchor.py` scaffolds from base paths and remaps legacy manifest `src` values that still point at `platforms/…/local-models`. Docs and platform briefs updated.

- **Grok dual-product cost ladder** — doctrine prefers **Grok 4.5** for lighter/cheaper mid work and **Grok 4.6** for heavier multi-step agent tasks while both exist; model-priority examples use `grok:4.5` before `grok:4.6`. Effort map unchanged (medium/high→reasoner, xhigh→frontier).

- **Grok 4.6 + effort as effective Preferred tier (Grok family only; medium/high→reasoner)** — catalog base tier remains **mid** for Grok 4.6 and 4.5, but a **reported** `reasoning_effort` now sets session eligibility: `low`→mid, `medium`/`high`→reasoner, `xhigh`→frontier on 4.6. **Grok 4.5 `xhigh` coerces to `high` → reasoner** (matches the xAI API). **Unknown effort stays mid** (API default high does not silently take frontier backlog). Fleet ids like `x-ai/grok-4.6` count as Grok family; lease/worktree ids such as `grok-effort-tier-46` do **not** (`is_grok_family` requires a product-shaped name; `work_once` never uses `--agent-id` as the model). On Grok, mid-only Preferred needs `low` or omitted effort — `medium` already promotes to reasoner. `plan_fit --help`, `/work` skills, and live docs now match the picker (Grok effort *does* change eligibility; other products stay cost-dial-only). Implemented in `plan_select.effective_fit_tier` / `worker_with_effort`; wired through `plan_fit`, `plan_select --effort`, and `work_once --effort`. `anchor_client` accepts endpoint quirk `reasoning_effort` (incl. `xhigh` for 4.6). Doctrine: `model-fitness.md`, `platforms/grok-build/GROK.md`, `/work` skills. This **changes** prior “effort never promotes tier” language for Grok only.

- **Merge authority: `/review` survey **or** the operator's answer at `/work` culmination** — the framework-wide rule that *only* a `/review` Approve may land a branch on integration is amended. A `/work` session may now merge `feature/<slug>` → **`dev` only**, and only when the operator answers its end-of-run question in-session *and* the branch passes the scoped-merge gate. `/review` remains the only route to `main`/`master` and the only route for work the operator did not just watch happen; executors and unattended runs still never merge. This adds one lane transition — `in-progress/` → `completed/` — which is **not** an agent self-certify path: it exists only as the tail of an operator-authorized merge, and the plan lands with a `## Handoff` note (`merged to dev by /work <date> — no /review sign-off`) that keeps every skipped review auditable in `/review --list` and `pending_merges.py`. `/review`'s survey preamble now surfaces a plan's `## Handoff` hold note first, since the hold reason is usually what to check before approving. Amended in lockstep across `.claude/commands/{work,review,commit-prep}.md`, `.grok/skills/{work,review,commit-prep}/SKILL.md`, `anchor/ANCHOR.md`, root `CLAUDE.md`, `anchor/scaffold/plans/README.md`, `platforms/{claude-code/CLAUDE.md,grok-build/GROK.md,chat/CHAT.md}`, `mcp/project-orchestrator/README.md`, `scripts/work_once.py`, and the docs pages — a surviving "`/work` never merges" line would make a careful model refuse the new path, so the sweep is part of the change rather than a follow-up

- **`/deploy` now checks for an unpromoted integration branch before deploying** — if the project has `dev` (or `develop`) with commits not yet merged into the branch this deploy actually publishes from, `/deploy` reports the gap (commit count + short log) and asks whether to run `/review` first, deploy the current branch as-is, or cancel; `--yes` defaults to deploying as-is rather than blocking on an unanswerable question. `/deploy` still never merges or promotes branches itself — landing `dev` stays `/review`'s job, same as before. Claude (`.claude/commands/deploy.md`), Grok (`.grok/skills/deploy/SKILL.md`), and docs (`/skills/deploy`) updated
- **`/review` Approve now merges `feature/<slug>` → `dev`** (create `dev` if needed; FF preferred; conflict aborts without completing the plan), then moves the plan to `completed/`. Empty `review-needed/` with integration ahead of mainline offers a **promotion review** (diff + survey); **Promote** merges `dev` → `main`. Flags: `--promote`, `--no-promote`, `--push` (push still confirm-gated; never force-push). At the time, `/work` never merged at all; the scoped-merge entry above later widened that to "`/work` may land on `dev` via the operator's in-session answer", leaving `/review` the only route to `main`. Claude + Grok skills, docs, scaffold/repo `.plans` README, platform briefs, and `pending_merges.py` advisory copy updated.
- **Agent finish defaults to `review-needed/`** — `/work` no longer offers an optional self-certify path to `completed/`. When Done when holds, agents `git mv` `in-progress/` → `review-needed/` and tell the human to run **`/review`**. Agents never move `in-progress/` → `completed/` on their own judgment (same rule as MCP `plans_complete`); the scoped-merge entry above later added the single exception, where the operator authorizes the merge in-session. Aligns interactive skills, `.plans/README`, scaffold, platforms (`CLAUDE.md` / `GROK.md` / `CHAT.md`), and docs with the human sign-off lane.
- **`scripts/pending_merges.py` gains last-commit age and a recency filter** — `PendingBranch` now carries `last_commit_epoch`, surfaced in the table report ("last commit" column) and in `--json`; `find_pending(root, since_days=…)` (CLI: `--since <days>` / `--all-pending`) drops branches whose tip commit is older than the window, **except** a branch matching a completed plan, which is always kept regardless of age. Backward compatible — `since_days` defaults to `None` (no filtering), matching every existing caller's prior behavior. Built for `/release`'s branch-intake step so it doesn't hand-roll its own git parsing
- **`/config` is no longer scaffolded into projects** — it sets the *operator's* Anchor defaults by running `./config.sh` from the Anchor checkout, so it has nothing to act on inside a scaffolded tree. It is now base-only for **both** platforms (Claude used to ship `.claude/commands/config.md` into projects; that is locked shut and covered by a `test_anchor.py` regression). `platforms/claude-code/CLAUDE.md` and `platforms/grok-build/GROK.md` now point operators to run `/config` from the Anchor checkout and to use `anchor <dir> --set-orchestrator <token>` for a single project's orchestrator

### Fixed

- **`scripts/worktree_for_agent.py` could silently discard a feature branch's commits** — `ensure()`'s feature-branch checkout, when it failed because `feat` was already checked out in another worktree, fell through to `git checkout -B feat integration`: `-B` isn't blocked by the same "already checked out elsewhere" guard a plain checkout is, so it succeeded and force-reset `feat` to `integration`'s tip, discarding every commit the branch actually had. This is exactly the failure mode the file's own sibling fallback for the *base* branch two lines above already avoids correctly — that one creates a distinct new branch name (`f"{base_branch}-wt"`) on the same trigger instead of resetting anything. `ensure()` now detects the identical "already checked out elsewhere" failure on the feature-branch path and refuses with a clear error naming the branch, instead of resetting it; the branch's commits and the other worktree's checkout are both left untouched. New regression test reproduces the exact loss scenario (a real commit on `feat`, checked out elsewhere, a second `ensure_worktree` call for the same slug) and proves the branch tip survives the refused attempt
- **`scripts/merge_feature.py` reported a merge on a run that moved nothing** — when a branch had been merged into the integration branch earlier and the **integration branch** had since advanced past it (the feature branch itself unchanged and left behind), the fast-forward test ("can the target be moved up to the branch?") answered no, so the run took the non-fast-forward path; `git merge --ff-only` then answered "Already up to date", exited 0, and `land()` handed back the target's **unchanged** head. The CLI printed `gate passed: … (merge commit (no-ff))` followed by `merged; dev is now <sha>` — two statements that were both false, on exit 0. A branch already contained in the target is now detected up front and reported as **already contained**, naming that the target is unchanged; the run creates no commit, runs no conflict probe, and does not disturb the checkout at all. It still exits `0`, because the work genuinely is integrated — what changes is that it no longer claims this run integrated it. `land()` returns a distinct `ALREADY_CONTAINED` sentinel so programmatic callers can tell the two apart, which they could not before: both handed back the target's head

- **The MCP SDK fix could rot silently — both guards closed** — two Low/Nit findings from the `dev`→`main` promotion review, neither of which blocked it. **(1)** `docs/docs/tooling/mcp-servers.md` carries the corrected, bounded `pip install "mcp[cli]>=1.2.0,<3"` that the SDK-2.0 fix repaired, but it was **not** in `check_docs_sync.py`'s `SYNC_MAP`, so nothing would notice when the three server READMEs it mirrors moved — the page could fall out of date with its own sources unremarked. Note what this does and does not buy: the checker compares **source** hashes, never the page's text, so an edit made directly to the page is still invisible to it — that is exactly what the script's "compares hashes, not content" note means, and re-reviewing a flagged page is what catches the drift. `SYNC_MAP` could not express this page either: it was `dict[str, str]`, one source to one page, while that page mirrors **three** server READMEs. The schema now accepts a **tuple of sources** per page, records one `synced-from:` comment per source, and reports the page stale when **any** of them moves (verified: reverting one README's install line to the unbounded form flags the page and names which source changed). All eight pre-existing 1:1 entries are unchanged and still pass; `--stamp` handles both shapes. **(2)** `requirements-dev.txt` carried the unbounded `mcp[cli]>=1.2.0,<3` while `ci.yml` runs only on push to `main` and PRs — so a new SDK major could turn mainline red with no commit of ours. The blocking job now pins `mcp[cli]==2.0.*`, and a new `sdk-unpinned` job (weekly schedule + `workflow_dispatch`) resolves the range the servers actually declare and imports every server against it. Those two triggers are what keep it from ever blocking a push or a merge, and the job is **allowed to fail**: marking it `continue-on-error` concluded the whole run green and notified nobody, which is not a signal. Pinning alone would have silenced the detection the test exists for. The servers' own `pyproject.toml` bounds are untouched — those describe what the software supports, which is a different question from what CI installs

- **`/review` authorized commits without ever running `/commit-prep`** — the skill created merge commits (`git merge --no-ff -m …`, both feature→integration and integration→mainline) and staged tracked plan-lane renames and review notes, while referencing `commit-prep` **zero times** in either the Claude or the Grok copy. In the Anchor repo this was invisible because it gitignores its whole `.plans/` tree; a **scaffolded project tracks it** (the scaffold ignores only `**/*.local.md` and `.leases/`), so every `/review` there left staged plan changes for the next unrelated commit to swallow. The hard rule in `CLAUDE.md` is now **scoped to what a commit contains** rather than stated absolutely: prep is required before any commit touching a path outside `.plans/` **and before any merge commit**, while a commit whose paths are *entirely* under `.plans/` takes a **light path** (state what moved and why, then commit — no CHANGELOG, no blog, no test run, because a lane move cannot break a test and gating it behind one is what trains operators to skip the skill). That lane-move commit is the one **exception** to *never commit on main/dev* — `/review`, `/work` and `/draft --promote` each make it on whichever branch the lane move exists on — and it is written `git commit -m "…" -- .plans/`: everything after `--` is a pathspec, so the flag order is load-bearing and the reversed form commits nothing while appearing to succeed. It must never run while a merge is staged, because git refuses a partial commit mid-merge and dropping the pathspec to clear that error would commit the entire merge ungated. A **merge commit is now gated before it exists**: `git merge --no-ff --no-commit`, run prep against the merged working tree — state neither branch was prepped in, where a clean textual merge can still be semantically broken — then `git add -A && git commit` if green (a bare `git commit` commits only the index and drops prep's own edits) or `git merge --abort || git reset --hard HEAD` if red (`--abort` refuses once prep has touched a merged file); the reset discards prep's edits to *tracked* files but leaves anything it **created**, such as a new blog post, untracked on disk. A fast-forward creates no commit and needs no further gate. The rule is restated in `platforms/claude-code/CLAUDE.md`, `platforms/grok-build/GROK.md` and `platforms/chat/CHAT.md` so scaffolded projects inherit it. New `tests/test_skill_commit_prep.py` fails if any skill runs a commit-creating git command (including the `git -C`/`git -c` forms and `gh pr merge`) without a `/commit-prep` reference **within 25 lines of that command** — checked per command rather than per file, so one reference beside the first commit no longer covers every later one — and separately if any skill uses `git merge --no-ff` without the `--no-commit` staging step; it reads the platform briefs and docs mirrors too, not just the skills. New `tests/test_light_path_command.py` **executes** the light-path command exactly as the skills ship it against a throwaway repo, so a command that runs cleanly while committing nothing fails the suite. Documented at [/skills/review](/skills/review)

- **`scripts/merge_feature.py`'s scoped merge created merge commits with no prep gate** — a non-fast-forward `land()` ran `git merge --no-ff <branch> -m …` outright, so the merged tree (state neither branch was prepped in) never got a `/commit-prep` pass, even though the merge-commit rule above requires one. `land()` now stages a non-fast-forward merge instead of committing it (`--no-commit`) and returns without creating a commit; the CLI reports this with exit **`6`** — neither success nor failure — naming what happened and how to finish it. Two new flags resume a staged merge: `--commit-staged` (after `/commit-prep` comes back green) verifies the merge is still genuinely in progress on the recorded target branch, then stages prep's own working-tree edits along with the merge, commits both, and returns to the branch you started on; `--abort-staged` (after a red prep) unwinds the merge, falling back to `git reset --hard` because `git merge --abort` refuses once prep has modified a merged file. Both finishers first check that the recorded merge is still the merge in front of them, and refuse rather than guess. `MERGE_HEAD` merely *existing* is not enough: it is compared against the exact commit that was merged — recorded at staging time, because the branch name legitimately advances when a red prep is fixed by committing on it — so a stale record plus any other staged merge on the same target — an operator's hand-run `git merge`, or another agent's — is refused rather than committed under the wrong plan's name having passed none of the scope, provenance or `--expect-head` checks. Against a merge already resolved by hand, `--commit-staged` refuses instead of committing whatever is now in the tree, and `--abort-staged` clears the stale record **without** resetting — a `reset --hard` against a tree the record no longer describes destroys unrelated uncommitted work instead of undoing a merge. A merge in progress on a different branch than recorded refuses on both. Staging a merge now also requires `--root` itself to be fit for one: it is refused if that checkout already has a merge in progress or an unfinished staged record (the conflict probe would otherwise abort another agent's staged merge — both skills point every agent at the same shared checkout), or if it holds uncommitted or untracked files, which `--commit-staged`'s `git add -A` would otherwise sweep into the merge commit. Passing both finisher flags, or `--dry-run` with either, is now refused rather than silently resolved. The clean-`--root` requirement covers every run that actually merges, **including `--dry-run`**, because the conflict probe ends in a `git reset --hard` that cannot distinguish your uncommitted edits from merge residue; the runs that touch nothing stay exempt — a fast-forward, and (since the already-contained fix above) a branch already in the target; neither probes nor commits. The check asks git for untracked files explicitly (`--untracked-files=normal`), because `git status` honours `status.showUntrackedFiles` while `git add -A` does not — with that config set the guard would have seen a clean tree and swept the files anyway. **Upgrade note:** the pending-merge record gained a required field, so a merge left staged by an older build reads as no record — both finishers refuse and name the in-progress merge so it can be finished by hand (`git commit`) or dropped (`git merge --abort`); the record self-heals on the next run. The pending merge is recorded under the repository's real git directory (resolved with `git rev-parse --absolute-git-dir`, so it works correctly inside a linked worktree too — the topology `/work` recommends), and both finishers clear it. `--slug`/`--touched`/`--expect-head` are no longer demanded on the finisher routes, which have no use for them. The fast-forward path is unchanged and still reports a real SHA. Documented at [How work reaches `dev`](/tooling/how-work-reaches-dev)
- **Grok 4.6 sessions could be instructed to self-report as 4.5** — GROK.md, the
  `/work` skill (Grok + Claude copies), and one `docs/docs/` mirror told a running
  session to "pick product by cost ladder" before reporting its own name, and used
  bare "Grok 4.5" as the canonical self-identity example even though the cost
  ladder is a **routing** table for which product to open next, not a source of
  truth for who the current session is. A live Grok 4.6 session following that
  instruction would report itself (and match `Preferred models`, `plan_fit`
  eligibility, and the effort→tier map) as Grok 4.5. Session identity is now
  stated once, up front: the harness/system-prompt line (or an explicit
  `/model`/`--model`/endpoint override) is the only source of a session's own
  name; the cost ladder stays for picking which product to open. The 4.5/4.6
  cost ladder, catalog rows, and effort-coercion tests are unchanged.

- **MCP servers could not start on a fresh install (SDK 2.0 removed `mcp.server.fastmcp`)** — all three servers (`model-fleet`, `anchor-prompts`, `project-orchestrator`) opened with `from mcp.server.fastmcp import FastMCP` while declaring an **unbounded** `mcp[cli]>=1.2.0`, so any new install resolved SDK **2.0.0** — which deleted that module and renamed `FastMCP` to `MCPServer` — and every server died at import with `ModuleNotFoundError`. Our own READMEs and module docstrings instructed the failing `pip install "mcp[cli]"`. Since the decorator surface (`tool`, `prompt`, `resource`) and `run()` are unchanged across the rename, each server now resolves the class once at import (SDK 2 first, SDK 1 as the guarded fallback) and the dependency is bounded `>=1.2.0,<3` — a fresh install works **and** an operator pinned to 1.x is not broken; verified by importing all three against both 1.29.0 and 2.0.0. Install commands in the three READMEs, the three module docstrings, and the docs page now carry the bound. New `tests/test_mcp_servers_import.py` imports each server against the **actually installed** SDK in a subprocess run from outside the repo, asserting it resolved a real site-packages `mcp` before trusting the result, asserts every server declares an upper bound, and rejects an unguarded module-level import of the removed module; `requirements-dev.txt` now installs the SDK so CI exercises it instead of skipping. Documented at [MCP servers](/tooling/mcp-servers), including the shadowing caveat

- **Review-skill blog post links to the review-needed-lane post** — the in-page href is now Docusaurus’s date-based route (`/blog/2026/07/12/review-needed-lane/`) instead of a filename-shaped path that 404s.
- **Scoped-merge file scope uses range history, not net two-dot diff** — `merge_feature.changed_files` now unions every path from `git log --name-only --pretty=format: --no-renames base..head`. A path added and then deleted within the range is still named (net `git diff base..head --name-only` is empty for it), so an undeclared blob cannot ride into `dev` history without a scope refusal. Docs/skills describe the history-union contract. Covered in `tests/test_merge_feature.py`.
- **Scoped-merge doctrine docs no longer contradict the culmination path** — `docs/docs/skills/review.md` Related bullet said agents finish to `review-needed/` and **never** merge (markdown emphasis hid it from a literal `never merge` grep). It now states the shipped contract: default finish is still `review-needed/`; interactive `/work` may land on **`dev` only** via the operator answer + scoped gate; unattended never merges; `/review` remains the only route to `main`. `docs/docs/skills/work.md` diagrams and Chat dictate rule now show the optional `in-progress/` → `completed/` edge after that answer.
- **`scope_gate.clean_entry` unwraps markdown bold around paths** — a touched line written as `**app/secret.py**` no longer becomes a glob that also matches `myapp/secret.py`. Real globs like `**/*.py` are unchanged. Covered in `tests/test_scope_gate.py` and `tests/test_merge_feature.py`.
- **`scope_gate.clean_entry` no longer truncates paths on internal double spaces** — trailing notes still strip on em/en dash, ` - `, or whitespace before `(`; bare multi-space runs inside a path (`path with  double space.py`) are preserved so scope/touched sets do not false-refuse legal paths. Covered in `tests/test_scope_gate.py`.

- **Consumer-facing docs still told scaffolded projects to use project-root `scripts/`/`mcp/`/`ANCHOR-CONVENTIONS.md`** — the fleet scaffold destination moved to `.anchor/scripts/`, `.anchor/mcp/`, and `.anchor/conventions.md` (already shipped), but the platform files those paths actually appear in — `CLAUDE.md`, `GROK.md`, `NEMOTRON.md`, every `platforms/local-models/*.md`, and the Grok local-models skill — still pointed at the old root paths, so following them literally in a scaffolded project would fail. Fixed throughout; `.claude/commands/work.md`, `.claude/commands/review.md`, and their Grok equivalents (large files that double as both this repo's own skill and every scaffolded project's copy of it, so a single hardcoded path can't be right in both contexts) instead gained one upfront note establishing the substitution instead of rewriting every command example. Source-repo-only references (`scripts/anchor.py`, `bin/anchor` — locating the Anchor checkout itself) were deliberately left alone; migration-detection scripts that already check both the legacy and current path on the same line were left alone too. Docs-sync stamps refreshed for the four mirrored pages this touched, and a stray leftover `<!-- synced-from: … @ PENDING -->` placeholder comment was cleaned out of three of them
- **MCP servers each hand-rolled their own project-root resolver** — `project-orchestrator`, `model-fleet`, and `anchor-prompts` each carried their own copy of the `.anchor/mcp/<name>` vs `mcp/<name>` root-detection logic instead of the shared `anchor_client.project_root_from`. The duplication was correct by construction (same logic, copy-pasted three times) but a change to the real resolver wouldn't have propagated. A minimal bootstrap copy is kept only where it's structurally required — locating `scripts/` before `anchor_client` is importable — and `REPO` is reassigned to `project_root_from`'s output immediately after that import, making the shared resolver authoritative for all three servers' actual path resolution
- **`resolve_doctrine_path` silently mangled explicit `.anchor/...` paths** — it normalized the input with `rel.lstrip("./")`, which strips leading characters (not a `"./"` prefix), so any path starting with a dot — every `.anchor/...` call — had its leading `.` stripped to `anchor/...` before the dual-read logic ran. That reversed the intended priority: a caller explicitly asking for the scaffolded `.anchor/` file would silently get the legacy `anchor/` one instead whenever both existed. Same latent pattern fixed in `anchor.py`'s `fleet_dest()` (not currently reachable with real inputs, but the same footgun). Covered by new tests in `test_anchor_client.py` for both source and `.anchor/{scripts,mcp}` layouts and the dual-read priority
- **`renew()` heartbeat could silently steal or fabricate a lease** — `scripts/plan_lease.py`'s heartbeat let a call from any agent succeed against an in-progress plan with **no** lease file at all (writing a brand-new lease as if it had claimed it), and against a plan whose lease had **expired under a different agent** (silently taking over abandoned work instead of routing through the explicit `recover=True` path). `renew()` now refuses both cases — it only ever extends a lease already on file for the calling `agent_id`, active or that agent's own just-expired one; unleased or foreign-owned (active or expired) plans raise `ClaimError`. `work_once.py --heartbeat` and the MCP `plans_heartbeat` tool already propagated `ClaimError` correctly and needed no changes. Covered by two new `test_plan_lease.py` cases; also re-aligned the stale "resume own in-progress first" wording still left in `docs/docs/skills/work.md`'s Usage table and the Claude/Grok/local-models platform briefs with the shipped ready-lanes-only bare `/work` behavior
- **Lesser models declined work they were suited for** — the fit check was over-triggering in the *down* direction. Doctrine defined `underqualified` as "Preferred needs reasoner/frontier **(or named stronger models)**", so a `mid`/`small`/local session skipped any plan whose `Preferred models` merely *named* a stronger product (`mid, Claude Sonnet 5, Grok 4.5` read as off-limits), and an absent or names-only list read as "reserved for a higher tier" — both **stricter than the picker code**, which already classifies those as eligible (`unknown`) and claims them. The `/work` fit table now gates on listed **tiers** only (names are extra good-fit hits, never a raised floor; absent/names-only = eligible after a one-line note), with a new "do not under-rate yourself" section; mythos-core rule 11 and `model-fitness.md` scope the gate to the model's weak column and orchestration-class work — "a stronger model exists", an unfamiliar/multi-file task, or one hard-looking step are explicitly **not** grounds to escalate. `scripts/anchor.py` gains a single `lesser_model_block()` owner for the `.anchor/conventions.md` "if you are a lesser model" section: the scaffold and `--set-orchestrator` paths had drifted, and the shorter one dropped the "here is what you may still claim" half, leaving escalate-only guidance. Poor-fit **refusals are now terse** — a one-line verdict plus at most two `→` lines, no restated Goal or re-derived rules. Covered across `test_plan_select.py`, `test_anchor.py`, and mirrored docs
- **A role-violating task was scored as an accurate claim** — the claimed-vs-actual ledger row was written inside `execute_task` at the verify step, but a task's **role verdict** is only known after it returns. An executor that wrote outside its role boundary (e.g. into `.plans/**`) and still passed verify was recorded as a clean, accurate `success` — in the very tool whose job is measuring claim accuracy. `orchestrate.py` now holds the row until the role check has run and stamps it with `role_verdict` (`pass`/`fail`, `None` when the run had no role enforcement); `OutcomeRecord` gains the field, `load_outcomes` reads it back, and `fitness_report.py` excludes `role_verdict == "fail"` rows from positive claim accuracy. Scope failures need no equivalent guard — they short-circuit before verify and already arrive with no exit code. Covered by four tests across `test_orchestrate.py` and `test_fitness_report.py`
- **Removed the abandoned `platforms/grok-build/commands/` tree** — five stale duplicates left behind when Grok moved to `.grok/skills/*/SKILL.md`, badly out of date (its `work.md` was 58 lines against the canonical 403) and still linked from `docs/docs/skills/work.md` as a usable alternative. The one current file, `config.md`, is preserved as **`.grok/skills/config/SKILL.md`**; `GROK.md` points there instead of at the deleted folder
- **`docs/package-lock.json` no longer drifts from `package.json`** — the lock's root dependency block still recorded `@docusaurus/core` / `preset-classic` at `^3.7.0` while `package.json` had moved to `^3.10.1`, so any `npm install` regenerated the same two-line diff and left contributors with phantom lockfile churn in every worktree. Regenerated. (`npm ci` was never broken by this — the resolved versions already satisfied the newer range.)


## [0.1.0] - 2026-07-19

First tagged release. Anchor's doctrine, `.plans/` workflow, scaffold CLI, fleet
tooling, and MCP servers as they stand today.

### Added

- **Capacity routing doctrine** (`anchor/capacity-routing.md` → scaffolded as `.anchor/capacity-routing.md`; docs at `/capacity-routing`) — what an agent does when a subscription tier runs out of capacity (session cap, rolling window, weekly quota, `429`/`insufficient_quota`, or a forced tier downgrade). Distinguishes capacity limits from transient rate limits, then works a fixed order: **reroute** to the next model in priority order *that clears the task's fitness floor*, else **wait** for a near reset, else **stop and report** — always after checkpointing to the in-progress plan. Rerouting requires restating the task spec on the new tier and re-verifying inherited claims, since a new model has no session memory. Hard limits: never continue on a silently downgraded tier, never narrow scope or weaken tests to beat a cap, never fabricate completion. Most useful in multi-provider harnesses (Cursor, Cline, OpenRouter-backed tools, `endpoints.yaml` fleets). Standing rules added to `platforms/claude-code/CLAUDE.md` and `platforms/grok-build/GROK.md`; routing section added to `anchor/ANCHOR.md`

- **`review-needed/` lane** — a new path-authoritative `.plans/` lane, framework-wide: an agent that believes a plan's `Done when` holds can `git mv` it from `in-progress/` to `review-needed/` instead of straight to `completed/`, for human sign-off; only a **human** may move `review-needed/` → `completed/` (agents must never perform that move — it's the entire point of the lane). A human may also send it back to `in-progress/` (changes requested) or release/return it to `bugs/`/`features/`. Never auto-picked or auto-executed. Landed in `.plans/README.md`, `.claude/commands/work.md`, `.grok/skills/work/SKILL.md`, `platforms/grok-build/commands/work.md`, `scripts/check_plans.py` (`KNOWN_LANES`), `scripts/plan_select.py` (`REVIEW_LANE`, excluded from ready/executable lanes, included in `OPEN_LANES` for `Depends on` checks), the scaffold (`anchor/scaffold/plans/review-needed/.gitkeep` + `scripts/anchor.py` pairing), and docs (`docs/docs/skills/work.md`, `docs/docs/doctrine.md`, `docs/docs/tooling/fleet-workers.md`)
- **`/work` cheaper-capacity probe + same-model effort right-size** — before skipping an overqualified plan or burning a high-cost session on `small`/`mid` Preferred work, `/work` now checks `scripts/endpoints.yaml` (and product-local models / project conventions) for a lesser **reachable** executor and prints its dispatch line (`work_once.py --once --endpoint …`) instead of claiming the plan; when nothing cheaper is reachable, it emits a pasteable effort-lowering command for the current session (Grok Build TUI `/effort low` / `/model <id> low`, CLI `--effort low`, Nemotron/Qwen3 thinking-off) rather than a dead stop. High reasoning effort on a mid-class model is treated as a cost dial, not a tier promotion. Landed in `.claude/commands/work.md`, `.grok/skills/work/SKILL.md`, `platforms/grok-build/GROK.md` + `commands/work.md`, and mirrored docs (`docs/docs/skills/work.md`, `docs/docs/platforms/grok-build.md`)
- **Grok 4.5 catalog tier clarified as `mid`** for `/work` Preferred-models matching (`anchor/model-fitness.md`, `docs/docs/model-fitness.md`) — its default *high* `reasoning_effort` doesn't make it overqualified for `mid` plans
- **`scripts/roles.py`** — planner / executor / critic as **harness-enforced capability sets** (single role→capability map): writable-path allow/deny globs per role (planner only `.plans/**`; executor everything except `.plans/**` and its own spec; critic read-only), `can_dispatch` (orchestrator only), and per-role MCP toolsets. Reuses `scope_gate.path_matches` — one glob implementation
- **`orchestrate.py` role enforcement** — each phase's worktree writes are checked against its role's capability map (only changes made *during* a phase are attributed to it); a violation is a hard error: logged as an event, task marked `failed-role`, run still emits its outputs then exits `4`. Role transitions (plan approved → executors spawned → review) are explicit logged events in the run JSON
- **project-orchestrator MCP `--role`** — `--role planner|executor|critic|orchestrator` scopes the registered toolset: planner/critic sessions never see `plans_claim`/`plans_release`/`plans_complete` (deny by omission); no `--role` keeps the full surface. ANCHOR.md role-separation bullet + mythos-core rule 2 now note the harness guarantee (orchestrated path only; single-model sessions stay prompt-bound)
- **Project `/anchor` skill** (scaffolded via `claude`/`grok`; source under `platforms/…`) — while in a project, locate the local Anchor checkout and **conform this project** (CWD/git root default): check/upgrade or conflict-aware scaffold; fix source-missing managed files when paths moved under `platforms/`. Anchor base `/anchor` remains path-required for operating on another tree.
- **`/anchor` skill** (Anchor base — Grok + Claude) — agent-driven scaffold/reconfigure of a **target** project: path required; dry-run first; merge/backup/skip on conflicts; prefer `--upgrade` when a manifest exists.
- **`/install-anchor` skill** (Claude + Grok; scaffolded) — safely put the `anchor` CLI on `PATH` via a user-local symlink to `bin/anchor` (no sudo by default); status / fix / optional bindir.
- **`/local-models` skill** (scaffolded via `claude`/`grok` platforms; source under `platforms/…`, **not** Anchor base skills) + **`fit_device.py --probe`** — evaluate this machine for lean local models; install links; optional reconfigure draft; WSL host probe + routing policy.
- **WSL host probe** — from WSL, `--probe` calls `powershell.exe` for bare-metal RAM/CPU/GPU (no user-run `.ps1`); sizes fits to host budget; recommends running the model server on **Windows bare metal** with Anchor remaining in WSL.
- **`/local-models` draft offer** — after the probe report, agents ask whether to create a `.plans/drafts/` plan to wire the project to the detected local model(s); install process lives in **`## Prerequisites`** for later `/work` once deps are installed.
- **`/local-models` routing policy** — reconfigure drafts: user model-priority order is primary; small locals stay on light tiers; when the host can run heavy local inference, prefer fit locals for heavy work within that priority (no promoting tiny locals to frontier roles).
- **`anchor --upgrade` / `--update`** — refresh an already-scaffolded project to current scaffold patterns: layout migration (`anchor/…` doctrine → `.anchor/…`), take clean upstream updates, restore missing managed files, add newly introduced scaffold files for recorded platforms; keeps locally modified files unless `--force`. **`--diff`** prints unified diffs; **`--check`** remains a short status summary. Non-interactive: `--yes` (required off a tty).
- **`scripts/scope_gate.py`** — machine-enforced scope gate (mythos-core rule 7): rejects any worktree change outside a task spec's `## Files in scope` **before** tests run. Pure `check_scope` + git-backed `worktree_changes`/`enforce_scope`; gitignore-style globs; `Allowed generated files:` allowlist. Wired into `orchestrate.py --scope-spec` (out-of-scope → `failed-scope`, tests skipped, routed back to planner) and usable standalone as a verify pre-step (`scope_gate.py --root . --spec spec.md && pytest -q`, exit `3` = violation). Task-spec template + docs updated
- **`scripts/pending_merges.py`** — surfaces finished work committed but **not yet merged** into integration: counts each local branch's commits ahead of its merge target (`feature/*` → `dev`/`develop` → mainline) and flags `feature/<slug>` branches matching a plan under `.plans/completed/` as *completed work awaiting merge*. Advisory table by default; `--json`, `--exit-code` (exit `1` when pending) for coordinators/monitors/CI
- **Plan `Priority:` header** (`P1` > `P2` > `P3`, default `P2`) — orders ready plans **within a lane** ahead of `Value`; parsed by `scripts/plan_select.py` (`parse_priority` + `plan_sort_key`), shown in `work_once.py --list`; documented in the plan template, `.plans/` README, `/work` (Claude/Grok/Chat), ANCHOR.md, and docs
- **`scripts/worktree_for_agent.py`** — per-`agent-id` git worktrees under `var/worktrees/` (ensure/list/path/remove; auto-create `dev` from main/master); `work_once.py --ensure-worktree` after claim
- **Scaffold / project config ensures `var/`** — creates `var/` + `var/worktrees/`, appends `var/` to root `.gitignore` (scaffold + `--set-orchestrator`)
- **`mcp/project-orchestrator/`** — per-project limited orchestrator MCP (L0+L1): `plans_list` / `plans_claim` / `plans_complete` (move-only), heuristic `plans_suggest_dependencies` (propose-only), `plans_stale_report` (tier-gap / age warnings); reuses `plan_select` + `plan_lease`; config `.anchor/mcp.yaml`
- Docs: MCP servers page documents project-orchestrator alongside anchor-prompts and model-fleet
- Blog: [Per-project plan orchestration via MCP](docs/blog/2026-07-09-project-orchestrator-mcp.md)
- Blog: [Parallel agents get their own git worktrees](docs/blog/2026-07-09-agent-worktrees.md)
- **`/draft`** skill (Claude `.claude/commands/draft.md`, Grok `.grok/skills/draft/SKILL.md`, Chat) — planning mode under `.plans/drafts/`; `--list`, `--load`, create/refine, optional `--local` → `*.local.md`; **`--promote <slug>`** infers `bugs/` vs `features/` from the plan (never from `/work`/fleet)
- **`/fleet-watch`** skill + `scripts/fleet_watch.py` — durable multi-tier plan watchers (status/list/once, emit/install systemd user timers with linger, cron fallback); scaffolded for Claude/Grok
- **`scripts/work_once.py`** — headless one-shot / bounded-loop puller (same priority, Preferred models, and Depends on as `/work`); leases in `.plans/.leases/`; shared `scripts/plan_select.py` + `scripts/plan_lease.py`
- Docs: **[Savings](docs/docs/savings.md)** — inference-cost framing, 12-month adoption curves (Q1 ramp), solar-for-local-compute section, humble plain-text donate links; navbar + intro + playbook
- Docs: **Multi-agent fleet workers** (`docs/docs/tooling/fleet-workers.md`) and Skills pages for `/work`, `/draft`, `/fleet-watch`
- Docs site: **Mermaid** (`@docusaurus/theme-mermaid`) plus mid/high-value section graphs across doctrine, playbook, intro, platforms, tooling, hardware
- Docs: local model names link to **official quick-start** pages (Qwen3, Gemma 3, Mistral Small, DeepSeek-R1, Llama 3.3)
- Blog: [Plans, fleet workers, and inference savings](docs/blog/2026-07-08-plans-fleet-savings.md)
- **Preferred orchestrator** (per project): `config.sh --orchestrator`, `anchor --orchestrator` / `--set-orchestrator`, `ANCHOR-CONVENTIONS.md`
- Tracked **`.plans/`** workflow: path-authoritative lanes (`bugs/`, `features/`, `in-progress/`, `ambiguous/`, `blocked/`, `drafts/`, `completed/`); `*.local.md` via `.plans/.gitignore`; scaffold tree under `anchor/scaffold/plans/`
- **`/work`** entrypoint (Claude, Grok, Chat) — pick/execute ready plans; `--list`, `--no-fit-check`; Preferred models + Depends on
- Plan template: Value, Slug, Preferred models, Depends on (no in-file Lane/Status)
- `scripts/check_plans.py` — path-lane + section sanity for `.plans/`
- `anchor/model-fitness.md` + fit check (mythos-core rule 11); scaffolded into projects
- `scripts/fit_device.py` and `hardware/personal-devices/` serve helpers
- Model-priority preference via `./config.sh --model-priority`
- `/commit-prep` command (Claude, Grok, chat)

### Fixed

- **`/commit-prep` was a hard rule the scaffold never delivered** — `CLAUDE.md`/`GROK.md` require `/commit-prep` before any `git commit` and `/work` calls it, but the command was absent from `PLATFORMS` in `scripts/anchor.py`, so scaffolded projects were told to run a command they never received (Grok's only copy sat at the abandoned `platforms/grok-build/commands/` path, unused since Grok moved to `.grok/skills/*/SKILL.md`). `scripts/anchor.py` now pairs `.claude/commands/commit-prep.md` and a new `.grok/skills/commit-prep/SKILL.md`; `GROK.md` points at the skill path. Covered by `test_plan_copy_scaffolds_commit_prep_for_both_platforms`
- **Two agents could collide on one in-progress plan** — a plan claimed by a live agent that hadn't recorded a lease (leases were optional) or whose short 1h TTL had lapsed looked *stalled/orphaned* to a second `/work`, which could silently reclaim it. Bare `/work` no longer scans `in-progress/` at all, claiming always writes a lease, the TTL is long (24h) with a heartbeat, and an unleased or expired-lease in-progress plan is **never** silently reclaimed — takeover of genuinely-abandoned work is an explicit `work_once.py --recover` / MCP `plans_claim(recover=true)`
- **Docs internal links** — rewrite relative cross-page links to absolute `/…` paths so they resolve correctly with Docusaurus `trailingSlash: true` (was producing broken `/anchor/tooling/skills/…`-style URLs)
- **Wording** — prefer **project** over “consumer app” / “consumer project”, and **Anchor** (or **Anchor base**) over “Anchor monorepo”, in skills, platform docs, README, and CLI docs
- Docs social cards for non-home routes: `trailingSlash: true` so GitHub Pages serves `/blog/`, `/doctrine/`, etc. (not 404); stronger global OG/Twitter image tags and blog description
- Mermaid diagrams render on the docs site (theme + `markdown.mermaid: true`)
- `orchestrate.py --plan-file` rejects non-executable lanes (`drafts/`, `completed/`, parked)
- README note for editable installs on old distro pip/setuptools (PEP 660)

### Changed

- **`/commit-prep` is project-agnostic by discovery, not by assumption** — the command no longer leans on Anchor-shaped defaults. Gate 1 treats **CI config as the authority** on what "green" means (`.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/`), falling back to a task-runner target (`make`/`just`/`npm`/`composer`/`rake`), then the language's default runner, then configured linters/type-checkers — and skips with a one-line note rather than scaffolding a suite the project doesn't have. Gate 2 matches the project's existing release-note convention (`CHANGELOG.md`, `CHANGES.md`, `NEWS`, `docs/changelog.md`, `changelog.d/` fragments) and, when notes are **generated** from Conventional Commits or PR labels, says the entry belongs in the commit message instead of hand-editing a generated file. Gate 3 follows an existing blog directory's conventions (Docusaurus, Jekyll `_posts/`, Hugo `content/posts/`), defaulting to plain Markdown under `docs/blog/` with no static-site generator required, and accepts "no audience for announcements" as a valid skip
- **`/work` picks ready lanes only; in-progress is owned by a required lease** — bare `/work` (and `work_once.py`, the project-orchestrator MCP, and the new picker) now select **only** from `bugs/`/`features/` and never scan `in-progress/` to resume or reclaim. Resuming your own work is an explicit named target (`/work in-progress/<slug>.md`); a foreign in-progress plan is never touched. Claiming a ready plan **moves it and writes its lease together** (required, not optional) — the lease under `.plans/.leases/` is what marks the plan yours so multiple agents can share one project safely. Lease TTL is now **24h** with a **heartbeat** (`work_once.py --heartbeat …`, MCP `plans_heartbeat`) so a live agent's plan never looks orphaned. Landed in `scripts/plan_select.py`, `scripts/plan_lease.py`, `scripts/work_once.py`, `mcp/project-orchestrator/{coordinator,server}.py`, `scripts/roles.py`, and doctrine (`.claude/commands/work.md`, `.grok/skills/work/SKILL.md`, `.plans/README.md`, scaffold README, `docs/docs/skills/work.md`, `docs/docs/tooling/{scripts,fleet-workers}.md`)
- **`plan_select.py --next` — deterministic single-plan picker for small/less-reliable models** — prints exactly one next ready plan (or a clear "nothing ready", exit `1`); `--next --claim --agent-id <id>` performs the atomic move-to-in-progress + lease itself so a weak model never runs `git mv` or touches `.leases/` by hand. `--json` for scripting; exit `0` picked / `1` nothing ready / `2` error
- **MCP `plans_complete` moves in-progress → `review-needed/`** (was `completed/`) — an agent asserting *Done when* now routes to human sign-off instead of self-certifying completion; only a human moves it on to `completed/`. New `plans_heartbeat` tool; `plans_claim` gains a `recover` flag for taking over an expired lease
- **Docs Skills sidebar** — category landing [Skills overview](docs/docs/skills/overview.md) lists every skill with **where it’s best used**, packaging (project vs Anchor), and a quick chooser; sidebar labels include short use-hints (`/anchor · update project`, …)
- Blog: [Agent skills for scaffold, PATH, and local models](docs/blog/2026-07-09-agent-skills-scaffold-local-models.md)
- **`.local.md` suffix is sticky** — plans that start as `*.local.md` keep that basename on `/draft --promote` and on later agent lane moves; agents must **never** drop `.local`. Only a **human manual rename** (or create with `/draft --shared`) makes a plan git-tracked. Replaces the old “promotion publishes” rule that stripped `.local` by default.
- **Scaffold doctrine dest is `.anchor/`** — core doctrine files copy from this repo’s `anchor/` package into the project’s **`.anchor/`** tree (e.g. `.anchor/ANCHOR.md`, `.anchor/templates/…`). Root **`.plans/`** is unchanged. Platform docs and generated `ANCHOR-CONVENTIONS.md` point at `.anchor/…`. Fleet `load_prompt` resolves both `anchor/` (source tree) and `.anchor/` (scaffold). Coexists with `.anchor/mcp.yaml`.
- **Fleet scaffold dest is `.anchor/scripts/` + `.anchor/mcp/`** — with `--fleet` (or saved FLEET=1), Anchor no longer writes project-root `scripts/` or `mcp/` (avoids colliding with app-owned trees). `anchor --upgrade` can migrate legacy root fleet copies. Script/MCP entrypoints resolve project root for both layouts.
- **Conventions file is `.anchor/conventions.md`** — scaffold and `--set-orchestrator` no longer write root `ANCHOR-CONVENTIONS.md`; readers dual-read the legacy name; upgrade migrates it.
- **Fresh drafts are private by default** — `/draft` creates `<slug>.local.md` (gitignored); `/draft --shared` creates a tracked `<slug>.md`. Applies to Claude, Grok, and Chat `/draft`
- **`/work` selection order now honors `Priority`** — own in-progress → bugs before features → `Priority` (`P1`>`P2`>`P3`, default `P2`) → `Value` → oldest first; applied consistently across `/work`, `scripts/work_once.py`, and fleet pullers
- **`/work` just-picks on ties by default** — when multiple ready plans share the top priority, `/work` takes the first in sorted order (Priority → Value → oldest → filename) and starts, instead of printing a menu and asking; it names the other tied plans so the user can redirect. Only pauses to ask when the user explicitly asks to choose (Claude + Grok `/work`)
- **Agents must run `/commit-prep` before any `git commit`** — standing rule on Claude/Grok/Chat platforms, `/work`, `/commit-prep` itself, and `.plans/` README (tests + CHANGELOG + blog-if-warranted gates)
- **`/commit-prep` is project-agnostic:** discover CI/tests per repo; no assumed Docusaurus build; blog posts are plain Markdown under `docs/blog/` (create the directory if missing)
- **After green `/commit-prep`, agents finishing plan work commit on the feature branch** (`/work` + platform rules — not inside `/commit-prep` itself; prep stays prep-only)
- **Agent Git:** if neither `dev` nor `develop` exists, **create `dev` from `main` (else `master`)** before feature branches (`/work`, scaffold `.plans/` README, platforms)
- **Docs rule (framework-wide):** docs describe **current shipped state**, not `.plans/` backlog — mythos-core rule 12, `ANCHOR.md`, platforms, scaffold, commit-prep
- **`.plans/` path is authoritative:** agents claim → `in-progress/`, park → `ambiguous/`|`blocked/`, finish → `completed/`; promotion via **`/draft --promote`** or human move only
- **Plan `Depends on`:** `plan_select` satisfaction checks; `/work` and `work_once` skip unmet deps
- **Temporary coordinator:** frontier/near-frontier may announce `TEMPORARY-COORDINATOR:` when Preferred orchestrator is unset; mid/small/local escalate
- Scaffold fleet install includes `work_once` / `plan_select` / `plan_lease` / `fleet_watch`
- Mid-page donate asks are **humble plain text** (link to [Savings](docs/docs/savings.md) + Stripe), not button CTA blocks
- Docs platforms, intro, playbook, MCP, scripts aligned with fleet + plans workflow
