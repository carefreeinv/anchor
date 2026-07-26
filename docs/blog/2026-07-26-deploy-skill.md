---
title: "/deploy — ship with the tooling the project already has"
authors: [carefree]
tags: [feature, skills]
---

Every project already has a way to go live — a workflow file, a `vercel.json`, a
`deploy.php`, or just a `production` remote someone pushes to. **`/deploy`**
finds that path and runs it. It only proposes tooling when a project genuinely
has none.

<!-- truncate -->

## The failure mode

Ask an agent to "deploy this" and the usual outcome is an invention: a fresh
`deploy.sh` that `rsync`s over a live directory, next to the GitHub Actions
workflow that was already doing the job correctly. Or the opposite — a `git
push` reported as a deploy, with nobody checking whether the pipeline it fired
went green.

`/deploy` is **detect-first**. Nothing gets scaffolded into a project that
already has a deploy path.

## Detection, in bands

First match wins, top down:

| Band | Markers | The deploy is |
|------|---------|---------------|
| **A — project entrypoint** | `make deploy`, `npm run deploy`, `scripts/deploy*` | that command (it usually wraps the rest) |
| **B — CI/CD** | `.github/workflows/*deploy*`, GitLab `deploy` stage, Jenkins | **`git push`** — or `gh workflow run` — then watch the run |
| **C — platform CLI** | `vercel.json`, `netlify.toml`, `fly.toml`, `.do/app.yaml`, `wrangler.toml`, `serverless.yml`, `Procfile` | that CLI |
| **D — release framework** | `deploy.php` (Deployer), `Capfile`, `.kamal/`, `fabfile.py`, `ansible/`, `.goreleaser.yml` | `dep deploy`, `cap deploy`, `kamal deploy`, … |
| **E — package publish** | `pyproject.toml`, library `package.json`, `Cargo.toml` | twine / npm / cargo — always confirmed, since registries do not take it back |
| **F — plain remote** | a remote named `production`, `deploy`, `dokku` | `git push <remote> <branch>` |

Band B is the common case and the one agents get wrong most often: when CI
deploys, **the push is the deploy**, and the skill treats `gh run watch` as part
of the operation rather than a nicety. Terraform is deliberately classified as
infra, not app deploy — explicit ask only, `plan` before `apply`, never
`destroy`.

## When there is no tooling

Then, and only then, `/deploy` stops and asks three questions: **where** should
this live (GitHub Pages, Vercel, Netlify, Cloudflare, DigitalOcean, Fly, AWS,
GoDaddy or other shared hosting, a VPS over SSH, a package registry), **who**
runs the deploy (CI or a human), and **which environments** you need now.

The answer plus the stack picks the framework — Deployer for PHP, Capistrano or
Kamal for Ruby, Kamal or Shipit for Node servers, Fabric or Ansible for Python,
goreleaser for Go and Rust binaries, a Pages/Vercel/Netlify build for static
front-ends.

## Deployer is the bar, in every language

Deployer earned its reputation with a model worth copying: timestamped
`releases/` directories, shared `storage`/`uploads`/`.env` symlinked across
them, an atomic `current` symlink flip, keep N old releases, and `dep rollback`
when the new one is bad.

`/deploy` treats that shape as the **minimum for any SSH-style target,
regardless of language**. If the ecosystem has a framework that provides it, use
the framework. If it doesn't, reproduce the shape — release directory, symlink
swap, prune — rather than rsyncing over a directory users are currently reading
from. A deploy that cannot be undone in one command is not finished.

## Guardrails

- **Committed code only.** A dirty tree is refused by default; `--allow-dirty`
  ships it anyway with a printed risk line.
- **Nothing remote before a confirm.** Target, environment, branch, and SHA are
  printed first. Production prints its risk line even under `--yes`.
- **No branch surgery.** `/deploy` never commits, merges, promotes, or
  force-pushes — landing work stays with [`/review`](/skills/review).
- **No destructive infra.** No `terraform destroy`, no dropped databases, no
  deleting remote resources, no `--force` deploy flags.
- **Secrets by name.** Required credentials are named, never printed, never
  committed.
- **Verified, not assumed.** Exit code 0 is not a deploy. The URL answers, or the
  platform reports the release live, or the released SHA matches HEAD — a failed
  check is a failed deploy, with rollback offered.

## Try it

```bash
/deploy --status      # what tooling is configured here, and where it points
/deploy --dry-run     # the exact commands and target, no outward action
/deploy staging       # plan → confirm → deploy → verify
/deploy --setup       # no tooling? interview, install, dry-run, stop
/deploy --rollback    # native rollback for whichever tool is in use
```

`--setup` never deploys in the same run. It writes config, documents the secret
names you need to set, runs the tool's own dry-run, and stops — shipping takes a
second, deliberate `/deploy`.

Docs: [`/deploy`](/skills/deploy). Sources: `.claude/commands/deploy.md` and
`.grok/skills/deploy/SKILL.md`, both scaffolded into projects by `anchor`.
