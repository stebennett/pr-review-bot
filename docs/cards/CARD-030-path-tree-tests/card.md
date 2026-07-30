---
id: CARD-030
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert the path-tree tests to InMemoryTree
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
estimated_lines: 188
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The path tree is pruned rather than flat-truncated, and its tests are the only place that distinction is pinned.

## Acceptance criteria
- [ ] `TestPackTree` (`tests/test_context.py:2034-2127`) uses `InMemoryTree` (REQ-025)
- [ ] It lives under `tests/core/pack/` (REQ-025)

## Notes
The four fence fixtures at `tests/test_context.py:2128-2172` sit inside this card's line span but are consumed only by `TestFenceBalanceUnderTruncation`, so they travel with CARD-031 instead (intake run 4, advisory A1).
