---
name: deploy
description: >
  Deploy the current project using the deployment tooling that project already
  uses (CI push-to-deploy, platform CLI, Deployer/Capistrano/Kamal, plain git
  remote). When no tooling exists, ask where it should deploy and set up the
  framework that best fits the stack. Use when the user runs /deploy, asks to
  ship/release/publish this project, push to production, or set up deployment.
argument-hint: "[env|--dry-run|--status|--setup|--target <host>|--rollback|--yes|--allow-dirty|--no-prep]"
disable-model-invocation: false
metadata:
  short-description: "Deploy with the project's own tooling; set it up if missing"
---

# /deploy — ship this project with its own tooling

Deploy the **current project** using **the deployment tooling that project already
uses**. Detect first, deploy second. When a project has **no** deployment tooling,
stop and ask where it should be deployed, then set up the tooling that best fits
its stack — never invent a one-off shell script when the ecosystem has a real
deployment framework.

This is **not** a provisioning/infra-as-code skill, not a release-management
product, and not a substitute for `/review`. Home: **one project, one target, one
deploy per invocation.**

`$ARGUMENTS` is everything after `/deploy`.

## Usage

| Invocation | Behavior |
|------------|----------|
| `/deploy` | Detect tooling → plan → confirm → deploy the project's **default** environment |
| `/deploy <env>` | Same, for a named environment (`staging`, `production`, `preview`, …) |
| `/deploy --dry-run` | Detect + print the exact commands and target; **no outward action** |
| `/deploy --status` | What tooling is configured, which remotes/targets exist, last deploy — read-only |
| `/deploy --setup` | Interview + install deployment tooling; **never deploys in the same run** |
| `/deploy --target <name>` | Setup hint: GitHub Pages, Vercel, Netlify, DigitalOcean, GoDaddy, Fly, S3, self-hosted SSH, … |
| `/deploy --rollback` | Previous release via the tool's **native** rollback |
| `/deploy --yes` | Skip the pre-deploy confirm (still print the target line first) |
| `/deploy --allow-dirty` | Deploy with uncommitted changes (prints a risk line) |
| `/deploy --no-prep` | Skip the `/commit-prep` suggestion gate |

Flags may combine (e.g. `/deploy staging --dry-run`).

## Hard rules

1. **Detect before you build.** Never scaffold deployment tooling into a project
   that already has some. If detection finds any configured path, **use it** —
   your job is to run the project's deploy, not to modernize it.

2. **Deploying is outward-facing.** Print the resolved target (host / URL /
   environment / branch / commit SHA) and get an explicit confirm before the first
   command that touches anything remote. `--yes` waives the prompt, not the
   printed target line. **Production always prints the risk line**, even with
   `--yes`.

3. **Ship committed code.** Refuse a dirty tree by default:

   ```text
   skip: /deploy — working tree dirty (N files); deploying untracked state is unreproducible
   → commit on the feature branch (/commit-prep, then /work discipline) and re-run
   → /deploy --allow-dirty to ship the tree as-is
   ```

   Never `git commit`, merge, or promote branches from `/deploy`. Landing work is
   `/review`'s job. If gates were never run on this HEAD, suggest `/commit-prep`
   once (skipped by `--no-prep`) — suggest, don't block.

4. **No destructive or irreversible infra actions.** No `terraform destroy`, no
   dropping/migrating-down databases, no deleting remote resources, no
   `--force`/`-f` deploy flags, no force-push, no rewriting remote history. Data
   migrations run only when the project's own deploy pipeline already runs them.

5. **Never handle secrets carelessly.** Do not print tokens, keys, or `.env`
   contents; do not commit credentials; do not write secrets into deploy config.
   Reference existing env vars / CI secrets / secret managers by **name**. When a
   required credential is missing, stop and tell the human exactly which one and
   where it goes.

6. **Setup is opt-in and separate.** `--setup` (and the no-tooling interview)
   writes config and a dry run, then **stops**. A deploy needs a second,
   deliberate `/deploy`.

7. **One target per invocation.** Never fan out to multiple environments, never
   chain `staging` → `production` in one turn.

## Pipeline (hard order)

```text
resolve project → tree + branch gate → integration-branch gap check → detect tooling
  → (none detected: interview → setup → stop)
  → resolve target/env → plan the exact commands
  → confirm (or --dry-run / --yes)
  → deploy → verify → footer
```

## 1. Resolve project + gate the tree

CWD, then git root. Print the absolute path. Report branch, HEAD SHA, and
`git status --porcelain` count. Apply Hard rule 3.

Note which branch the project deploys from if the tooling declares one (an Actions
`on: push: branches:` list, `vercel.json` git config, a `production` remote). If
HEAD is not on that branch, say so and confirm before proceeding.

**Integration-branch gap check.** If the project has an integration branch
(`dev`, else `develop` — same convention `/work` uses), compare it against the
branch this deploy actually publishes from (usually `main`/`master`):

```bash
git rev-list --count <deploy-branch>..dev   # or develop
```

No such branch, or the count is `0` → nothing to report, continue silently. A
non-zero count means `dev` has commits not yet promoted to the deploy branch —
report the count and a short `git log <deploy-branch>..dev --oneline`, then
**ask** (prefer `ask_user_question` when available):

| Option | Meaning |
|--------|---------|
| **Run `/review` first** (recommended) | Stop here; the human promotes `dev` → deploy branch via `/review`'s survey, then re-runs `/deploy` |
| **Deploy `<deploy-branch>` as-is** | Proceed; `dev`'s unpromoted work stays unpublished (a normal, non-broken state) |
| **Cancel** | Stop, no deploy |

Under `--yes` (non-interactive), default to **Deploy as-is** — note the gap in
the footer rather than blocking on a question nothing can answer. **`/deploy`
never merges or promotes branches itself** (Hard rule 3 / Out of scope) — this
check only surfaces the gap; landing `dev` is always `/review`'s job.

## 2. Detect deployment tooling

Read the markers; do **not** run anything yet. First match wins by band, top to
bottom.

### Band A — the project's own deploy entrypoint

| Marker | Deploy with |
|--------|-------------|
| `Makefile` `deploy:` / `Justfile` `deploy` / `Taskfile.yml` | `make deploy` / `just deploy` / `task deploy` |
| `package.json` scripts: `deploy`, `release`, `publish` | `npm run deploy` (match the lockfile's runner) |
| `composer.json` scripts `deploy` | `composer deploy` |
| `scripts/deploy*`, `bin/deploy*`, `deploy.sh` | Read it first, then run it |

A project-authored entrypoint is the authority — it usually wraps the tools below.

### Band B — CI/CD is the deployer (push-to-deploy)

| Marker | Deploy with |
|--------|-------------|
| `.github/workflows/*` with `deploy`/`pages`/`release` jobs | Push the deploy branch, or `gh workflow run <file>` for `workflow_dispatch` |
| `.gitlab-ci.yml` with a `deploy` stage | Push, or trigger the pipeline job |
| `.circleci/config.yml`, `Jenkinsfile`, `bitbucket-pipelines.yml` | Push the tracked branch |
| `.buildkite/`, `azure-pipelines.yml` | Push / trigger per that config |

Here **`git push` is the deploy** — Hard rule 2 still applies (print branch,
remote, SHA, and which workflow it fires). After pushing, watch the run when the
CLI allows (`gh run watch`) and report its conclusion.

### Band C — platform CLI configured in-repo

| Marker | Deploy with |
|--------|-------------|
| `vercel.json`, `.vercel/` | `vercel deploy` (`--prod` for production) |
| `netlify.toml`, `.netlify/` | `netlify deploy` (`--prod`) |
| `fly.toml` | `flyctl deploy` |
| `.do/app.yaml`, `.do/deploy.template.yaml` | `doctl apps create-deployment <id>` |
| `app.yaml` + `gcloud` config / `firebase.json` | `gcloud app deploy` / `firebase deploy` |
| `wrangler.toml` | `wrangler deploy` / `wrangler pages deploy` |
| `serverless.yml` | `serverless deploy --stage <env>` |
| `samconfig.toml` / `template.yaml` (SAM) | `sam deploy` |
| `Procfile` + `heroku`/`dokku` remote | `git push heroku <branch>` |
| `render.yaml`, `railway.json`, `.platform.app.yaml` | That platform's CLI |

### Band D — release-framework / SSH deploys

| Marker | Deploy with |
|--------|-------------|
| `deploy.php`, `deploy.yaml` (**Deployer**) | `dep deploy <stage>` (`vendor/bin/dep` if local) |
| `Capfile`, `config/deploy.rb` (**Capistrano**) | `cap <stage> deploy` |
| `config/deploy.yml` + `.kamal/` (**Kamal**) | `kamal deploy -d <env>` |
| `fabfile.py` (**Fabric**) | `fab deploy` |
| `ansible/`, `playbook*.yml`, `inventory*` | `ansible-playbook -i <inv> <playbook>` |
| `.shipitfile.js` / `shipit.js` (**Shipit**) | `shipit <env> deploy` |
| `ecosystem.config.js` (PM2 deploy block) | `pm2 deploy production` |
| `.goreleaser.yml` | `goreleaser release` |
| `docker-compose.prod.yml` / `Dockerfile` + registry config | The project's documented image push + remote pull |
| `helm/`, `k8s/`, `kustomization.yaml` | `helm upgrade --install` / `kubectl apply -k` |
| `*.tf` (Terraform), `main.tf` | **Infra, not app deploy** — only with an explicit human ask; `plan` before `apply`; never `destroy` |

### Band E — package publication (a "deploy" for libraries)

`pyproject.toml`/`setup.py` → `twine upload` / `poetry publish`; `package.json`
(library, no app) → `npm publish`; `Cargo.toml` → `cargo publish`;
`composer.json` (package) → tag + push (Packagist). **Always** confirm: publishing
is irreversible on most registries.

### Band F — plain git remote

A remote named `production`, `deploy`, `dokku`, `live`, or a documented
push-to-deploy hook → `git push <remote> <branch>`. This is the "simple case" the
skill should take when it genuinely is the project's mechanism.

**Report what you found** as a short table (marker → tool → command → confidence)
before doing anything. If two bands both look live (e.g. an Actions deploy *and* a
`vercel.json`), say so and let the human pick — the CI path usually wins.

## 3. Nothing detected → ask, then set up

Do **not** guess a host. Ask (platform ask UI when available):

1. **Where should this deploy to?** — GitHub Pages · Vercel · Netlify ·
   Cloudflare Pages · DigitalOcean (App Platform or Droplet) · Fly.io · AWS
   (S3+CloudFront / ECS / Lambda) · GoDaddy or other shared hosting (SSH/SFTP) ·
   Self-hosted VPS over SSH · A package registry (PyPI/npm/crates) · Other
2. **Who runs the deploy?** — CI on push · a human running a local command
3. **Which environment(s) now?** — production only · staging + production

That answer plus the stack determines the tooling. Prefer a **real deployment
framework** over ad-hoc scripts.

### Pick the tool: stack × target

| Stack | Framework of choice | Why |
|-------|---------------------|-----|
| **PHP** | **Deployer** (`deploy.php`) | Atomic releases, shared dirs, one-command rollback; recipes for Laravel/Symfony/WordPress |
| **Ruby** | **Capistrano**, or **Kamal** if containerized | Same release/symlink model, mature recipes |
| **Node (server)** | **Kamal** (Docker) or **Shipit** / PM2 deploy | Shipit is the Node-side Capistrano/Deployer analogue |
| **Node/static front-end** | Vercel · Netlify · Cloudflare Pages · GitHub Pages Action | Build + CDN is the deploy |
| **Python (app)** | **Fabric** (fabfile) or **Ansible**; **Kamal** if containerized | Fabric is Python's SSH-task deployer |
| **Python (package)** | `twine` / `poetry publish` via a release workflow | |
| **Go / Rust (binary)** | **goreleaser**, or Kamal/rsync+systemd for services | |
| **Any containerized app** | **Kamal** | Closest modern analogue to Deployer: zero-downtime, rollback, no control plane |
| **Anything, CI-driven** | GitHub Actions workflow calling the above | Keeps the local command and CI identical |

**Deployer's model is the bar for every SSH-style target**, whatever the language:
releases in timestamped directories, shared `storage`/`uploads`/`.env` symlinked
across releases, an atomic `current` symlink flip, **keep N old releases**, and a
one-command **rollback**. If the ecosystem has no such framework, reproduce that
shape (rsync into `releases/<ts>`, symlink flip, prune) rather than rsyncing over
a live directory.

### Target notes worth getting right

| Target | Set up |
|--------|--------|
| **GitHub Pages** | `.github/workflows/deploy-pages.yml` using `actions/configure-pages` + `upload-pages-artifact` + `deploy-pages`, `permissions: pages: write, id-token: write`. Set the site base path in the generator's config |
| **Vercel / Netlify / Cloudflare Pages** | Prefer the **Git integration** (push = deploy) and commit only `vercel.json` / `netlify.toml` / `wrangler.toml`; CLI + token in CI when the human wants explicit deploys |
| **DigitalOcean** | App Platform → `.do/app.yaml` + `doctl apps`; Droplet → Kamal or Deployer/Capistrano over SSH |
| **GoDaddy / cPanel shared hosting** | SSH available → Deployer (`deploy.php`) with releases + `current` symlink. FTP/SFTP only → an rsync/lftp deploy in CI with credentials as CI secrets; still deploy into a fresh dir and swap |
| **Fly.io** | `fly launch` → commit `fly.toml`; `flyctl deploy` locally or in CI |
| **AWS S3 + CloudFront** | Sync to the bucket, then a CloudFront invalidation; credentials via OIDC role in CI, never keys in the repo |
| **Self-hosted VPS** | Kamal (Docker) or Deployer-class SSH releases; systemd unit + health check |

### Setup deliverables

Write only what the choice needs, and match the repo's conventions:

- The tool's config file(s) — hosts, paths, environments, build command
- A CI workflow when CI is the deployer
- **Secrets by reference only** — document required env/CI secret **names** in
  `README`/`docs`; add local secret files to `.gitignore`
- A `deploy` entrypoint (`make deploy` / `npm run deploy`) when the project
  already uses a task runner
- A short **README/docs** section: how to deploy, how to roll back, what to set
- A CHANGELOG line if the project keeps one (shipped tooling, not a plan)

Then run the tool's **check/dry-run** (`dep deploy --dry-run`, `vercel build`,
`kamal config`, `ansible-playbook --check`, `terraform plan`) and **stop**. Report
what to set (secrets, DNS, first-run steps) and tell the human to re-run
`/deploy`.

## 4. Plan, confirm, deploy

1. **Plan:** print environment, target host/URL, branch + SHA, the exact commands
   in order, and what is irreversible (registry publish, DNS change, migration).
2. **Preflight:** required CLI on PATH and authenticated (`vercel whoami`,
   `flyctl auth whoami`, `gh auth status`, `ssh -o BatchMode=yes <host> true`),
   build passes if the deploy builds locally, required env/secret **names**
   present. Missing tool or auth → stop with the install/login command; do not
   silently install global tooling.
3. **Confirm** (Hard rule 2) unless `--dry-run` (never deploys) or `--yes`.
4. **Run** the commands as planned, non-interactively where the tool supports it.
   Stream/summarize output; on failure, stop at the first failing step and report
   the command, exit code, and stderr tail. **Two** fix attempts on the same
   failure, then surface it — don't thrash, and never "fix" a deploy by disabling
   checks, forcing, or bypassing hooks.

## 5. Verify

Confirm the deploy actually landed — never report success from a zero exit code
alone when a cheap check exists:

- The deployment URL responds (`curl -sSI <url>`) with an expected status
- The platform reports the release live (`vercel ls`, `flyctl status`,
  `kubectl rollout status`, `gh run watch`, `dep releases`)
- The released SHA/version matches HEAD

Failed verification is a **failed deploy** — say so, and offer rollback.

## 6. Rollback

`/deploy --rollback` uses the tool's native path — `dep rollback`, `cap <stage>
deploy:rollback`, `kamal rollback`, `vercel rollback` / re-alias the previous
deployment, `flyctl releases` + `flyctl deploy --image <prev>`, `helm rollback`,
`kubectl rollout undo`, re-run CI on the previous SHA. Print what will become live
and confirm first. Where no native rollback exists, say so plainly rather than
improvising a destructive fix.

## 7. Footer

```text
## Result
## How to verify
## Deferred / concerns
```

Include: project path, environment + target, branch/SHA deployed, tooling used
(detected or newly set up), commands run, verification result (URL + status), and
anything the human must do (set a secret, point DNS, approve a protected
environment).

## Out of scope

- Provisioning infrastructure from scratch (servers, DNS zones, clusters, IAM)
- Committing, merging, or promoting branches (`/work`, `/review`)
- Running the test suite as a deploy step (`/commit-prep` owns gates)
- Database migrations beyond what the project's own deploy already runs
- Rotating, generating, or storing credentials
- Multi-environment or multi-project fan-out in one invocation

## Quick discovery

```bash
git status --porcelain && git branch --show-current && git rev-parse --short HEAD
git remote -v
ls deploy.php deploy.yaml Capfile fly.toml vercel.json netlify.toml \
   serverless.yml wrangler.toml Procfile .kamal config/deploy.yml \
   .do/app.yaml fabfile.py .goreleaser.yml 2>/dev/null
ls .github/workflows 2>/dev/null
grep -nE '"(deploy|release|publish)"' package.json composer.json 2>/dev/null
grep -nE '^(deploy|release|publish):' Makefile Justfile 2>/dev/null
command -v dep cap kamal vercel netlify flyctl doctl wrangler gh
```
