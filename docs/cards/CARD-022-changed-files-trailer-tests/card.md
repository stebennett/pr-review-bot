---
id: CARD-022
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert the trailer, labelling and file-cap tests
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-019]
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
estimated_lines: 400
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The trailer, the section label and the file cap are the parts a budget squeeze exercises. Their tests convert together because they share fixtures.

## Acceptance criteria
- [ ] The trailer, labelling and file-cap tests from `TestPackChangedFiles` use `InMemoryTree` (REQ-025)
- [ ] They live under `tests/core/pack/` (REQ-025)
- [ ] Test-count parity with the block being replaced (REQ-004)

## Notes
Sibling of CARD-020 and CARD-021. See CARD-020's notes on the cut points.
