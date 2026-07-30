---
id: CARD-012
type: task
layer: core
reqs: [REQ-001, REQ-022, REQ-025]
title: Extract core/render
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
estimated_lines: 306
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Small pure helpers for windowing, binary detection and path matching. Moving them early gives the pack assemblers something to depend on that is already inside the boundary.

## Acceptance criteria
- [ ] `merge_ranges`, `windowed`, `is_binary` and `path_matches` live in `core/render.py` (REQ-001)
- [ ] `TestPathMatches`, `TestIsBinary`, `TestMergeRanges` and `TestWindowed` (`tests/test_context.py:683-769`) move with them (REQ-025)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
None yet.
