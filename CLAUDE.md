# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single dependency-free Python script (`review.py`) plus a directory of prompts
(`doctrine/`) that reviews GitHub pull requests: three lens agents read the diff and a
deterministically-assembled context pack via OpenRouter, then one adjudicator turns their
findings into a GitHub review. No package manager, no virtualenv, no build step.

There is a test suite — stdlib `unittest`, four files under `tests/`:

```bash
python3 -m unittest discover -s tests -t . -v
```

It needs no install. `unittest` is standard library, and the deployment mounts only
`review.py` and `doctrine/`, so tests never ship. `tests/__init__.py` must exist and stay
empty, or that command fails with `ImportError: Start directory is not importable`.

## Commands

```bash
# full review of one PR, dry run, verbose (nothing is posted without --post)
python3 review.py owner/repo#42 -v

# re-review a PR already reviewed (also bypasses max_rounds / max_review_lines)
python3 review.py owner/repo#42 --force -v

# the prompt-iteration loop: no GitHub, no token, fractions of a cent per run
gh pr diff 42 > /tmp/x.diff
python3 review.py --diff-file /tmp/x.diff --lens craft -v

# same, but with a real context pack read from a local checkout
python3 review.py --diff-file /tmp/x.diff --worktree ~/code/owner-repo --lens craft -v

# capture envelopes + verdict + the pack for before/after comparison when tuning
python3 review.py --diff-file /tmp/x.diff --save /tmp/before.json

# review from the diff alone, or with caching off
python3 review.py owner/repo#42 --no-context
python3 review.py owner/repo#42 --no-cache

# actually post
python3 review.py owner/repo#42 --post
```

`review.py` resolves `doctrine/` and `.env` relative to its own file, so it runs from any
cwd. Auth resolves GitHub App → `GH_TOKEN`/`GITHUB_TOKEN` → `gh auth token`.

Unit tests cover the deterministic parts — diff parsing, budget accounting, the pack
assemblers, prompt-block composition. They cover nothing that calls a model. Verifying
review *quality* still means running the offline mode on a diff you know well, `--save`ing
both runs and comparing: `--no-context` against `--worktree <checkout>` to see what the pack
changes, and against `main` to see what a prompt change costs.

## Architecture

`review.py` is one file, sectioned by banner comments, and the pass runs top-down:

`main` → `select` (candidate PRs, triage) → `review_pr` (fetch diff, size check) →
`build_context` (checkout, assemble the pack) → `run_panel` (staggered `run_lens` calls,
then `adjudicate`) → `post_review`.

**Only four steps call a model** — the three lenses and the adjudication. Selection, triage,
round counting, diff fetching, the whole context pack, and posting are ordinary
deterministic code, and keeping them that way is the point of the repo. Prefer code over a
new model call.

**Each model call names its own model** (`--model-lens`, `--model-verdict`), so a cheap
model does the mechanical reviewing and a stronger one adjudicates. Don't collapse this.

**The adjudicator never sees the diff, and never sees the pack.** `adjudicate()` passes only
the lens envelopes, the PR body, the prior review body, and the resolved requirements. This
is structural, not stylistic — the design depends on it, and
`doctrine/agents/pr-review-verdict.md` explains why. Never add the diff or `ctx.pack` to
that prompt.

The resolved **requirements** string is the one deliberate exception: it reaches the
adjudicator exactly as the plain PR body did before, so the verdict can judge conformity
claims against what was actually asked. Because it lands in the verdict prompt, keep it
faithful to what humans wrote and add no framing of your own. An earlier version injected
"Requirements as stated by people, not by the description", which asserted a priority nobody
wrote; it was removed for that reason.

**There is no state anywhere.** Round number and last-reviewed SHA are recovered by
`prior_rounds()` from an HTML marker the adjudicator writes as the first line of its own
review body (`MARKER_RE`, and the format spec in `doctrine/verdict.md`). No database, no
labels, no files. Consequently: don't introduce persistence — if a new piece of state is
needed, it belongs in the marker.

### The context pack

`build_context` is a context manager owning one temp checkout for one PR. It fetches
`/repos/{repo}/tarball/{sha}` and extracts it with `tarfile` using `filter="data"` — that
filter is what refuses path traversal, and it is load-bearing on the 3.13 deployment where
`None` still means `fully_trusted`. Never remove it because a local test passes without it.

Four sections go into the prompt after the diff, each with its own character budget as a
fraction of `max_context_chars`:

- **Changed files at head** — whole file where it fits, hunk-centred windows where it
  doesn't, always line-numbered. Assembled by greedy admission in hunk-count order: keep
  each file whose cheapest rendering still fits, name the rest. It must never cause
  section-level truncation.
- **Call sites and importers** — definition-shaped names from the diff, grepped outside the
  changed files. Restricted to a `CODE_SUFFIXES` allowlist, so a repo whose code uses an
  unlisted extension gets nothing here — and silence is indistinguishable from "no callers".
- **Repo conventions** — `CLAUDE.md`/`AGENTS.md`/`CONTRIBUTING.md`, nearest-first by distance
  to a changed directory so a budget squeeze drops the least specific guidance. Each
  document is wrapped in a fence sized one backtick longer than any run inside it, so its own
  headings can't be mistaken for prompt structure.
- **Path tree** — pruned, not flat-truncated. Deliberately does *not* reuse `walk_source`:
  that walk is restricted to `CODE_SUFFIXES` for the grep's benefit, which would drop
  `README.md`, `Makefile` and every config file from a listing whose whole purpose is "what
  does this repo already have".

`--worktree` is validated against the diff's *pre-existing* changed paths. A directory that
isn't a checkout of the repo under review degrades to no checkout with a note, rather than
producing plausible-but-wrong context. Pre-existing paths, not all paths: a PR that only adds
files has none to check, and rejecting it would discard the pack for no reason.

`resolve_requirements` replaces what used to be `pr.get("body")` — the body plus up to five
linked issues plus human PR comments, bots filtered by both `type == "Bot"` and a `[bot]`
login suffix. It degrades locally on every GitHub failure so the body always survives.

`anchor_violations` reports findings anchored outside the diff. It logs them and never drops
them: a real bug at a slightly wrong line is worth more than a clean log, and `post_review`
already folds inline comments into the body on a 422.

### Prompt composition

The lens prompt is three blocks, ordered shared-first so the expensive part is cacheable:

1. system — `agents/pr-review-lens.md` + `lenses/_shared.md`. **Cache breakpoint.**
2. user — PR title, PR body, resolved requirements, prior recommendations, the diff, then
   the four pack sections. **Cache breakpoint.**
3. user — `lens: <name>`, that lens's brief from `lenses/<lens>.md`, and `LENS_TAIL`.

Blocks 1 and 2 are ~90% of the prompt and must stay **byte-identical across the three
lenses**; one lens-dependent character and all three calls miss the cache.
`tests/test_prompting.py` asserts it. The lens name and brief live in block 3 for exactly
this reason — never move anything lens-specific above it.

`run_panel` therefore dispatches the first lens alone to write the cache prefix, then the
rest in parallel to read it. Three cold parallel calls would each pay the write premium and
none would read, which is worse than not caching. Staggering is gated on `CACHE_ENABLED`.

Verdict system prompt = `agents/pr-review-verdict.md` + `verdict.md`, uncached — one call per
PR, no shared prefix to exploit.

The `agents/*.md` files open with a **porting note** blockquote that overrides the doctrine
below it for this deployment (no tools, no merging, context pushed rather than fetched). The
doctrine itself is carried close to verbatim from the `pr-reviewer` plugin in
`stebennett/nyx-claude` so improvements flow both ways — put deployment-specific caveats in
the porting note or in `LENS_TAIL`, not in the shared doctrine.

Each lens brief follows a fixed shape: `## Your lens`, `## Not your lens`, `## Walk`,
`## Blocking bar`, `## Not blocking`, `## Example finding`. Keep it when editing.

### Schemas mirror doctrine

`FINDING_SCHEMA`, `LENS_SCHEMA` and `VERDICT_SCHEMA` in `review.py` are the machine-readable
form of the return contracts written out in `doctrine/lenses/_shared.md` and
`doctrine/verdict.md`. Change one and you must change the other. Schemas are `strict` with
`additionalProperties: false`, so a field the doctrine describes as optional has to be
declared nullable instead (see `failure_scenario`).

`run_panel` enforces the doctrine's hard consistency rules after adjudication — approve
implies `blocker_count == 0`, request-changes implies `>= 1`, body starts with the marker —
and raises rather than posting an unsound review.

## Invariants worth knowing before changing behaviour

- **Drafts and Renovate-authored PRs are never reviewed**, in any mode, not even with an
  explicitly named PR or `--force`. A draft has not been offered for review; Renovate PRs
  belong to the separate `renovator` skill and the two must never contend over a PR.
- **Posting requires explicit opt-in** (`--post`, or `DRY_RUN=0`). `resolve_post()` is the
  only place that decides; `--dry-run` always wins.
- **Standard library only.** The deployment is a stock `python:3.13-slim` image with this
  script and `doctrine/` mounted from a ConfigMap — there is no install step, so a new
  import from PyPI breaks it. `openssl` is shelled out to for GitHub App JWT signing, and the
  checkout arrives as a tarball rather than via `git`, for exactly this reason. Test code is
  bound by this too: `unittest`, never `pytest`.
- **The pack must never fail a review.** Every acquisition and assembly path degrades — to a
  per-file API fetch, then to a smaller pack, then to no pack — recording a note in
  `ctx.notes`. A thin review beats no review, so `build_context` catches broadly and still
  yields. The corollary matters when you work on it: a bug in a pack part degrades silently
  instead of raising, so pack parts earn their correctness from tests, not from runtime noise.
- **Blocks 1 and 2 of the lens prompt must be byte-identical across the three lenses.** Never
  interpolate anything lens-specific above the tail block. This is what the entire caching
  saving rests on, and it fails silently — nothing breaks, the cost just doubles.
- **v1 is review-only**: it never merges, pushes, labels or edits. An `approve` verdict posts
  an approving review and stops.
- Inline comments that anchor to an untouched line make GitHub reject the *entire* review, so
  `post_review()` falls back to folding them into the body on a 422.
- One failing PR must not abort a pass — `main` catches per-PR and per-repo and counts
  failures into the exit code.

## Configuration

Per-repo overrides live in `.claude/pr-reviewer.json` in the *target* repo. Beyond the
selection knobs, the pack and caching read: `context` (on/off), `max_context_chars` (83000,
the pack's total budget), `max_context_files` (25), `max_tarball_bytes` (50000000), and
`cache` (on/off). `--no-context` and `--no-cache` do the same from the CLI and always win.

`ignore_paths` was declared here and read nowhere for a long time; it is now honoured by the
changed-files packer, the grep corpus and the path tree.

## Tuning review quality

The doctrine is where review quality lives; `review.py` is plumbing. Tune with `--diff-file`
against a PR you know well, one lens at a time, and `--save` both runs to compare. Read the
lens briefs before switching models — they assume a reviewer that can follow a lot of
instruction.

Two cautions learned the hard way. **Caching is provider-dependent**: OpenRouter routes the
same model to different providers call to call, and some return zero cached tokens, so a
single zero reading proves nothing — re-run before concluding. And when comparing `--save`
output, remember the pack must be deterministic for the comparison to mean anything; if you
add a pack part, build its needles from an ordered structure, never by iterating a `set`.
