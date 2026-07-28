# pr-review-bot

Reviews GitHub pull requests with a three-lens agent panel, calling OpenRouter directly.

One dependency-free Python script and a directory of prompts. No framework, no agent
runtime, no virtualenv, no build step.

```bash
export GH_TOKEN=$(gh auth token)
export OPENROUTER_API_KEY=sk-or-...
python3 review.py owner/repo#42 -v
```

That does a full review and prints it. **Nothing is posted to GitHub unless you pass
`--post`.**

---

## How it works

Three independent reviewers ("lenses") read the diff in parallel, each through one fixed
concern and blind to the other two. An adjudicator then reconciles their findings into a
single verdict and writes the review a human actually reads.

| Lens | Asks |
|---|---|
| `requirements` | Does this do what the PR says it does — no more, no less? |
| `correctness` | Is it right? What breaks, and with what input? |
| `craft` | Is it built the way this codebase builds things? |

The adjudicator **never sees the diff**. It sees only what the lenses claim about it. That
is deliberate: giving it the code would invite a fourth, unaccountable review with none of
the panel's scope discipline. Here the constraint is structural — it has no tools and the
diff is not in its context.

### Only four steps need a model

Everything else is ordinary code, and that is the point of this repo:

| Step | |
|---|---|
| pick candidate PRs, triage, count rounds, fetch the diff | code |
| the three lenses | **3 model calls, parallel** |
| adjudication | **1 model call** |
| post the review, report | code |

The design started life as a Claude Code plugin, where all of this ran as agents. Most of
it turned out to be an algorithm written in English because the runtime happened to be an
agent. As code it is deterministic, debuggable, and free.

The payoff: **each call names its own model**, so a cheap model can do mechanical work
while a stronger one adjudicates. Single-agent runtimes generally cannot express that.

### No state, anywhere

Round numbers and the last-reviewed commit are recovered from a hidden marker the
adjudicator writes into its own review body:

```html
<!-- pr-reviewer: verdict=request-changes round=2 sha=abc1234 -->
```

No database, no labels, no files. Re-reviewing is idempotent: if the head SHA has not moved
since the last review, the PR is skipped.

---

## Install

Python 3.11+ and nothing else. `openssl` is needed only for GitHub App auth.

```bash
git clone git@github.com:stebennett/pr-review-bot.git
cd pr-review-bot
cp .env.example .env      # add your OPENROUTER_API_KEY
```

`review.py` finds `doctrine/` and `.env` beside itself, so it runs from anywhere.

---

## Usage

```
review.py [targets ...] [options]
```

Targets accept `owner/repo`, `owner/repo#42`, a PR URL, or an SSH remote. With no target it
falls back to `$TARGET_REPOS` (comma-separated) — that is how it runs unattended.

| Want to | Command |
|---|---|
| Review one PR, verbose | `review.py owner/repo#42 -v` |
| Re-review one you already reviewed | `review.py owner/repo#42 --force` |
| Queue pass over a repo's open PRs | `review.py owner/repo` |
| Iterate on prompts, no GitHub | `review.py --diff-file x.diff -v` |
| Cheapest loop — one lens | `review.py --lens craft --diff-file x.diff -v` |
| Capture output for comparison | `review.py owner/repo#42 --save out.json` |
| Try another model | `review.py owner/repo#42 --model-lens deepseek/deepseek-v4-flash` |
| Give a slow model longer | `review.py owner/repo#42 --timeout 600` |
| Review from the diff alone, no context pack | `review.py owner/repo#42 --no-context` |
| Read context from a local checkout instead of a tarball fetch | `review.py owner/repo#42 --worktree ~/code/owner-repo` |
| Disable prompt caching | `review.py owner/repo#42 --no-cache` |
| **Actually post it** | `review.py owner/repo#42 --post` |
| Run the test suite | `python3 -m unittest discover -s tests -t . -v` |

Naming a single PR is an instruction to review it, so the throughput and preference filters
are bypassed. Two exclusions are absolute and are never bypassed in any mode: **drafts**
(not yet offered for review) and **Renovate-authored PRs** (a dependency bot's PRs want a
different kind of scrutiny).

`--force` additionally bypasses the already-reviewed, `max_rounds` and `max_review_lines`
skips, which is what makes iterating against one PR practical.

### Offline mode

`--diff-file` touches no GitHub API and needs no token:

```bash
gh pr diff 42 > /tmp/x.diff
python3 review.py --diff-file /tmp/x.diff --lens craft -v
```

Grab a diff once, then iterate on doctrine wording for a fraction of a cent per run. This
is the right loop for tuning prompts.

---

## Configuration

Environment, or `.env` beside the script (real environment variables win):

| Variable | Default | |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required. |
| `GH_TOKEN` / `GITHUB_TOKEN` | — | Falls back to `gh auth token`. |
| `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY` | — | Use the App identity instead. |
| `MODEL_LENS` | `z-ai/glm-5.2` | The three reviewers. |
| `MODEL_VERDICT` | `deepseek/deepseek-v4-pro` | Adjudication. |
| `TARGET_REPOS` | — | Comma-separated, for unattended runs. |
| `DRY_RUN` | `1` | `0` posts. `--post` does the same. |
| `REQUEST_TIMEOUT` | `300` | Seconds per model request. |

### Per-repository

Drop `.claude/pr-reviewer.json` in the **repo being reviewed**:

```json
{
  "renovate_authors": ["renovate[bot]"],
  "exclude_authors": [],
  "require_label": null,
  "max_reviews_per_pass": 3,
  "max_rounds": 3,
  "max_review_lines": 3000,
  "ignore_paths": ["*.lock", "package-lock.json", "**/generated/**"],
  "cache": true,
  "context": true,
  "max_context_chars": 83000,
  "max_tarball_bytes": 50000000,
  "max_context_files": 25
}
```

`max_rounds` is when to give up re-reviewing and leave it to a human. `max_review_lines` is
the point past which a PR is parked with "split this up" instead of reviewed — a diff too
big to review carefully is too big to review at all.

`ignore_paths` excludes matching paths (glob, matched against the full path and the bare
filename) from the context pack — lockfiles and generated code by default. It is read now;
earlier versions declared it but never consulted it.

`context` turns the pack on or off (`--no-context` does the same from the CLI).
`max_context_chars` is the pack's total character budget, split across its four sections by
fixed shares; `max_context_files` caps how many changed files it reads in full.
`max_tarball_bytes` caps the size of the per-PR repo tarball fetched to build the pack — over
that, the fetch is abandoned and the pack falls back to fetching changed files individually
over the API. `cache` turns prompt caching on or off (`--no-cache` does the same from the
CLI); the CLI flag always wins over this setting.

### Authentication

Resolves in order: GitHub App → `GH_TOKEN`/`GITHUB_TOKEN` → `gh auth token`.

A user token is fine for reading and for reviewing other people's PRs. But **GitHub rejects
an `APPROVE` or `REQUEST_CHANGES` review submitted by the PR's own author** — so if you
want the bot to review PRs it (or you) opened, it needs its own App identity. That is the
whole reason App support exists here.

The App needs: **Pull requests** read & write, **Contents** read, **Metadata** read. No
write access to code.

---

## Cost

Measured, not estimated — two runs over the same real 642-line pull request, on the
defaults:

| Configuration | Effective input tokens | Relative to original |
|---|---|---|
| No pack, no caching (the original) | 69,160 | 1.00x |
| No pack, with caching | 40,936 | 0.59x |
| Pack, no caching | 113,246 | 1.64x |
| Pack + caching | 64,519 | 0.93x |

With caching actually landing, the full context pack is roughly cost-neutral against the
original diff-only design — 0.93x. But **caching is provider-dependent**: OpenRouter routes
each call to whichever upstream provider it picks, and one measured run was routed to a
provider that returned zero cached tokens, which makes **1.64x the real worst case**, not a
theoretical one. Routing is not even stable across a single pass — one early run saw four
different providers across five calls. Quote both numbers, not just the cost-neutral one, or
you will mislead whoever lands on a non-caching route.

Levers, cheapest first: `--no-context` to drop the pack entirely, `--lens` to run fewer
reviewers, a smaller `MODEL_LENS`, `max_review_lines` to skip the giants, and
`max_reviews_per_pass` to bound a queue run.

---

## Running it unattended

Set `TARGET_REPOS`, `DRY_RUN=0`, and run it on a schedule. It is stateless and idempotent,
so a cron entry, a systemd timer, a CI job or a Kubernetes CronJob all work equally well —
a pass with nothing new to review costs one cheap API call and exits.

A Kubernetes deployment lives in
[`home-lab-k8s`](https://github.com/stebennett/home-lab-k8s) under
`applications/pr-reviewer/`: a CronJob on a stock `python:3.13-slim` image with this script
and `doctrine/` mounted from a ConfigMap. No image build, because there are no dependencies
to install.

**The context pack needs outbound access to `codeload.github.com`.** Building it fetches a
repo tarball from `api.github.com/repos/.../tarball/...`, which redirects there; a network
policy that allows only `api.github.com` will block the tarball fetch on every PR. That
degrades to the per-file API fallback rather than failing the review, so it costs pack
quality, not correctness — but if you expect the full pack, allow the redirect target too.

**Watch a `DRY_RUN=1` pass before you let it post.** It does the full run, model calls
included, and prints the review body and every inline comment instead of sending them.

---

## Current limits

**Review-only.** It never merges, pushes, labels or edits. An `approve` verdict posts an
approving review and stops.

**The lenses get a bounded context pack, not a real checkout.** Alongside the diff, each
lens is given the changed files at head, a repo-wide grep for other call sites of what
changed, a conventions doc if the repo has one, and a path tree — assembled once per PR and
shared byte-for-byte across all three lens prompts. It is a substitute for a worktree, not
one: a lens still cannot follow an arbitrary import chain, and it is told not to speculate
about code no section shows it — a finding that depends on something outside the diff and
the pack must be dropped or marked unverified.

**Call sites are restricted to a fixed extension allowlist (`CODE_SUFFIXES`).** Currently
`.py`, `.pyi`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.go`, `.rs`, `.java`, `.kt`,
`.rb`, `.php`, `.cs`, `.swift`, `.scala`, `.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.sh`. A repo
whose code lives under an unlisted extension (`.vue`, `.svelte`, `.dart`, `.tf`, `.proto`,
`.ex`, `.erl`, `.clj`, `.lua`, `.jl`, an extensionless `Makefile`/`Dockerfile`, …) gets
nothing from the call-sites section — it degrades to silence, and silence reads exactly
like "this symbol has no callers." Grep matching is also purely textual, so a listed call
site can turn out to be unrelated on inspection.

**`--worktree` is validated, not trusted.** A directory that does not contain at least one
of the diff's pre-existing changed paths is treated as no checkout at all, with a note in
the log, rather than silently manufacturing a path tree and call sites from an unrelated
repository.

**Requirements now follow issue links.** `#123`-style references and full issue/PR URLs in
the title or body are resolved (up to 5 per PR) and folded in, along with human (non-bot)
PR comments, so the `requirements` lens judges conformity against more than the raw
description. A PR with no body and no linked issue still gets a thin requirements review —
there is nothing to fold in.

---

## Troubleshooting

**`OpenRouter rejected the credentials (HTTP 401)`** — the message OpenRouter returns for a
key it cannot parse is *"Missing Authentication header"*, which points at the wrong thing
entirely; a genuinely absent header says *"No cookie auth credentials found"*. So a 401
usually means the key value is mangled, not missing. The error prints a redacted
description of the key — length, first and last characters, and whether it contains
whitespace, a `#`, quotes, or the wrong provider prefix. Common causes: a trailing inline
comment in `.env`, or a key for a different provider (it should start `sk-or-`).

**It looks hung** — a non-streaming completion returns nothing until it is finished. A
heartbeat prints every 30 seconds per in-flight request, so silence longer than that is a
real problem, not a slow model. A lens over a 700-line diff should return in 30–120s, and
the three run in parallel, so the panel takes about as long as the slowest one.

**`response was not JSON despite response_format`** — a provider ignored structured output.
Requests set `provider.require_parameters: true` to route only to providers that honour it,
so this should be rare; the error names the provider and quotes what came back.

**A lens returns `needs-input`** — it could not review at all. That is a legitimate outcome
on, say, a docs-only PR reaching the `correctness` lens, and the adjudicator discloses the
reduced coverage in the review.

---

## Repository layout

```
review.py              everything: selection, triage, the four model calls, posting
doctrine/
  lenses/_shared.md    rules every lens follows, and the finding schema
  lenses/*.md          one brief per lens — the actual review standards
  verdict.md           adjudication rules and the review body template
  agents/*.md          role definitions, used as system prompts
```

**The doctrine is the interesting part.** `review.py` is plumbing; the review quality lives
in those markdown files. Tune them with `--diff-file` against a PR you know well, and read
the lens briefs before changing a model — they assume a reviewer that can follow a fair
amount of instruction.

The doctrine originates in the `pr-reviewer` plugin in
[`stebennett/nyx-claude`](https://github.com/stebennett/nyx-claude) and is carried here
close to verbatim, so improvements can flow both ways.
