# Milestones

Ordered delivery milestones, authored by `/refine` and `/requirement`. Document order = delivery order.
`/kanban` reads this file and never writes it.

The eight milestones below are the eight stages of REQ-026 in
`docs/superpowers/specs/2026-07-28-modular-refactor-design.md`. Stage 8 is last and alone so
that the only milestone where goldens are expected to move is the one where a behaviour
change was actually requested.

## M1 — Pipeline and safety net

**Goal:** Close the deployment gap and make every later pull request independently validated, hermetically.
**Exit criteria:** A tagged build publishes a working image to GHCR; CI runs the test suite, a hermetic image smoke-test and the golden prompt-byte comparison on every pull request, with no workflow reaching the real GitHub or OpenRouter.
**Cards:** CARD-001, CARD-002, CARD-003, CARD-004, CARD-005

## M2 — Pure core extracted

**Goal:** The pure, I/O-free logic lives in `reviewer/core/` behind an import boundary a test enforces.
**Exit criteria:** The AST import-boundary test passes and runs in CI; `build_shared_blocks` has no `lens` parameter and `build_verdict_prompt` has no parameter able to carry the diff or the pack, both verified by `inspect.signature`; no `core/` module imports `reviewer.log`; goldens byte-identical.
**Cards:** CARD-006, CARD-007, CARD-008, CARD-009, CARD-010, CARD-011, CARD-012, CARD-013, CARD-014, CARD-015

## M3 — The pack behind a port

**Goal:** The four-rung degradation ladder becomes a choice of `SourceTree` implementation rather than branching inside the assemblers.
**Exit criteria:** All four rungs are `SourceTree` implementations; no `pack_*` assembler contains `root is None` branching, assertable by grep; every pack test drives `InMemoryTree` rather than a temp directory; goldens byte-identical.
**Cards:** CARD-016, CARD-017, CARD-018, CARD-019, CARD-020, CARD-021, CARD-022, CARD-023, CARD-024, CARD-025, CARD-026, CARD-027, CARD-028, CARD-029, CARD-030, CARD-031, CARD-032, CARD-033

## M4 — Adapters isolated

**Goal:** Every side effect lives at the edge, behind a port the core can depend on.
**Exit criteria:** No `core/` module logs or performs I/O; `.env` loading, doctrine loading, token resolution, GitHub calls and OpenRouter calls all live under `adapters/`; the panel's dispatch and retry logic is exercisable with no network call and no cost; goldens byte-identical.
**Cards:** CARD-034, CARD-035, CARD-036, CARD-037, CARD-038

## M5 — Dependencies adopted

**Goal:** Hand-rolled transport and auth are replaced where a library is better, with the prompt-cache invariant measured rather than assumed.
**Exit criteria:** No `subprocess` call remains in the auth path and `_http` is gone from the package; every request carries an explicit timeout; the OpenRouter cache measurement and the githubkit confirmation are both recorded on their pull requests as the two REQ-028 exemptions; goldens byte-identical.
**Cards:** CARD-039, CARD-040, CARD-041, CARD-042, CARD-043

## M6 — App wired, monolith retired

**Goal:** `review.py` becomes an entry point rather than the program.
**Exit criteria:** `review.py` is three lines and every command in `CLAUDE.md` and `README.md` runs unchanged; posting still requires explicit opt-in and `--dry-run` still wins; **each merged card's pull request reverts cleanly on its own without touching another card's files** (REQ-026); goldens byte-identical.
**Cards:** CARD-044, CARD-045, CARD-046, CARD-047, CARD-048, CARD-049, CARD-050, CARD-051

## M7 — Tests restructured

**Goal:** The suite runs under pytest and its layout mirrors the package.
**Exit criteria:** pytest runs the whole suite green in CI with no test lost; `conftest.py` provides the `InMemoryTree`, `RecordingModelClient` and stub-server fixtures; `pytest` is in `requirements-dev.txt` and absent from the image; goldens byte-identical.
**Cards:** CARD-052

## M8 — Worktree head verification

**Goal:** Land the one intended behaviour change of this refactor, in isolation.
**Exit criteria:** A `--worktree` checkout not at the PR head records a note, keeps the conservative label and still produces a pack; one at the head is labelled as such; the goldens move in exactly the labelling and nowhere else.
**Cards:** CARD-053
