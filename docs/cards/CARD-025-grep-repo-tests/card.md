---
id: CARD-025
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert TestGrepRepo to InMemoryTree
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-024]
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
estimated_lines: 210
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Grepping a repository is the pack operation most awkward to test against a temp directory, and the one an in-memory dict models most cleanly.

## Acceptance criteria
- [ ] `TestGrepRepo` (`tests/test_context.py:1436-1540`) uses `InMemoryTree`, not a temp directory (REQ-025)
- [ ] It lives under `tests/core/pack/` (REQ-025)

## Notes
None yet.
