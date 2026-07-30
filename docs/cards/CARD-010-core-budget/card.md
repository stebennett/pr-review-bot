---
id: CARD-010
type: task
layer: core
reqs: [REQ-001, REQ-010, REQ-011, REQ-022]
title: Extract core/budget; Accounting returns diagnostics as data
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-006]
branch: ""
worktree: ""
design_pr_url: ""
pr_urls: []
split_slices: 0
adrs: []
reworks:
  slice: 0
  design: 0
  implement: 0
  split: 0
  deliver: 0
review_lenses_failed: []
estimated_lines: 332
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`Accounting.report()` calls `log()`, which the import boundary forbids to `core/`. Returning per-part usage as data instead also fixes a real defect the ledger recorded as out of scope — a thinned requirements string is invisible without `-v`. Once those are notes rather than log lines, the caller decides how loud they are.

## Acceptance criteria
- [ ] `_capped` is the only budget-slicing code in the package, assertable by AST (REQ-011)
- [ ] `Accounting.report()` returns per-part usage as data; the entry point emits it; `core/budget.py` does not import `reviewer.log` (REQ-010)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
A fifth per-section cutter is never added — `_capped` stays the single cut point.

The test conversion is CARD-011, not here: `tests/test_context.py:61-182` addresses `review.budgets` / `review.Accounting` / `review._truncate_inline` and stays green against `review.py`'s re-export until that card lands.
