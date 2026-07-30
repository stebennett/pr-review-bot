---
id: CARD-028
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert TestPackConventions to InMemoryTree (part A)
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
estimated_lines: 330
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`TestPackConventions` is 306 source lines covering discovery, ordering and fencing. Splitting the conversion in two keeps each half reviewable.

## Acceptance criteria
- [ ] The discovery and nearest-first ordering tests from `TestPackConventions` (`tests/test_context.py:1728-2033`) use `InMemoryTree` (REQ-025)
- [ ] They live under `tests/core/pack/` (REQ-025)

## Notes
Sibling of CARD-029.
