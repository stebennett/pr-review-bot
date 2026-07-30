---
id: CARD-021
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert the changed-files budget and utilisation sweeps
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
The budget and utilisation sweeps are what proved the allocator correct over five fix rounds. They have to survive the move to `InMemoryTree` intact.

## Acceptance criteria
- [ ] The budget and utilisation sweeps from `TestPackChangedFiles` use `InMemoryTree` (REQ-025)
- [ ] They live under `tests/core/pack/` (REQ-025)
- [ ] The named utilisation tests are all still present, and test-count parity holds (REQ-004)

## Notes
Sibling of CARD-020 and CARD-022. See CARD-020's notes on the cut points.
