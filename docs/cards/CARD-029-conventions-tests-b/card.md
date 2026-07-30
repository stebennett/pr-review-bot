---
id: CARD-029
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert TestPackConventions to InMemoryTree (part B)
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-027]
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
estimated_lines: 282
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The fencing and budget-squeeze half of the conventions tests, which is where the adversarial-backtick behaviour is pinned.

## Acceptance criteria
- [ ] The fencing and budget tests from `TestPackConventions` use `InMemoryTree` (REQ-025)
- [ ] They live under `tests/core/pack/` (REQ-025)

## Notes
Sibling of CARD-028.
