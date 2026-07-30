---
id: CARD-008
type: task
layer: core
reqs: [REQ-001, REQ-022, REQ-025]
title: Extract core/diff
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
Diff parsing is the most obviously pure thing in the program and has its own test file already, so it is the cheapest early proof that the boundary test and the golden net both work.

## Acceptance criteria
- [ ] `_hunks`, `diff_paths`, `diff_anchors`, `anchor_violations` and `diff_size` live in `core/diff.py` (REQ-001)
- [ ] `tests/test_diff.py` moves to `tests/core/` with them (REQ-025)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
`tests/test_diff.py` moves as a whole file, so it is rename-detected and costs only ~30 changed lines rather than twice its 240 lines.
