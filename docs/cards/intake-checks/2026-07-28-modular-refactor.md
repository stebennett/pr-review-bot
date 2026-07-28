---
verdict: fail
criteria: {INT-AC-OBSERVABLE: pass, INT-REQ-RESOLVES: pass, INT-VERTICAL: pass, INT-COVERAGE: pass, INT-NO-OVERLAP: fail, INT-DAG: pass, INT-MILESTONE: fail, INT-SIZED: fail}
---
# Intake check — modular refactor backlog (24 cards, REQ-001..REQ-027)

Spec: `docs/superpowers/specs/2026-07-28-modular-refactor-design.md`
Board: empty — the checked proposal was the whole board.
`size_limit`: 500 changed lines including tests.

> **Run 1 of `check_budget.intake: 2`.** This is the first, failing proposal. It is persisted
> per `INTAKE.md` §Check because a failing run is the most informative one. The reworked
> proposal and its re-check are recorded separately.

## Verdict

**fail** — three blocking criteria. Coverage, requirement resolution, the dependency graph and
the vertical-slice question are all sound; the failures are size arithmetic (nine cards), one
milestone-ordering defect around the import-boundary test, and one direct contradiction between
two cards' acceptance criteria.

Summed, the proposal was ~23,500 changed lines across 24 cards against a 24 × 500 = 12,000
ceiling. At this `size_limit` the work needs roughly 45–50 cards, not 24.

## Criteria

| id | verdict | evidence |
|---|---|---|
| INT-AC-OBSERVABLE | pass | 76 acceptance criteria walked with "what would I run to see this?". Most name a command or assertion. Six marginal, carried as A2. |
| INT-REQ-RESOLVES | pass | All 27 ids REQ-001..REQ-027 resolve to a spec heading, all `**Status:** active`. No dangling or superseded ids. |
| INT-VERTICAL | pass | Ruled explicitly — see below. |
| INT-COVERAGE | pass | All 27 requirements claimed. Two soft spots as A6/A7, neither unclaimed. |
| INT-NO-OVERLAP | **fail** | CARD-016 freezes `openrouter.py` byte-identical; CARD-019 requires `_http` gone. `openrouter()` calls `_http` at `review.py:492` and catches `urllib.error.HTTPError` at `:493`. Finding B11. |
| INT-DAG | pass | 19 edges walked; every edge points to a lower-numbered card, acyclic by construction. One missing edge as A5. |
| INT-MILESTONE | **fail** | Membership clean (M1:4, M2:5, M3:6, M4:2, M5:3, M6:2, M7:1, M8:1 = 24). But CARD-008 (M2) and CARD-014 (M3) need REQ-010 work owned by CARD-017 (M4). Finding B10. |
| INT-SIZED | **fail** | Nine of 24 cards exceed 500. Findings B1–B9. |

## Vertical slice ruling

The extraction cards move modules rather than shipping user-visible capability. **They pass.**
Reading `INT-VERTICAL` as "must ship user-visible capability" would make `INTAKE.md`'s own
`task` type — "internal scaffolding or refactor, no direct user value" — unusable. The operative
test is "independently shippable and testable", and each card meets it three ways: mergeable to
`main` alone leaving a working program; verified without a model call (goldens byte-identical,
suite green, import boundary held); and independently revertible, which REQ-026 states as a
requirement precisely because eleven defects shipped past a green suite during the context-pack
work.

## Size

Method: a relocation counts as delete + add (~2× the moved block), plus import churn and any
test block the acceptance criteria require to move or convert. Estimates derived from real line
ranges in `review.py` (2,577 lines) and `tests/` (3,434 lines).

| card | estimated_lines | over 500 |
|---|---|---|
| CARD-001 | 60 | |
| CARD-002 | 135 | |
| CARD-003 | 70 | |
| CARD-004 | **9,000** | **yes** |
| CARD-005 | 310 | |
| CARD-006 | 250 | |
| CARD-007 | 320 | |
| CARD-008 | **520** | **yes** |
| CARD-009 | 415 | |
| CARD-010 | 440 | |
| CARD-011 | **1,030** | **yes** |
| CARD-012 | 480 | sensitive (A8) |
| CARD-013 | 400 | |
| CARD-014 | 260 | |
| CARD-015 | 380 | |
| CARD-016 | **645** | **yes** |
| CARD-017 | **730** | **yes** |
| CARD-018 | 160 | |
| CARD-019 | 290 | |
| CARD-020 | **620** | **yes** |
| CARD-021 | **710** | **yes** |
| CARD-022 | **1,010** | **yes** |
| CARD-023 | **5,000** | **yes** |
| CARD-024 | 230 | |

**Total ~23,465 changed lines against a 12,000 ceiling.**

## Blocking findings

- **B1 — CARD-004 ~9,000.** Goldens dominate and no slicing reduces them. Requires a
  `size_exclude` entry for the golden directory first; the hand-written part alone (~1,650)
  still needs a three-way split.
- **B2 — CARD-008 ~520.** Marginal; split one card per module (`core/budget` ~300,
  `core/render` ~220).
- **B3 — CARD-011 ~1,030.** Highest-risk module in the repo at twice the ceiling. Split three
  ways.
- **B4 — CARD-016 ~645.** Separate the verbatim relocation from the fake and the new
  panel/retry tests.
- **B5 — CARD-017 ~730.** Four adapters at once; split three ways.
- **B6 — CARD-020 ~620.** Split the REQ-015 confirmation from the read-path and write-path swaps.
- **B7 — CARD-021 ~710.** Split `app/select` from `app/context`.
- **B8 — CARD-022 ~1,010.** Split three ways; the shim card's AC deserves isolated review.
- **B9 — CARD-023 ~5,000.** Reduce to the pytest runner migration; move each test module's
  relocation into the extraction card that moves its production code.
- **B10 — REQ-010 scheduled two milestones after the test that requires it.** CARD-005 (M2)
  installs the boundary test forbidding `core/** → reviewer.log`; `Accounting.report()` calls
  `log()` at `review.py:1868` and moves to `core/` in CARD-008 (M2); `resolve_requirements`
  calls `vlog()` at `:1992` and `:2002` and moves to `core/` in CARD-014 (M3); CARD-017 (M4)
  owns the removal. M2's exit criterion is unreachable.
- **B11 — CARD-016 and CARD-019 contradict.** See INT-NO-OVERLAP above.

## Advisory findings

- **A1** — `size_exclude` has no entry for generated goldens. *(Resolved: `tests/goldens/**`
  added to `config.md` before rework.)*
- **A2** — Six acceptance criteria only marginally observable, including three requiring live
  credentials or model spend. *(Superseded by the hermetic-CI requirement adopted in rework.)*
- **A3** — CARD-017's checkout half is already true at HEAD: `extract_checkout` already uses
  `log()` not `vlog()`, with the reasoning at `review.py:1910` and a test at
  `tests/test_context.py:203`. Only the issue-fetch half is real work.
- **A4** — Eight "goldens are byte-identical" ACs cite REQ-001; the golden net is REQ-022.
  Re-cite so impact analysis surfaces them.
- **A5** — CARD-017 has no `depends_on` edge to CARD-015 despite asserting behaviour whose code
  moves there.
- **A6** — Four REQ-012 invariants asserted by no acceptance criterion; "no state beyond the
  marker" is the one a modular refactor could plausibly erode.
- **A7** — REQ-026 cited on CARD-004 for a REQ-023 property; REQ-026's actual content has no
  observable AC on any card.
- **A8** — CARD-012's estimate is ownership-sensitive (~480 or ~640) depending on which card
  owns the `InMemoryTree` conversion of `TestGrepRepo` / `TestPackCallSites`.

## Spec observations (not card findings)

**REQ-010's premise is inaccurate.** It states `vlog` is called "from inside pack assemblers".
Verified against `review.py`: `vlog` is called only at `:149` (`load_dotenv`), `:224`/`:230`
(`resolve_token`), `:528` (`openrouter`) and `:1992`/`:2002` (`resolve_requirements`). No
`pack_*` assembler calls `log` or `vlog`. The requirement's substance stands, but its scope is
three call sites, not five assemblers.

**REQ-013 and REQ-016 are in unacknowledged tension in the spec itself.** REQ-013 names
`_http (review.py:246)` as replaced by httpx; REQ-016 freezes the module that calls it. The spec
must state which governs `review.py:492-493`.

## Knowledge for `KNOWLEDGE.md`

- Sizing a relocation: a module move costs ~2× its line count in changed lines, before import
  churn and test edits. Size extraction cards against real line ranges in the source, not
  against the spec's per-module budget, which describes the destination file only.
- Generated golden artifacts must be in `size_exclude` before any card that produces them is
  written. They are diffed mechanically, never read line by line, and at production budgets a
  single golden runs to thousands of lines.
- When a card installs a structural test (import boundaries, AST rules), check every later card
  that moves code into the constrained region against that test before fixing the milestone
  plan. A boundary test installed early converts every latent violation into a blocking
  dependency on whichever card removes it.
