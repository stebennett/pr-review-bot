---
id: CARD-011
type: task
layer: core
reqs: [REQ-011, REQ-025]
title: Convert the budget, accounting and inline-truncation tests
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-010]
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
estimated_lines: 244
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The budget sweep is the strongest test in the suite and the one most likely to be quietly weakened by a move. Converting it as its own change keeps that visible.

## Acceptance criteria
- [ ] `TestBudgets`, `TestAccounting` and `TestTruncateInline` (`tests/test_context.py:61-182`) live under `tests/core/` (REQ-025)
- [ ] The existing sweep over every integer budget still passes, all 10,060 cases (REQ-011)

## Notes
Split out of CARD-010 because the two together are ~576 changed lines against a 500 ceiling (intake run 3, finding F5). The sweep criterion belongs here rather than on CARD-010, whose estimate excludes this conversion (intake run 4, advisory A3).
