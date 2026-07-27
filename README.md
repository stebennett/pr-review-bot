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
| **Actually post it** | `review.py owner/repo#42 --post` |

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
  "max_review_lines": 3000
}
```

`max_rounds` is when to give up re-reviewing and leave it to a human. `max_review_lines` is
the point past which a PR is parked with "split this up" instead of reviewed — a diff too
big to review carefully is too big to review at all.

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

Roughly **$0.11 per PR** on the defaults for a ~30k-token diff: about 5k tokens of doctrine
per lens plus the diff, three times over, plus adjudication.

Levers, cheapest first: `--lens` to run fewer reviewers, a smaller `MODEL_LENS`,
`max_review_lines` to skip the giants, and `max_reviews_per_pass` to bound a queue run.

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

**Watch a `DRY_RUN=1` pass before you let it post.** It does the full run, model calls
included, and prints the review body and every inline comment instead of sending them.

---

## Current limits

**Review-only.** It never merges, pushes, labels or edits. An `approve` verdict posts an
approving review and stops.

**The lenses see only the diff.** No repository checkout, so a reviewer cannot go and read
the function being called two files away. They are told not to speculate about code they
cannot see — a finding that depends on something outside the diff must be dropped or marked
unverified.

`craft` loses the most to this: *"does this duplicate a utility we already have?"* is not
answerable from a diff alone. Expect thinner craft findings than the design intends. Giving
the lenses a read-only tool loop is the obvious next step; the models support it.

**Requirements are the PR body.** There is no issue-link following, so the `requirements`
lens judges conformity against what the PR description claims. A thin PR body makes for a
thin requirements review.

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
