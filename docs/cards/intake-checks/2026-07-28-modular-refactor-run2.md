---
verdict: fail
criteria: {INT-AC-OBSERVABLE: pass, INT-REQ-RESOLVES: pass, INT-VERTICAL: pass, INT-COVERAGE: fail, INT-NO-OVERLAP: fail, INT-DAG: pass, INT-MILESTONE: pass, INT-SIZED: fail}
---
# Intake check run 2 — modular refactor backlog (39 cards, REQ-001..REQ-028)

Spec: `docs/superpowers/specs/2026-07-28-modular-refactor-design.md` — 28 requirements.
Run 1: `2026-07-28-modular-refactor.md`. **Final budgeted run** (`check_budget.intake: 2`).

## Verdict

**fail** — eight blocking findings, none of which is CARD-005.

The re-slice worked. Aggregate size is now **~14,530 counted lines across 39 cards against a
19,500 ceiling**, median ~330, where run 1 was ~23,500 against 12,000. Seven of run 1's nine
size breaches are resolved, and `INT-MILESTONE` and `INT-DAG` now pass. What remains is
localized: four cards need splitting, one dependency edge needs inverting, one AC needs adding,
and one systematic gap — test-relocation ownership — needs applying to eight more cards.

## Criteria

| id | verdict | note |
|---|---|---|
| INT-AC-OBSERVABLE | pass | 108 criteria walked. Materially better than run 1 — the three live-credential ACs are gone via REQ-028 stubbing. Three marginal, all advisory. |
| INT-REQ-RESOLVES | pass | All cited ids resolve and carry `**Status:** active`, including REQ-028. |
| INT-VERTICAL | pass | Same ruling as run 1. Three new card shapes re-examined and also pass: test-only conversion, measurement-only, and spike. |
| INT-COVERAGE | **fail** | REQ-010 incomplete (B1), REQ-025 incomplete (B2), REQ-016's gating clause unclaimed (B3). |
| INT-NO-OVERLAP | **fail** | `prior_rounds` claimed by two cards with a third implied (B4). |
| INT-DAG | pass | 44 edges walked; acyclic by construction. |
| INT-MILESTONE | pass | 39 cards, each in exactly one milestone (M1:5, M2:7, M3:9, M4:4, M5:7, M6:5, M7:1, M8:1). Run 1's failure resolved. |
| INT-SIZED | **fail** | Four unwaived breaches (B5–B8). CARD-005 waived by recorded driver override. |

## Blocking findings

**B1 — REQ-010's fourth leak is unclaimed.** `parse_target` calls `die()` at `review.py:654`;
`die` lives in `log.py`, which REQ-009 forbids to `core/**`. CARD-007 moves `parse_target` into
`core/target.py` one card after the boundary test is installed, carrying neither REQ-010 nor an
AC about it, so it cannot go green. The checker audited every `log`/`vlog`/`die` call site to
bound this: exactly one addition, no others. *(Spec corrected: REQ-010 now names four sites and
flags `die` explicitly.)*

**B2 — ~2,100 lines of test relocation belong to no card.** Run 1's B9 fix moved relocation onto
extraction cards, but only CARD-007, CARD-008, CARD-016 and CARD-018 say so — and CARD-038's own
note disclaims the rest. Unowned: `TestPackConventions` (306), `TestPackTree` (139),
`TestBuildContext` (294), `TestCheckoutMatchesDiff` (126), budget/accounting (122), render (87),
`TestChangedSymbols` (66), fence-balance (100), checkout (70), plus all 459 lines of
`tests/test_prompting.py`, which mixes core/prompt, adapters/openrouter, app/cli and app/panel
tests in one file and must be split four ways. REQ-025 is not covered. Expect ~9 more cards.

**B3 — REQ-016's landing gate is unenforced.** REQ-016 says "the port does not land until that
measurement passes", but `CARD-029 depends_on [CARD-028]` means the port merges first.
`depends_on` means "after"; a gate cannot live downstream of what it gates.

**B4 — `prior_rounds` is claimed twice, with a third home implied.** CARD-023 →
`adapters/github.py`; CARD-033 → `app/select.py`; REQ-001's layout → `core/marker.py` (CARD-007).
One 15-line function, three destinations — and it is the function recovering all of this
program's state.

**B5–B8 — four cards over 500:** CARD-016 (~1,200), CARD-018 (~562), CARD-036 (~540),
CARD-015 (~513).

**Waived, recorded, not a cause of this verdict:** CARD-005 at ~1,600 (driver override).
Independently costed at ~1,600 against the driver's ~1,650 — within 3%.

## On the driver override (CARD-005)

The override is sound, but the recorded reason is not the strongest. "Useless apart" is not quite
true — harness plus one fixture is a complete working unit. The argument that holds: **the fixture
source tree is shared, and `pack_tree` renders the whole tree into every fixture's pack**, so
adding tree files in a later card would move goldens established by an earlier one, churning the
net during the exact window it is being built.

Two cautions. `right_sized: true` is the correct mechanism, but it means this is the card's only
pre-code size check ever. And all 34 downstream "goldens byte-identical" ACs anchor to whatever
net it produces, executed when calibration is lowest. Recommended added AC: the harness runs green
against the first fixture before the remaining four are added.

## Advisory findings

- **A1** — CARD-002 under-estimated ~1.6x (~420 vs 260); the missing term is the canned-response
  corpus. Still under the ceiling.
- **A2** — `seg` and `_blocks` have no stated home, and the default is a boundary violation. They
  sit in the OpenRouter section today; CARD-024 relocates that to `adapters/`, but CARD-011's
  `build_shared_blocks` must call `seg` from `core/`. They are pure and are prompt structure, so
  they belong in `core/prompt.py` under CARD-011, with CARD-024 leaving them behind.
  `strip_fence` correctly stays with the adapter.
- **A3** — CARD-030 is a second live verification, which REQ-028 said did not exist. *(Spec
  corrected: REQ-028 now names two exemptions.)*
- **A4** — CARD-030 AC-3 instructs board mutation; a card cannot close other cards. Move to notes.
- **A5** — two unstated thresholds: CARD-029's "consistent with 91%", CARD-016's "coverage no
  lower" (needs a tool not in dev deps).
- **A6** — three ACs cite REQ-012 on cards whose `reqs` omit it, so impact analysis cannot see
  them.
- **A7** — milestone headings must use `**Exit criteria:**` and carry a `**Cards:**` line;
  `/kanban` computes progress from it.

## Spec observations — all three corrected after this run

- REQ-016's amendment was incomplete: `spec:116` still read `HAND-ROLLED AND UNTOUCHED` and the
  *Out of scope* list still forbade rewriting the module, both contradicting REQ-016 and REQ-013.
- REQ-010's "exactly three call sites" was four.
- REQ-028 claimed a single exemption; REQ-015's client confirmation is a second.

## Knowledge for `KNOWLEDGE.md`

- Before extracting any function into `core/`, grep it for `log()`, `vlog()` **and `die()`**. All
  three live in `reviewer/log.py`, which the boundary test forbids, so de-logging happens in the
  same change as the move. `die` is the easy one to miss because it reads as an error path.
- Sizing a relocation has two cases. A whole file that moves with mechanical edits is
  rename-detected and counts only its changed lines (~20–40). A block lifted out of a large file
  into a new one is never rename-detected and counts at ~2x. Almost every card in a monolith
  split is the second case.
- When an obligation is discharged "by whichever card moves the function", every affected card
  needs it named in its own `reqs` and ACs. An obligation stated only in the requirement is
  unclaimed, and the card that trips over it is the one that cannot go green.
- A gate expressed as a separate card cannot gate the card it depends on. Gates belong in the
  gated card's own acceptance criteria.
