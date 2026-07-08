# CLAUDE.md — working in the Anchor repo

This repo's purpose: help less-powerful models behave like Mythos-class models via structured prompting, orchestration, and verification. Read `anchor/ANCHOR.md` first — and practice it while working here.

- Doctrine + templates: `anchor/`
- Per-platform instructions: `platforms/` (the reusable CLAUDE.md for OTHER repos is `platforms/claude-code/CLAUDE.md`)
- Hardware tiers: `hardware/{personal-devices,h100,space-1-vera-rubin}/`
- Fleet tooling: `scripts/` (registry: `scripts/endpoints.yaml`), MCP servers: `mcp/`
- Docs site: `docs/` (Docusaurus; `npm install && npm start`)

Conventions: Python 3.10+, OpenAI-compatible endpoints only, model quirks belong in `anchor_client.py` quirks handling (never in callers). Docs pages mirror repo files — update both when changing doctrine.
