---
title: A rule you can't follow gets skipped, so we scoped it to what a commit contains
authors: [carefree]
tags: [doctrine, skills, tooling]
---

Anchor's hard rule used to read: run `/commit-prep` before **any** commit. `/review`
had been ignoring it for months.

<!-- truncate -->

Not out of laziness — the skill referenced `commit-prep` exactly zero times in
either the Claude or the Grok copy, while running four separate paths that touch
git. It created merge commits in both directions, and it staged plan-lane renames
and review notes without ever committing them.

That was invisible here, because this repo gitignores its entire `.plans/` tree. A
project scaffolded from Anchor **tracks** it — the scaffold ignores only
`**/*.local.md` and `.leases/` — so over there, every `/review` left staged plan
bookkeeping lying around for whatever unrelated commit came next to swallow.

## The rule was the problem

The obvious fix is to make `/review` run the full three-gate prep. That is also the
wrong fix. A lane move is a `git mv` from one directory to another; it cannot break
a test, it needs no CHANGELOG entry, and it has nothing to announce. Demanding
tests, a changelog and a blog decision before renaming a file is how you teach an
operator that the skill is optional.

So the rule is now scoped by **what a commit contains**, not by the fact that it is
a commit:

- Any commit touching a path **outside** `.plans/` — prep first.
- Any **merge** commit — prep first.
- A commit whose paths are **entirely** under `.plans/` — light path: say what moved
  and why, then commit.

## The light path has a load-bearing flag order

```bash
git add .plans/
git commit -m "Plans: <slug> → <lane> (/review Approve)" -- .plans/
```

The pathspec keeps an unrelated pre-staged file out of an ungated commit. But note
where it sits. Everything after `--` is a pathspec, so the reversed form —
`git commit -- .plans/ -m "…"` — treats `-m` and the message as *filenames*. It
exits without complaint and commits nothing. We shipped that form, twice, because
reading a command is not running one. There is now a test that runs the command
exactly as the skills ship it, against a throwaway repo, and fails if it succeeds
without producing a commit.

This is also the one commit allowed to land on an integration branch rather than a
feature branch — `/review`, `/work` and `/draft --promote` each make it on whichever
branch the lane move exists on. And it must never run while a merge is staged: git
refuses a partial commit mid-merge, and the tempting repair of dropping `-- .plans/`
would commit the **whole staged merge** under a `Plans:` message.

## A merge commit is gated before it exists

A clean textual merge can still be semantically broken, and the merged tree is state
neither branch was ever prepped in. So the merge is staged, prepped, and only then
committed:

```bash
git merge --no-ff --no-commit feature/<slug>
# run /commit-prep against the merged working tree
#   green → git add -A && git commit -m "Merge feature/<slug>: <title>"
#   red   → git merge --abort || git reset --hard HEAD
```

Both halves of that are more subtle than they look. `git add -A` matters because
prep **edits the working tree** — a bare `git commit` commits only the index and
silently drops prep's own output. And `git merge --abort` *refuses*, with
`error: Entry '<path>' not uptodate`, once prep has modified a file involved in the
merge — which is precisely what its fix-the-tests gate does. Hence the reset
fallback.

One honest correction to what we wrote earlier: the reset does not discard
everything prep did. It restores **tracked** files, so a new blog post prep created
survives as untracked. Check `git status` and decide about it deliberately, rather
than assuming a clean slate.

A fast-forward creates no commit at all, and its content is byte-identical to what
was already prepped on the branch, so it needs no additional gate.

## `merge_feature.py` was reporting merges it hadn't made

Anchor's own scoped-merge tool is bound by the same rule, and it was breaking it in
a way that looked like success. When a merge could not fast-forward, `land()`
correctly staged it and stopped — and the CLI printed:

```text
merged; dev is now STAGED.
```

and exited `0`. Every caller was told a merge had landed while the checkout sat
mid-merge with nothing committed, and no documented way to finish or undo it.

A staged merge now exits **`6`** — neither success nor failure — and says so:

```text
STAGED: dev has the merge staged, NOT committed.
  Run /commit-prep against the merged tree, then finish it:
    green -> python scripts/merge_feature.py --root . --commit-staged
    red   -> python scripts/merge_feature.py --root . --abort-staged
```

`--commit-staged` stages prep's own edits along with the merge, commits both, and
returns you to the branch you started on. `--abort-staged` unwinds it, with the
`reset --hard` fallback for the refusing case above. The tool records the pending
merge under `.git/`, so the finishing run knows which branch to restore without
being told. The fast-forward path is unchanged and still reports a real SHA.

## Tests that read the documents

Every one of these defects recurred in a file no test read. So the anti-rot test now
reads the platform briefs and the docs mirrors too, not just the skills — and it
checks proximity **per command** rather than per file. One `/commit-prep` mention
next to the first git command used to satisfy an entire document, leaving every
later commit-creating command unguarded. That is exactly how the merge path shipped
ungated in the first place.
