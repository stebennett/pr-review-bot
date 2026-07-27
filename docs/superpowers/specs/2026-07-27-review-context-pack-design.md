# Context pack: giving the lenses more than the diff

**Date:** 2026-07-27
**Status:** approved, not yet implemented

## Problem

The lens doctrine was written for a reviewer with a worktree. `doctrine/lenses/_shared.md`
§Method tells the lens to read around the diff for "context the hunk alone hides", and
`doctrine/agents/pr-review-lens.md` Do-step 5 tells it to use `Read`/`Grep`/`Glob` on a
read-only checkout at the PR head. Neither is true in this deployment: the porting note at
the top of `pr-review-lens.md` revokes both, and the tail of `run_lens()` repeats the
revocation to the model.

The reviewer therefore cannot see four things it is doctrinally supposed to see:

1. **Surrounding code in changed files.** A hunk hides the function it sits inside, the
   guard clause above it, the type it returns.
2. **Callers and call sites.** A changed signature or invariant breaks code the diff never
   shows.
3. **Repo conventions and existing utilities.** The craft lens cannot know the repo already
   has the helper this PR reimplements.
4. **Real requirements.** `review.py:842` resolves requirements as `pr.get("body")`, so the
   requirements lens judges conformity against whatever the author chose to write.

## Approach

Assemble a **context pack** in ordinary deterministic code before dispatching the panel,
and append it to each lens's user message. Still exactly one model call per lens, four per
PR. No agentic tool loop, no new model call, no new dependency.

Two approaches were rejected:

- **Agentic tool loop** — give each lens `read_file`/`grep`/`glob` and let it pull what it
  needs over 3–8 turns. Highest fidelity, and it would let the porting-note carve-out be
  deleted rather than rewritten. Rejected on cost: it overshoots the ~2–3x budget ceiling,
  makes latency unpredictable, and bets the review on the cheap lens model being a
  disciplined tool-caller.
- **Hybrid: pack plus one bounded pull round** — lenses may return
  `status: "needs-context"` naming what they want, fulfilled from the checkout with one
  re-dispatch. This is the right eventual shape, but it should be built after the pack has
  shown where it falls short. The pack's infrastructure — the checkout, the greppable tree
  — is exactly what the hybrid needs, so nothing here is wasted.

Expected cost: ~21k tokens of pack on top of a ~30k-token diff, three times over. Roughly
2x the current ~$0.11 per PR.

## Acquisition

One call: `GET /repos/{repo}/tarball/{sha}`, streamed to a temp file under
`max_tarball_bytes`, extracted with `tarfile` using `filter="data"` — stdlib, available on
the 3.13 target, and the thing that blocks path-traversal entries. Walking the extracted
tree supplies the path list, so no separate `/git/trees` call is needed.

The temp directory is owned by a context manager scoped to one PR: disk holds one checkout
at a time and cleanup is guaranteed on failure.

**Fork PRs.** The head SHA of a fork PR does not reliably resolve in the base repo's
tarball endpoint. Use `pr["head"]["repo"]["full_name"]` for the tarball when present, and
fall back to the base repo when it is null — which happens when the fork has been deleted.
If that fetch fails, the degradation ladder handles it.

## Degradation ladder

The pack must never fail a review.

1. Tarball fetch fails, or exceeds `max_tarball_bytes` → fall back to per-file
   `contents?ref={sha}` fetches for the changed files only. Loses call sites and the tree;
   keeps whole changed files and conventions.
2. That also fails → the pack is empty and the review proceeds exactly as it does today.
3. Either way, the pack states in-band which parts are missing, so a lens knows what it has
   not seen rather than treating absence as evidence.

## Pack contents

Five parts. Budgets are in **characters**, not tokens, so there is no tokenizer dependency.
The total is the config key `max_context_chars` (default 83000); each part's share is a code
constant expressed as a fraction of it, so raising the total scales every part
proportionally.

| Part | Fraction | Default chars |
|---|---|---|
| Changed files | 0.48 | 39,840 |
| Call sites | 0.18 | 14,940 |
| Conventions | 0.14 | 11,620 |
| Requirements | 0.13 | 10,790 |
| Path tree | 0.07 | 5,810 |

Slack in an underfilled part is **not** reallocated to another. Reallocation is a
tuning-time optimisation with no evidence behind it yet.

### Changed files in full

Every file the diff touches, read at head. Whole file when it fits its share; otherwise
hunk-centred windows of ±60 lines, merged where they overlap, separated by explicit
`… N lines elided …` markers so the lens can see it is reading a window rather than a file.

Capped at 25 files, ordered by hunk count descending. Files dropped by the cap are named in
the pack. `ignore_paths` is read here — it is declared in `DEFAULTS` at `review.py:80` and
currently read nowhere in the script, so this is its first consumer. A null-byte sniff in
the first 8KB skips binaries, and files over 512KB are skipped outright rather than
windowed — at that size the file is generated or vendored, whatever `ignore_paths` says.

### Call sites

Extract definition-shaped identifiers from the diff's added and removed lines, matching
`def`, `class`, `function`, `func`, `fn`, `type`, `interface`, `struct`, and
`export const`. Filter to names of 4+ characters against a small stoplist, then grep the
extracted checkout **outside the changed files**.

A symbol with more than ~40 hits is too generic to be informative and is dropped rather
than allowed to eat the budget. Cap: 20 symbols × 3 hits × ±8 lines of surrounding context.

The same pass greps for **importers** of each changed file by module path and basename.
This is cheaper and more precise than symbol matching and should run even when symbol
extraction finds nothing.

### Conventions

Root `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, plus the nearest such file above each
changed directory. `README.md` only when none of those exist.

### Path tree

Pruned, not flat-truncated: full listing for directories containing changed files, plus the
top two levels elsewhere. This is what lets the craft lens notice an existing utility.

### Requirements

Replaces `requirements = pr.get("body")` at `review.py:842`. Parse `#123`,
`Closes #123`/`Fixes`/`Resolves`/`Implements`/`Refs`, and full issue URLs from the PR title
and body; fetch up to 5 linked issue bodies. Also fetch `/repos/{repo}/issues/{n}/comments`
and include **human** comments with bot comments filtered out — a human saying "don't do it
that way" is genuine requirements signal no lens can currently see. The PR body is
prepended, so a PR with no linked issues degrades to exactly today's behaviour.

## Prompt placement

Requirements stay where they are in `run_lens`, ahead of the diff, because they frame the
read. Changed-file context, call sites, conventions and the tree go **after** the diff,
because they are lookups. The tail instruction stays last so the binding constraint is the
final thing read.

The tail instruction is rewritten: you have a context pack but still no tools; every
finding must anchor to a line the diff touches; a truncation marker means you have not seen
that code.

## What reaches the adjudicator

`adjudicate()` already receives `requirements` (`review.py:712`), deliberately — the
verdict doctrine gives the adjudicator the requirements so it can judge conformity claims.
So the precise rule is:

- The **enriched requirements string does** reach the adjudicator, exactly as the plain PR
  body does today. This modestly grows the adjudication prompt.
- The **other four pack parts never do** — not passed, not summarised, not sampled. This is
  the same structural rule as the diff, for the reason `doctrine/agents/pr-review-verdict.md`
  gives.

`adjudicate()` keeps its exact current signature, with a one-line comment at the call site
recording why the pack is absent, so the next reader does not "fix" it.

## Code shape

A new banner section `# Context pack` in `review.py`, between "Selection and triage" and
"The pass" — it is built in `review_pr` and consumed by `run_panel`. Roughly 250 lines,
taking the file to ~1250.

A second module was considered and rejected: the Kubernetes deployment in `home-lab-k8s`
mounts `review.py` and `doctrine/` from a ConfigMap, so a second file changes a deployment
contract in another repository. A line count is the cheaper thing to break.

```python
class Context:
    pack: str            # assembled context; "" when disabled or fully degraded
    requirements: str    # PR body + linked issues + human comments
    notes: list[str]     # what degraded and what was truncated, for the log

@contextmanager
def build_context(gh, repo, pr, diff, cfg, *, enabled, worktree=None) -> Context
```

Supporting helpers: `fetch_checkout`, `diff_paths`, `changed_symbols`, `grep_repo`, and one
`pack_*` function per part. `run_lens` grows a `pack` parameter and `run_panel` threads it
through.

## Configuration

Three new keys in `DEFAULTS`, tunable per-repo via `.claude/pr-reviewer.json`:

```json
{
  "context": true,
  "max_context_chars": 83000,
  "max_tarball_bytes": 50000000
}
```

Two new CLI flags:

- `--no-context` — disable the pack. This is what makes before/after comparison possible,
  and it is the escape hatch when the pack misbehaves on a specific repo.
- `--worktree PATH` — use a local checkout instead of fetching a tarball, so offline
  `--diff-file` mode gets a real pack. Without it, offline mode has no repo and therefore
  no pack; requirements remain whatever `--body` supplies.

`--save` grows a `"pack"` key, recording what the lens was actually fed. Without it a
before/after comparison can show that output changed but not why.

## Anchor validation

The pack's main new risk is a lens citing a `path:line` it found by browsing rather than in
the diff. `_shared.md` etiquette rule 4 already forbids this, but having context makes it
tempting.

Parse hunk headers into a set of valid `(path, line, side)` anchors and check every returned
finding against it. **Log violations; do not drop the findings.** A real bug reported at a
slightly wrong line is worth more than a clean log, and `post_review`'s existing 422
fallback already stops a bad anchor from killing the whole review. The violation count is
the single most useful signal for whether the pack is helping or eroding discipline.

## Doctrine changes

One paragraph. Bullet 1 of the porting note in `doctrine/agents/pr-review-lens.md` is
rewritten: you have no tools, but you are given a context pack; read around the diff there;
a truncation marker means code you have not seen.

`doctrine/lenses/_shared.md`, the three lens briefs and `doctrine/verdict.md` are
untouched, so parity with the upstream `pr-reviewer` plugin in `stebennett/nyx-claude`
holds. This follows the rule in `CLAUDE.md`: deployment-specific caveats belong in the
porting note or the user-message tail, never in the shared doctrine.

## Verification

There is no test suite; verification means running offline mode against a diff you know
well, with `--worktree` pointing at a checkout of it:

```bash
gh pr diff 42 > /tmp/x.diff
python3 review.py --diff-file /tmp/x.diff --no-context --save /tmp/before.json -v
python3 review.py --diff-file /tmp/x.diff --worktree ~/Code/thatrepo --save /tmp/after.json -v
```

Three things to read from the comparison:

1. Did new findings appear that **genuinely needed** context — a caller, a convention, an
   existing utility — rather than just more findings?
2. Did the anchor-violation count stay at zero?
3. Did any part's budget bite? Each part logs chars used against chars allowed. This line
   is part of the build, not an afterthought: without it an empty part is
   indistinguishable from a truncated one.

Also confirm the degradation ladder by hand: point `--worktree` at a nonexistent path and
at a directory that is not a checkout, and confirm the review still completes with a
smaller pack rather than failing.

## Out of scope

- The hybrid `needs-context` re-dispatch round.
- Prompt caching of the shared pack prefix across the three lenses. It would cut cost, but
  the lenses dispatch in parallel with differing system prompts, so there is no shared
  prefix to hit and the cache writes would race. Revisit only if cost becomes a problem.
- Any change to merging, posting or state. v1 remains review-only and stateless.
