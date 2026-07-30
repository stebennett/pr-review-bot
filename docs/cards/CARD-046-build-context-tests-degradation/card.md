---
id: CARD-046
type: task
layer: app
reqs: [REQ-001, REQ-025]
title: Convert the build_context tests — acquisition and degradation
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-045]
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
estimated_lines: 256
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The degradation paths are the ones that must never raise, and the ones a temp-directory test models worst. Converting them first proves the ladder behaves identically as a type choice.

## Acceptance criteria
- [ ] The config and filesystem degradation tests from `TestBuildContext` (`tests/test_context.py:263-380`) live under `tests/app/` (REQ-025)
- [ ] The `_pr` and `_FakeGH` helpers (`:253-262`) move with them (REQ-025)
- [ ] Every degradation still records a note and still yields a context (REQ-001)

## Notes
Sibling of CARD-047. `TestBuildContext` is 294 source lines (~588 changed) and does not fit on one card with the code (intake run 3, finding F3). The cut falls at `:381`, which is a semantic boundary rather than an even halving, so this half is ~256 and CARD-047 is ~352 (intake run 4, advisory A9).

`_FakeGH` was owned by no card in earlier proposals — it fell in the gap between two cited line ranges, and its only consumers are in this half (intake run 4, advisory A1).
