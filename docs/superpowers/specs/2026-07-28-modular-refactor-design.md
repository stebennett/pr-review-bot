# A modular reviewer: pure core, adapter edges, and a container to ship it in

**Date:** 2026-07-28
**Status:** approved, not yet implemented

## Problem

`review.py` is 2,577 lines in one file, and four separate things are wrong with that.

1. **No concern can be held in isolation.** Reading about the context pack means scrolling
   past auth, HTTP, OpenRouter and selection. The banner comments mark the boundaries but do
   not enforce them, so nothing stops a change in one section reaching into another.
2. **There is a monolith inside the monolith.** The context pack is ~1,380 of the 2,577
   lines — over half the file — and `pack_changed_files` alone is 210 lines. The section that
   took five fix rounds to get right is the one least amenable to being read.
3. **There are no seams to test behind.** Every test does a flat `import review` and reaches
   into module globals. The pack assemblers take `root: Path | None` and read the filesystem
   themselves, so testing them needs a temp directory rather than a value. `tests/test_context.py`
   has become 2,304 lines for the same reason the source did.
4. **Large files degrade agent edit reliability.** Future work on this repo is more expensive
   and more error-prone than it needs to be, and this repo is explicitly a place where agents
   do the work.

There is also a fifth problem, discovered while scoping this, which is worse than any of the
above and changes what the answer has to be.

### The deployment ships a stale hand-copied duplicate

The Kubernetes deployment does **not** deploy this repository. It deploys
`home-lab-k8s/applications/pr-reviewer/review.py` — a separate copy, 999 lines, byte-identical
to this repo's `main` at `c2286bb`. That is the pre-context-pack version.

So the 48 commits on `feat/context-pack` are not deployed, and cannot be deployed without
manually copying a 113 KB file into another repository. The ConfigMap mechanism flattens paths
into keys (`doctrine.lenses.craft.md`) and rebuilds them with an `items:` mapping in
`cronjob.yaml`, and the YAML's own comment names the trap: *"Keep the two lists in sync — a key
added here but not mapped there simply never appears in the pod."*

For a doctrine file, a missed entry is a degraded prompt. For a Python module it is an
`ImportError` that kills every review, discovered when the CronJob next fires. Under a modular
layout the cost is not "two YAML lists" — it is a manual cross-repo file copy per module, with
a silent, total failure mode on any miss.

This is why the refactor and the deployment change belong to the same piece of work: modularity
is not shippable under the current mechanism.

## Approach

Restructure into **ports and adapters**: a pure `core/` of functions over data, an
`adapters/` layer holding every side effect, and an `app/` layer that wires them together. Ship
the result as a container image built from this repository, so file count stops being a
deployment cost.

Two properties make this worth the ceremony in a program this size, and both are specific to
this codebase rather than general architecture preference:

- **The degradation ladder collapses into a type.** The spec that introduced the context pack
  defines four acquisition rungs, and today each is expressed as `root is None` / `gh is None`
  branching scattered across five assemblers. Under a `SourceTree` port each rung is simply
  *which implementation you were handed*, and the assemblers stop knowing that degradation
  exists.
- **Two invariants become impossible to violate rather than merely tested.** The byte-identical
  cache prefix and the adjudicator's blindness to the diff are both currently upheld by
  convention plus a test. Both can be made structural — see "Invariants, enforced structurally".

### Rejected alternatives

- **A flat package with coarse modules** (~10 files, no nesting). Shortest migration and the
  simplest import graph, but `pack.py` stays ~1,200 lines, so it relocates the worst problem
  instead of solving it.
- **A responsibility-based package with a `pack/` subpackage** (~20 files, boundaries following
  the existing banner comments). This was the recommendation, because the split would have been
  largely a move rather than a redesign, keeping the golden-artifact diff trivial to read. It
  was rejected in favour of ports and adapters on the strength of the two properties above:
  responsibility-grouping gives smaller files but no new guarantees.
- **Modular source, concatenated into one shipped file.** Preserves the ConfigMap deployment
  exactly and needs no infrastructure. Rejected because it introduces a build step whose output
  is what runs in production while the source you edit is something else — the worst property to
  add to a program whose failure mode is a silent prompt-shape regression.
- **Keeping the ConfigMap and generating the two YAML lists from the file tree.** Removes the
  sync-drift risk without a container. Rejected because it does nothing about the hand-copied
  duplicate, which is the actual defect.

## Architecture

### REQ-001 — Ports-and-adapters module layout
**Status:** active

The package is laid out as:

```
review.py                         # 3-line shim -> reviewer.app.cli:main
reviewer/
  config.py             ~90   DEFAULTS and pure config resolution      (stdlib, core-safe)
  log.py                ~40   log, vlog, die                           (adapters and app only)
  ports.py              ~60   the Protocols core depends on
  core/                        PURE — no I/O, no network, no clock
    target.py           ~20   parse_target
    diff.py            ~180   _hunks, diff_paths, diff_anchors, anchor_violations, diff_size
    budget.py          ~180   CONTEXT_SHARES, budgets, Accounting, _capped, fence handling
    render.py          ~100   merge_ranges, windowed, is_binary, path_matches
    schemas.py          ~70   FINDING_SCHEMA, LENS_SCHEMA, VERDICT_SCHEMA
    prompt.py          ~140   lens and verdict prompt composition, LENS_TAIL
    marker.py           ~60   MARKER_RE parse/compose, round and SHA recovery
    consistency.py      ~50   approve <=> zero blockers, marker-first, anchor rules
    pack/
      changed_files.py ~320   the 210-line packer, decomposed
      call_sites.py    ~200   changed_symbols, pack_call_sites
      conventions.py   ~135
      tree.py           ~45
      requirements.py   ~60   issue_refs, requirements assembly
  adapters/                    EVERY side effect
    env.py              ~50   .env loading
    auth.py             ~60   GitHub App credentials and token resolution
    github.py          ~200   PRs, issues, comments, post_review
    openrouter.py      ~240   request shape frozen; transport ported (REQ-016)
    doctrine.py         ~30   loads doctrine/*.md from disk
    trees/
      local.py         ~140   LocalTree: read/walk/grep a real directory
      tarball.py       ~120   fetch and extract, yields a LocalTree
      api.py           ~100   ApiTree: the per-file contents?ref fallback
      empty.py          ~30   EmptyTree: the fully-degraded rung
  app/
    select.py          ~130   candidate PRs, triage, round counting
    context.py         ~180   build_context: choose a tree, assemble, record notes
    panel.py           ~200   run_lens, staggered dispatch, adjudicate, enforce consistency
    review.py          ~120   review_pr, review_diff_file
    cli.py             ~150   build_parser, resolve_post, resolve_cache, main
```

### REQ-002 — `review.py` remains a root-level shim
**Status:** active

`review.py` remains at the repository root as a three-line shim. Every command in `CLAUDE.md`
and `README.md` keeps working verbatim, and the container entrypoint stays `/app/review.py`,
so the eventual `home-lab-k8s` change is a volume swap with no `command:` edit.

## The ports

Three, in `reviewer/ports.py`, defined as `typing.Protocol`. Each exists because it has more
than one real implementation or is a seam a test genuinely needs. No port is introduced
speculatively.

### REQ-003 — `SourceTree` port and its four implementations
**Status:** active

```python
class SourceTree(Protocol):
    def read(self, rel: str) -> str | None: ...
    def exists(self, rel: str) -> bool: ...
    def walk(self, cfg: dict) -> Iterable[str]: ...
    def grep(self, needles: Sequence[str]) -> dict[str, list[Hit]]: ...
```

This is the central abstraction. The four acquisition rungs the context-pack spec defines stop
being branching and become implementations:

| Rung | Today | Under this design |
|---|---|---|
| tarball checkout | `root: Path` | `TarballTree` -> `LocalTree` |
| `--worktree` | `root: Path` | `LocalTree` |
| per-file API fallback | `root=None` plus `gh` threaded down | `ApiTree` |
| nothing available | `root=None`, `gh=None` | `EmptyTree` |

### REQ-004 — Pack assemblers are pure with respect to a `SourceTree`
**Status:** active

Every `pack_*` assembler takes a `SourceTree` and is pure with respect to it. Three
consequences follow directly:

- The assemblers are testable with an in-memory dict instead of a temp directory.
- "The pack must never fail a review" is enforceable in one place: `read()` returns `None`
  rather than raising, and each adapter owns its own `try/except`.
- A partial implementation is a first-class thing. `ApiTree` can serve `read()` and answer
  `walk()`/`grep()` with emptiness, which is exactly the documented degradation — and the pack
  states in-band what is missing, so a lens does not read absence as evidence.

### REQ-005 — `ModelClient` port
**Status:** active

```python
class ModelClient(Protocol):
    def complete(self, model: str, system, user, schema: dict, *, label: str) -> dict: ...
```

One production implementation. It exists as the seam that lets `app/panel.py`'s staggered
dispatch, retry ladder and consistency enforcement be tested without a network and without
cost — today none of that logic can be exercised without spending money.

### REQ-006 — `IssueSource` port
**Status:** active

```python
class IssueSource(Protocol):
    def issue(self, number: int) -> dict | None: ...
    def comments(self, number: int) -> list[dict]: ...
```

The narrow read-only slice of GitHub that requirements resolution needs. Kept separate from the
write side deliberately: nothing on the requirements path should be able to post.

## Invariants, enforced structurally

The existing invariants are preserved. Three of them stop depending on care.

### REQ-007 — The byte-identical cache prefix is structurally enforced
**Status:** active

Blocks 1 and 2 of the lens prompt must be identical across
the three lenses, and the failure is silent — nothing breaks, the cost doubles. Today a test
asserts this. Instead, `core/prompt.py` splits the builder so that

```python
def build_shared_blocks(...) -> tuple[list[dict], list[dict]]   # NO lens parameter
def build_lens_tail(lens: str, brief: str) -> dict
```

The shared builder has no `lens` argument, so lens-dependence in the cached prefix is not
merely detected — it cannot be expressed. The existing assertion in `tests/test_prompting.py`
stays as a second line of defence.

### REQ-008 — The adjudicator never sees the diff or the pack
**Status:** active

`build_verdict_prompt(pr, requirements, envelopes, prior_review)` has no parameter capable of
carrying either, and lives in a module that does not import the pack types. The mutation tests
added for finding I4 — which caught appending both the diff and the pack via `run_panel` —
carry over unchanged.

### REQ-009 — Layer boundaries are enforced by an import test
**Status:** active

A test walks the AST of every module and asserts:

- `reviewer/core/**` imports only the standard library, `reviewer.ports`, `reviewer.config`,
  and other `reviewer.core` modules;
- `reviewer/core/**` never imports `reviewer.adapters`, `reviewer.app` or `reviewer.log`;
- `reviewer/adapters/**` never imports `reviewer.app`.

`reviewer.config` is on the permitted list because it is reduced to `DEFAULTS` and pure
resolution over a dict; `.env` loading — the one side effect it performs today — moves to
`adapters/env.py`.

This is what keeps the "pure core" claim true over time. It also preserves the old
standard-library-only rule precisely where it still has value — the core stays dependency-free
and portable — while the edges are free to use libraries.

### REQ-010 — The core does not log
**Status:** active

Writing to stderr is a side effect, and `die()` counts as one: it lives in `reviewer/log.py`
alongside `log` and `vlog`, so the boundary of REQ-009 forbids all three to `core/`.

Exactly four call sites leak into what becomes the pure core: `parse_target` calls `die()` at
`review.py:654`; `Accounting.report()` calls `log()` at `:1868`; and `resolve_requirements` calls
`vlog()` at `:1992` and `:2002`. Every other call site lands in `adapters/` or `app/`, where
logging is permitted. No `pack_*` assembler logs at all.

`parse_target` is the one to watch, because `die` reads as an error path rather than as logging:
it raises instead, and `app/cli.py` converts the exception to the same message and exit code.

Diagnostics from core travel back as data instead: `Accounting` already collects per-section
budget usage and truncation notes, and `ctx.notes` already carries degradation reasons. `app/`
emits them. This also fixes a real defect the ledger recorded as out of scope — a thinned
requirements string is invisible without `-v`. Once those are notes rather than log lines, the
caller decides how loud they are.

`extract_checkout` is already correct and needs no change: it uses `log()` deliberately, for the
reason recorded in the comment at `review.py:1910`.

Because the import boundary of REQ-009 forbids `core/` importing `reviewer.log`, this obligation
is discharged by whichever change moves each offending function into `core/`, not afterwards.

### REQ-011 — `_capped` remains the single cut point for pack content
**Status:** active

`core/budget.py` is the only module
containing truncation logic; assemblers never slice strings themselves. The 10,060-case sweep
over every integer budget carries over unchanged, as does the rule that a fifth per-section
cutter is never added.

### REQ-012 — The existing behavioural invariants are preserved unchanged
**Status:** active

Unchanged and restated: only four steps call a model; each model call names its own model;
there is no state anywhere beyond the marker; drafts and Renovate-authored PRs are never
reviewed; posting requires explicit opt-in; `tarfile`'s `filter="data"` is load-bearing on the
3.13 target; one failing PR must not abort a pass; v1 is review-only.

## Dependencies

The standard-library-only rule existed because the ConfigMap deployment has no install step. A
container has one, so the rule is relaxed at the edges and retained in the core by the import
test above.

### REQ-013 — Adopt githubkit, httpx, PyJWT and pytest
**Status:** active

| Dependency | Replaces | Why |
|---|---|---|
| `githubkit` | hand-rolled REST calls in `GitHub`, `select`, `prior_rounds`, `post_review` | Typed client with native GitHub App auth |
| `httpx` | `_http` (`review.py:246`) | Real timeouts, retries, connection pooling; `githubkit` is built on it |
| `PyJWT` + `cryptography` | `_app_jwt` (`review.py:161-195`) | Removes an `openssl` **subprocess** and hand-rolled base64url/PKCS1 handling |
| `pytest` (dev only) | `unittest` runner | Runs the existing 263 `unittest` classes unchanged, so migration is additive |

`_http` is replaced everywhere it is called, including at `review.py:492` inside
`openrouter()`'s retry ladder. REQ-016 governs how that particular call is verified, not whether
it changes.

### REQ-014 — The `openssl` shell-out is deleted
**Status:** active

Because `githubkit` performs App authentication itself using `PyJWT`, `adapters/auth.py` shrinks
to credential resolution and configuration rather than crypto. The `openssl` shell-out — a
binary dependency on the base image that exists only because PyPI was unavailable — is deleted.

The staging deliberately does this in two steps rather than one. Stage 4a replaces the
`openssl` subprocess with direct `PyJWT` signing, which is a standalone win that stands whatever
happens later. Stage 4c may then delegate the same work to `githubkit`'s own installation-auth
strategy, superseding most of 4a's code. That is expected, not waste: 4a removes the shell-out
immediately and independently of whether the client swap survives its verification.

### REQ-015 — The GitHub client choice is confirmed against the real API surface
**Status:** active

`githubkit` is the intended client, confirmed against the real API surface at Stage 4c. If GitHub
App installation auth or the 422 inline-comment fallback does not map cleanly onto it, the
fallback is `PyGithub`; if neither maps cleanly, the hand-rolled calls stay on `httpx` and the
stage is dropped. This is a decision with a documented trigger, not an open question.

### REQ-016 — `adapters/openrouter.py` is ported under a cache-measurement gate
**Status:** active

`adapters/openrouter.py` carries the `cache_control` content-block structure,
`provider: {"require_parameters": true}`, the three-attempt retry ladder and `cached_tokens`
logging. That is the machinery behind the measured 0.93x cost figure, and it fails silently: a
wrong request shape does not error, it simply stops caching and doubles the bill.

It is therefore ported to `httpx` deliberately rather than exempted from REQ-013, and the port
is gated on **measurement rather than inspection**. The gate: a live run against the real
OpenRouter API reports non-zero `cached_tokens` on the second and third lens calls, consistent
with the 91% cache-read figure Gate 1 recorded. The port does not land until that measurement
passes. Because OpenRouter routes the same model to different providers call to call, a single
zero reading proves nothing and is re-run before it is believed.

The OpenAI SDK is still not adopted: the port replaces the transport call and its exception
type, and nothing else. The retry ladder's branching behaviour — three attempts on the same
status codes as today — is preserved and pinned by a test.

This is the one verification in this design that cannot be hermetic, and therefore the one that
is never a CI job (REQ-028).

### REQ-017 — Runtime and development dependencies are separated and pinned
**Status:** active

Runtime dependencies are pinned in `requirements.txt`; `requirements-dev.txt` holds `pytest` and
never enters the image.

## Deployment

Confined to this repository. The `home-lab-k8s` change is the user's, made later.

The cluster already runs `ghcr.io/stebennett/slack-invite-mgr-{web,backend}:2.0.2`, built by
that repository's own `release.yml`, with Renovate already watching image tags in
`home-lab-k8s`. This follows an established pattern rather than introducing one.

### REQ-018 — A container image and its build pipeline are defined in this repository
**Status:** active

```
Dockerfile              python:3.13-slim; pip install -r requirements.txt;
                        COPY reviewer/ review.py doctrine/; non-root user;
                        ENTRYPOINT ["python3", "/app/review.py"]
.dockerignore
requirements.txt        pinned runtime dependencies
requirements-dev.txt    pytest; never shipped
.github/workflows/ci.yml       tests and the import-boundary check on every PR
.github/workflows/release.yml  build and push ghcr.io/stebennett/pr-review-bot:X.Y.Z
```

`.env` remains a local convenience and is not in the image; the container reads the same
environment variables from the existing secrets. `.claude/pr-reviewer.json` lives in the
*target* repository and is untouched.

### REQ-019 — The container entrypoint stays `/app/review.py`
**Status:** active

The entrypoint stays `/app/review.py`, so `cronjob.yaml`'s `command:` needs no edit — the
eventual change is swapping a ConfigMap volume for an `image:`.

### REQ-020 — `doctrine/` is baked into the image
**Status:** active

`doctrine/` is baked into the image. That removes all seven doctrine entries from both
YAML lists, so the deployment change is a net simplification rather than a lateral move.

### REQ-021 — Bytecode is precompiled at build time
**Status:** active

Bytecode is precompiled at build time with `compileall`. The pod runs with
`readOnlyRootFilesystem: true` and mounts at `defaultMode: 0555`, so nothing can write
`__pycache__` at runtime.

### REQ-028 — Continuous integration runs only against stubbed endpoints
**Status:** active

No workflow may require live credentials or spend money, so CI never reaches the real GitHub or
OpenRouter. `GITHUB_API` and `OPENROUTER_API` — module constants at `review.py:56-57` with seven
call sites between them — default from the environment, and CI points them at a local stub
server serving canned responses.

Stubbing at the **transport boundary** rather than by injecting in-process fakes is deliberate:
it keeps the real HTTP client, the real auth path and the real retry ladder under test, which is
the only thing that makes an image smoke-test worth running at all. A GitHub App JWT is verified
against a key pair generated inside the test rather than against GitHub, which is a stricter
assertion than a live call — it can check `iss`, `iat`, `exp` and `alg`, where a live call only
proves the token was accepted.

The existing 263 tests already satisfy this: none opens a connection. The obligation binds the
new work — the image smoke-test, the auth port, and the 422 inline-comment fallback.

Two verifications are exempt, because both are inherently live and neither can be satisfied by a
stub one has written oneself: REQ-016's cache measurement, and REQ-015's confirmation that the
GitHub client maps onto GitHub's real behaviour. Both are manual, both are recorded on their
card, and neither is ever a CI job.

## Verification

The 263 tests are the obvious safety net, but the dependency swaps force some of them to change
— so the net moves while the code moves. The net therefore has to be anchored to something that
survives both.

### REQ-022 — Golden prompt bytes pin the refactor
**Status:** active

For a refactor, pinning the assembled prompt bytes is a stronger claim
than pinning the findings: findings are stochastic, prompt bytes are not, and identical bytes
mean identical model behaviour by construction. Prompt assembly and `build_context` both run
entirely offline, so this net costs **zero model calls and no money**.

Captured per fixture diff and configuration, byte-for-byte:

- each lens's system blocks and user blocks, all three lenses;
- the verdict prompt;
- `ctx.pack`, `ctx.notes`, `ctx.requirements`.

The harness regenerates these and compares against committed goldens. It is framework-independent
— plain files on disk — so it survives the `pytest` and `httpx` migrations intact.

### REQ-023 — Fixtures are synthetic, committed and self-contained
**Status:** active

A set of diffs and a small source tree
constructed to stress the parts that matter: one that fills the changed-files budget, one that
forces hunk windowing, one that forces the dropped-file trailer, one carrying adversarial
backtick fences, one that adds only new files. No fixture depends on a checkout existing on a
particular machine; that fragility is part of what this work removes.

### REQ-024 — Two new structural tests ship with the refactor
**Status:** active

Two new structural tests: the golden comparison above, and the import-boundary AST check.

### REQ-025 — The test layout mirrors the source, with two fakes
**Status:** active

Test layout mirrors the source. `tests/test_context.py` is 2,304 lines and is split into
`tests/core/`, `tests/adapters/` and `tests/app/`. Two fakes replace most existing scaffolding:
`InMemoryTree` (a dict of path to content, implementing `SourceTree`) and `RecordingModelClient`
(implementing `ModelClient`).

Mutation testing becomes available as a dev dependency rather than a hand-rolled exercise. It is
offered at the end, not mandated.

### REQ-026 — The migration proceeds in independently revertible stages
**Status:** active

Each stage is independently verifiable and independently revertible. This matters because the
project's own ledger records that eleven defects shipped past a fully green suite during the
context-pack work.

| Stage | Content | Goldens |
|---|---|---|
| 0 | Synthetic fixtures; capture goldens; add the regenerate-and-compare test. No production code moves. | *established* |
| 1 | Extract pure `core/`: `target`, `diff`, `budget`, `render`, `schemas`, `marker`. Moves only. | byte-identical |
| 2 | Introduce `SourceTree`; rewrite the five assemblers against it, deleting `root is None` branching. | byte-identical |
| 3 | Extract `adapters/`: github, openrouter, doctrine, trees. Still standard library; no swaps. | byte-identical |
| 4a | `PyJWT` + `cryptography`; delete the `openssl` shell-out. | byte-identical |
| 4b | `httpx`. | byte-identical |
| 4c | `githubkit`. | byte-identical |
| 5 | Split `app/`: select, context, panel, review, cli. | byte-identical |
| 6 | `pytest` migration and the test-layout split. | byte-identical |
| 7 | `Dockerfile`, requirements files, CI and release workflows, documentation. | byte-identical |
| 8 | The `--worktree` head-SHA change. | **changes, intentionally** |

Stage 8 is last and alone so that the only stage where goldens are expected to move is the one
where a behaviour change was requested, and the diff should be exactly one label.

## Behaviour changes

Exactly one, and it is deliberate.

### REQ-027 — `--worktree` verifies the checkout is at the PR head
**Status:** active

Today the head SHA is never checked and
the section is labelled conservatively in all cases. The new behaviour verifies it, and on a
mismatch **warns and degrades**: a note is recorded, the conservative label is applied, and the
pack is still built. It does not reject — rejecting a stale checkout would violate the standing
rule that the pack must never fail a review, and would break the offline tuning loop that
`CLAUDE.md` prescribes.

This subsumes the parked minor at `review.py:2128`, where `local_checkout=bool(worktree)` labels
a rejected worktree that fell back to per-file API fetches as "not known to be at the PR head".
Computing the label correctly requires the correct predicate, so the fix arrives as part of this
change rather than as separately reopened scope.

## Out of scope

- **The `home-lab-k8s` deployment change.** This repository produces an image; switching the
  CronJob from a ConfigMap volume to that image is a separate change in a separate repository.
- **The other three parked minors** (`_capped` not being a true cap; `pack_conventions`
  truncating silently at exactly budget 167; `pack_tree`'s fixed three-backtick fence). Recorded
  with rulings in the ledger, deliberately left.
- **The two ledger follow-ups**: documenting `pack_changed_files`' 15-character margin with a
  property test, and skipping files whose diff covers their whole body. Both are behaviour or
  quality work, and this is a structural change.
- **Rewriting `adapters/openrouter.py`'s request shape or adopting an SDK for it.** Its transport
  call *is* ported to httpx under REQ-016's measurement gate; everything else about the module is
  out of scope.
- **Any change to review quality, doctrine, prompts, or cost.** If a golden moves outside
  Stage 8, that is a defect, not an improvement.
- **The hybrid `needs-context` re-dispatch round**, still deferred from the context-pack design.
