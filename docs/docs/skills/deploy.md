---
sidebar_position: 3.7
sidebar_label: /deploy · ship the project
---

# `/deploy`

**Best used:** when a project is ready to go live and you want it shipped **the
way that project already ships** — or, if it has never been deployed, when you
want deployment tooling chosen and wired up properly instead of a one-off shell
script. See [Skills overview](/skills/overview).

`/deploy` **detects before it builds**. If the repo has a deploy path — a CI
workflow, a platform CLI config, Deployer/Capistrano/Kamal, or just a
`production` git remote — it runs that. Only when nothing is detected does it ask
where the project should live and set the tooling up.

## Why use it

| Without `/deploy` | With `/deploy` |
|-------------------|----------------|
| Every project's deploy lives in someone's shell history | The repo's own mechanism is detected and run |
| Agents improvise `rsync -a . server:/var/www` | Deployer-class releases: atomic symlink swap, keep N, rollback |
| "It deployed" = exit code 0 | Deploy is verified (URL/status/release SHA) or reported failed |
| Deploy scripts appear next to the ones that already exist | Detect-first; never scaffolds over working tooling |
| Secrets get pasted into config | Secrets referenced by **name** only; never printed, never committed |

## Usage

| Invocation | Behavior |
|------------|----------|
| `/deploy` | Detect → plan → confirm → deploy the default environment |
| `/deploy <env>` | `staging`, `production`, `preview`, … |
| `/deploy --dry-run` | Exact commands + target; **no outward action** |
| `/deploy --status` | Configured tooling, remotes/targets, last deploy — read-only |
| `/deploy --setup` | Interview + install tooling; **never deploys in the same run** |
| `/deploy --target <name>` | Setup hint: GitHub Pages, Vercel, DigitalOcean, GoDaddy, Fly, S3, SSH, … |
| `/deploy --rollback` | Previous release via the tool's **native** rollback |
| `/deploy --yes` | Skip the confirm (target line still printed) |
| `/deploy --allow-dirty` | Ship an uncommitted tree (risk line printed) |
| `/deploy --no-prep` | Skip the `/commit-prep` suggestion |

## Pipeline

```text
resolve project → tree + branch gate → integration-branch gap check → detect tooling
  → (none detected: interview → setup → stop)
  → resolve target/env → plan commands
  → confirm (or --dry-run / --yes)
  → deploy → verify → footer
```

If the project has an integration branch (`dev`, else `develop`) with commits
not yet promoted to the branch this deploy publishes from, `/deploy` reports
the gap and asks whether to run [`/review`](/skills/review) first, deploy the
current branch as-is, or cancel — under `--yes` it defaults to deploying
as-is. `/deploy` never merges or promotes branches itself; landing `dev` stays
`/review`'s job.

## Detection bands

First match wins, top down:

| Band | Markers | Deploy with |
|------|---------|-------------|
| **A — project entrypoint** | `make deploy`, `just deploy`, `npm run deploy`, `scripts/deploy*` | That command (it usually wraps the rest) |
| **B — CI/CD** | `.github/workflows/*deploy*`, `.gitlab-ci.yml` deploy stage, Jenkins/CircleCI | **`git push` is the deploy** (or `gh workflow run`), then watch the run |
| **C — platform CLI** | `vercel.json`, `netlify.toml`, `fly.toml`, `.do/app.yaml`, `wrangler.toml`, `serverless.yml`, `Procfile` | `vercel` / `netlify` / `flyctl` / `doctl` / `wrangler` / `serverless` / `git push heroku` |
| **D — release framework** | `deploy.php` (Deployer), `Capfile`, `config/deploy.yml` + `.kamal/`, `fabfile.py`, `ansible/`, `.goreleaser.yml`, `helm/`, `k8s/` | `dep deploy` / `cap deploy` / `kamal deploy` / `fab` / `ansible-playbook` / … |
| **E — package publish** | `pyproject.toml`, library `package.json`, `Cargo.toml` | `twine` / `npm publish` / `cargo publish` — always confirmed (irreversible) |
| **F — plain remote** | remote named `production` / `deploy` / `dokku` | `git push <remote> <branch>` |

Terraform is treated as **infra, not app deploy**: only on an explicit ask,
`plan` before `apply`, never `destroy`.

## When nothing is detected

`/deploy` asks three questions — **where** (GitHub Pages · Vercel · Netlify ·
Cloudflare · DigitalOcean · Fly · AWS · GoDaddy/shared hosting · VPS over SSH ·
a package registry), **who runs it** (CI or a human), and **which environments**
— then picks by stack:

| Stack | Framework of choice |
|-------|---------------------|
| PHP | **Deployer** (`deploy.php`) |
| Ruby | **Capistrano**, or **Kamal** if containerized |
| Node (server) | **Kamal**, or **Shipit** / PM2 deploy |
| Node/static front-end | Vercel · Netlify · Cloudflare Pages · GitHub Pages Action |
| Python (app) | **Fabric** or **Ansible**; Kamal if containerized |
| Python (package) | `twine` / `poetry publish` in a release workflow |
| Go / Rust binary | **goreleaser**, or Kamal / rsync+systemd for services |
| Any containerized app | **Kamal** |

**Deployer's model is the bar for every SSH-style target, in any language:**
timestamped `releases/` directories, shared `storage`/`uploads`/`.env` symlinked
across releases, an atomic `current` symlink flip, keep N old releases, and a
one-command rollback. Where no such framework exists for the stack, `/deploy`
reproduces that shape rather than rsyncing over a live directory.

Setup writes config, a CI workflow when CI deploys, a `deploy` task-runner entry,
docs for the required secret **names**, and then runs the tool's dry-run and
**stops**. Deploying takes a second, deliberate `/deploy`.

## Safety

- Dirty tree refused by default — deploy committed, reproducible state
- Target (host / URL / env / branch / SHA) printed and confirmed before the first
  remote command; production prints a risk line even under `--yes`
- Never commits, merges, promotes branches, or force-pushes — landing work is
  [`/review`](/skills/review)
- No `terraform destroy`, no dropping databases, no deleting remote resources, no
  `--force` deploy flags
- Secrets referenced by name; never printed, never committed
- Verified after the fact — a failed health check is a failed deploy, with
  rollback offered

## Scaffolded?

Yes — dual-use Claude command + Grok skill (`scripts/anchor.py` platform lists).

Full contract: source `.claude/commands/deploy.md` / `.grok/skills/deploy/SKILL.md`.
